"""CAN-frame fault injectors (Tier 3, F6 / ADR-019).

The defect families that only exist once a signal is **encoded as an actual J1939
frame** (see ``signals/frames.py``). Each injector encodes the unit's value to its
PGN frame, corrupts the *bytes*, then **decodes back** into the engineering column —
modeling exactly what a real receiver would observe — and records the corrupted
frame hex so the byte-level truth can be emitted as a side artifact.

Four families, each a registered :class:`AnomalyInjector` whose ``anomaly_type`` is a
new *value* in the open vocabulary (ADR-016 — no schema change):

* **``can_frame_corrupt``** — a payload byte in the signal's field flips. Decodes to
  an out-of-range / implausible value (value-distorting).
* **``can_frame_stale``** — the previous frame is re-sent over a contiguous segment.
  The decoded value freezes — but it is a *transport* fault (the bus, not the
  transducer), distinct from ``sensor_stuck`` (value-distorting).
* **``can_frame_error_indicator``** — the field is set to the J1939 error / "not
  available" code. Decodes to ``NULL`` (blanks the value).
* **``can_frame_truncated``** — the frame is shorter than the PGN's DLC, so the
  field's bits are absent. Decodes to ``NULL`` (distinct from era-NULL and
  ``sensor_dropout`` — a malformed-frame NULL).

All injectors are pure and seeded (ADR-005) and respect the orchestrator's
``eligible`` masks (no era-NULL cells, no cell another injector already claimed).
Only **bus signals** (those with a ``FrameLayout``) are targetable — a frame fault is
meaningless for the non-bus derived fields (runtime, age, vibration add-on).
"""

from __future__ import annotations

import math

import numpy as np

from ..signals import get_spec
from ..signals.frames import (
    decode_signal_frame,
    encode_signal_frame,
    frame_to_hex,
)
from .injectors import _fault_segments
from .spec import (
    CAN_FRAME_CORRUPT,
    CAN_FRAME_ERROR_INDICATOR,
    CAN_FRAME_STALE,
    CAN_FRAME_TRUNCATED,
    AnomalyInjector,
    InjectionHit,
)

# Bus signals carry a frame layout; only those can suffer a frame fault. Resolved
# once from the registry so adding a layout to a new signal makes it targetable.
_FRAME_SIGNALS: tuple[str, ...] = tuple(
    name
    for name in (
        "engine_speed_rpm",
        "coolant_temp_c",
        "oil_pressure_kpa",
        "engine_load_pct",
        "fuel_rate_lph",
        "boost_pressure_kpa",
        "egt_c",
        "def_level_pct",
    )
    if get_spec(name).layout is not None
)

# How many bytes shorter than the DLC a truncated frame arrives (drops the field).
_TRUNCATE_TO_BYTES = 3


def _corrupt_byte(frame: bytearray, layout, rng: np.random.Generator) -> bytearray:
    """Flip one byte inside the signal's field to a new random value (seeded)."""
    start = layout.start_bit // 8
    n = layout.bit_len // 8
    idx = start + int(rng.integers(0, n))
    out = bytearray(frame)
    # XOR with a non-zero mask so the byte is guaranteed to change.
    out[idx] ^= int(rng.integers(1, 256))
    return out


def _inject_corrupt(
    signals: dict[str, np.ndarray | None],
    eligible: dict[str, np.ndarray],
    rate: float,
    rng: np.random.Generator,
) -> list[InjectionHit]:
    hits: list[InjectionHit] = []
    if rate <= 0.0:
        return hits
    for name in _FRAME_SIGNALS:
        values = signals.get(name)
        elig = eligible.get(name)
        if values is None or elig is None or not elig.any():
            continue
        spec = get_spec(name)
        draw = (rng.random(size=values.shape[0]) < rate) & elig
        if not draw.any():
            continue
        mask = np.zeros(values.shape[0], dtype=bool)
        frames: dict[int, str] = {}
        for i in np.nonzero(draw)[0]:
            frame = encode_signal_frame(float(values[i]), spec)
            corrupted = _corrupt_byte(frame, spec.layout, rng)
            decoded = decode_signal_frame(corrupted, spec)
            values[i] = decoded  # NaN if the flip hit the NA/error band
            frames[int(i)] = frame_to_hex(corrupted)
            mask[i] = True
        hits.append(InjectionHit(name, mask, CAN_FRAME_CORRUPT, frames=frames))
    return hits


def _inject_stale(
    signals: dict[str, np.ndarray | None],
    eligible: dict[str, np.ndarray],
    rate: float,
    rng: np.random.Generator,
) -> list[InjectionHit]:
    hits: list[InjectionHit] = []
    if rate <= 0.0:
        return hits
    for name in _FRAME_SIGNALS:
        values = signals.get(name)
        elig = eligible.get(name)
        if values is None or elig is None or not elig.any():
            continue
        n = values.shape[0]
        segments = _fault_segments(n, elig, rate, rng)
        if not segments:
            continue
        spec = get_spec(name)
        mask = np.zeros(n, dtype=bool)
        frames: dict[int, str] = {}
        for start, end in segments:
            # The last good frame before the fault is re-sent for the whole segment.
            held_value = float(values[start - 1]) if start > 0 else float(values[start])
            held_frame = frame_to_hex(encode_signal_frame(held_value, spec))
            for i in range(start, end):
                values[i] = held_value
                frames[i] = held_frame
                mask[i] = True
        hits.append(InjectionHit(name, mask, CAN_FRAME_STALE, frames=frames))
    return hits


def _inject_error_indicator(
    signals: dict[str, np.ndarray | None],
    eligible: dict[str, np.ndarray],
    rate: float,
    rng: np.random.Generator,
) -> list[InjectionHit]:
    hits: list[InjectionHit] = []
    if rate <= 0.0:
        return hits
    for name in _FRAME_SIGNALS:
        values = signals.get(name)
        elig = eligible.get(name)
        if values is None or elig is None or not elig.any():
            continue
        spec = get_spec(name)
        draw = (rng.random(size=values.shape[0]) < rate) & elig
        if not draw.any():
            continue
        # Encode the J1939 not-available field (NaN value → all-ones field) once: it
        # is identical for every row of this signal, so it can be cached.
        na_frame = frame_to_hex(encode_signal_frame(math.nan, spec))
        mask = draw
        frames = {int(i): na_frame for i in np.nonzero(draw)[0]}
        values[mask] = np.nan  # decodes to NULL
        hits.append(InjectionHit(name, mask, CAN_FRAME_ERROR_INDICATOR, frames=frames))
    return hits


def _inject_truncated(
    signals: dict[str, np.ndarray | None],
    eligible: dict[str, np.ndarray],
    rate: float,
    rng: np.random.Generator,
) -> list[InjectionHit]:
    hits: list[InjectionHit] = []
    if rate <= 0.0:
        return hits
    for name in _FRAME_SIGNALS:
        values = signals.get(name)
        elig = eligible.get(name)
        if values is None or elig is None or not elig.any():
            continue
        spec = get_spec(name)
        layout = spec.layout
        # A signal whose field already fits in the truncated DLC can't lose its bits;
        # skip it so the fault is honest (its decode would still be valid).
        if layout.start_bit // 8 + layout.bit_len // 8 <= _TRUNCATE_TO_BYTES:
            continue
        draw = (rng.random(size=values.shape[0]) < rate) & elig
        if not draw.any():
            continue
        mask = draw
        frames: dict[int, str] = {}
        for i in np.nonzero(draw)[0]:
            full = encode_signal_frame(float(values[i]), spec)
            short = bytes(full[:_TRUNCATE_TO_BYTES])  # drop the trailing bytes
            decoded = decode_signal_frame(short, spec)  # NaN — field bits absent
            values[i] = decoded
            frames[int(i)] = frame_to_hex(short)
        hits.append(InjectionHit(name, mask, CAN_FRAME_TRUNCATED, frames=frames))
    return hits


# Registered in the same fixed order as their vocabulary entries; the orchestrator
# runs them after the value-domain and sensor-fault injectors (registry order) so a
# rare frame fault never silently overwrites an earlier labeled defect.
FRAME_INJECTORS: tuple[AnomalyInjector, ...] = (
    AnomalyInjector(
        anomaly_type=CAN_FRAME_CORRUPT,
        description="A J1939 payload byte flips → the field decodes to an implausible value.",
        inject=_inject_corrupt,
    ),
    AnomalyInjector(
        anomaly_type=CAN_FRAME_STALE,
        description="A frame is re-sent over a segment → the decoded value freezes (transport fault).",
        inject=_inject_stale,
    ),
    AnomalyInjector(
        anomaly_type=CAN_FRAME_ERROR_INDICATOR,
        description="The field carries the J1939 error/not-available code → decodes to NULL.",
        inject=_inject_error_indicator,
    ),
    AnomalyInjector(
        anomaly_type=CAN_FRAME_TRUNCATED,
        description="A short DLC drops the field's bytes → the field decodes to NULL.",
        inject=_inject_truncated,
    ),
)


__all__ = ["FRAME_INJECTORS", "_FRAME_SIGNALS"]
