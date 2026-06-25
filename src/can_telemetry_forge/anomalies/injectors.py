"""The concrete anomaly/fault injectors (F3) and the registry that holds them.

Three defect *families*, each a registered :class:`AnomalyInjector` (ADR-016):

* **obvious outlier** — a single out-of-range spike (the F2 slice, refactored in).
  Value clearly impossible *on its own*; the easy data-quality case.
* **joint / contextual outlier** — each column stays **in its own valid range** but
  two signals are made **jointly impossible** (e.g. high fuel rate with near-zero
  engine load; hot coolant with the engine effectively off). The hard case a
  univariate range check misses — only a *contextual* model catches it. The defect
  is labeled on the signal whose value was perturbed.
* **sensor faults** — a healthy, era-capable channel degrades over a **contiguous
  segment** (that is how sensors actually fail), deliberately distinct from the
  structural era-NULL missingness (ADR-008):
    - **stuck** — the channel freezes at one value for the segment.
    - **drift** — a slow linear bias accumulates across the segment.
    - **dropout** — the channel goes NULL (missing) for the segment.

All injectors are pure and seeded (ADR-005); all respect the orchestrator's
``eligible`` masks (no era-NULL cells, no cell another injector already claimed),
so at most one ``anomaly_type`` lands on a cell.
"""

from __future__ import annotations

import numpy as np

from ..signals import get_spec
from .spec import (
    JOINT_OUTLIER,
    OBVIOUS_OUTLIER,
    SENSOR_DRIFT,
    SENSOR_DROPOUT,
    SENSOR_STUCK,
    AnomalyInjector,
    InjectionHit,
)

# --- which signals each family may target ------------------------------------
# Engineering signals with a meaningful "impossible" value; monotonic/derived
# fields (runtime, age) and DEF level are left alone (a spike there is not an
# obvious glitch — same rationale as F2).
_OUTLIER_SIGNALS: tuple[str, ...] = (
    "engine_speed_rpm",
    "coolant_temp_c",
    "oil_pressure_kpa",
    "engine_load_pct",
    "fuel_rate_lph",
    "boost_pressure_kpa",
    "egt_c",
    "vibration_mms",
)

# Physical channels a sensor fault is plausible on (a real transducer can stick,
# drift, or drop out). Derived/computed fields (runtime, age) are excluded.
_SENSOR_SIGNALS: tuple[str, ...] = (
    "engine_speed_rpm",
    "coolant_temp_c",
    "oil_pressure_kpa",
    "engine_load_pct",
    "fuel_rate_lph",
    "boost_pressure_kpa",
    "egt_c",
    "def_level_pct",
    "vibration_mms",
)

# Joint-outlier rules: (driver_signal, predicate_on_driver) → (target_signal,
# in-range but contradictory value to write into target). Each rule encodes a
# documented physical impossibility while keeping the target inside its own range.
#
# Magnitudes are first-pass plausible constants (refined in F5); what is
# contractual is that the *pair* is impossible, while each value alone is valid.
_JOINT_RULES: tuple[dict, ...] = (
    {
        # High fuel rate while engine load is near zero — fuel without work.
        "name": "fuel_without_load",
        "driver": "engine_load_pct",
        "where": lambda load: load < 5.0,          # genuinely unloaded rows
        "target": "fuel_rate_lph",
        "value_frac": 0.55,                          # well above idle fuel, in-range
    },
    {
        # Hot coolant while the engine is essentially off (RPM at/under idle) — a
        # hot engine that isn't running.
        "name": "hot_while_idle",
        "driver": "engine_speed_rpm",
        "where": lambda rpm: rpm < 750.0,            # idle / off
        "target": "coolant_temp_c",
        "value_frac": 0.55,                          # ~115 degC, valid range, but impossible idle
    },
    {
        # High boost pressure with no load — turbo boosting against nothing.
        "name": "boost_without_load",
        "driver": "engine_load_pct",
        "where": lambda load: load < 5.0,
        "target": "boost_pressure_kpa",
        "value_frac": 0.60,
    },
)

# Sensor-fault segment shape: a fault lasts a contiguous run of this many steps
# (drawn around the mean), so faults look like real degradation episodes, not
# per-cell salt. Rate is interpreted as the probability that any given step is the
# *start* of a fault segment on an eligible signal.
_FAULT_SEGMENT_MEAN_STEPS = 40
_FAULT_SEGMENT_MIN_STEPS = 8
_DRIFT_MAX_BIAS_FRAC = 0.40  # peak drift bias as a fraction of the signal's range


def _eligible_indices(eligible: np.ndarray) -> np.ndarray:
    return np.nonzero(eligible)[0]


# --- obvious outlier (refactored from F2) ------------------------------------


def _inject_obvious(
    signals: dict[str, np.ndarray | None],
    eligible: dict[str, np.ndarray],
    rate: float,
    rng: np.random.Generator,
) -> list[InjectionHit]:
    hits: list[InjectionHit] = []
    if rate <= 0.0:
        return hits
    for name in _OUTLIER_SIGNALS:
        values = signals.get(name)
        elig = eligible.get(name)
        if values is None or elig is None or not elig.any():
            continue
        spec = get_spec(name)
        draw = rng.random(size=values.shape[0]) < rate
        mask = draw & elig
        if mask.any():
            # An "impossible" spike well past the documented max — the easy case.
            values[mask] = spec.max_value * 1.5 + 1.0
            hits.append(InjectionHit(name, mask, OBVIOUS_OUTLIER))
    return hits


# --- joint / contextual outlier ----------------------------------------------


def _inject_joint(
    signals: dict[str, np.ndarray | None],
    eligible: dict[str, np.ndarray],
    rate: float,
    rng: np.random.Generator,
) -> list[InjectionHit]:
    hits: list[InjectionHit] = []
    if rate <= 0.0:
        return hits
    for rule in _JOINT_RULES:
        driver = signals.get(rule["driver"])
        target = signals.get(rule["target"])
        elig = eligible.get(rule["target"])
        if driver is None or target is None or elig is None:
            continue
        spec = get_spec(rule["target"])
        # Candidate rows: the physical context that makes a contradiction possible,
        # the target cell still free, and a seeded rate draw.
        context = rule["where"](driver)
        draw = rng.random(size=target.shape[0]) < rate
        mask = context & elig & draw
        if mask.any():
            # An in-range value that is impossible *given the context* — each column
            # alone passes a range check; only the pair is wrong.
            value = spec.min_value + rule["value_frac"] * (spec.max_value - spec.min_value)
            target[mask] = value
            hits.append(InjectionHit(rule["target"], mask, JOINT_OUTLIER))
    return hits


# --- sensor faults (segment-based) -------------------------------------------


def _fault_segments(
    n: int, eligible: np.ndarray, rate: float, rng: np.random.Generator
) -> list[tuple[int, int]]:
    """Pick non-overlapping [start, end) segments on eligible rows, seeded.

    A fault starts at a step with probability ``rate``; its length is drawn around
    the segment mean and clamped so it stays within the window and on contiguous
    eligible rows. Segments never overlap (a fault claims its span).
    """
    if rate <= 0.0:
        return []
    segments: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if eligible[i] and rng.random() < rate:
            length = int(rng.geometric(1.0 / _FAULT_SEGMENT_MEAN_STEPS))
            length = max(_FAULT_SEGMENT_MIN_STEPS, length)
            end = i + length
            # Truncate at the first non-eligible row or the window edge.
            j = i
            while j < end and j < n and eligible[j]:
                j += 1
            if j - i >= _FAULT_SEGMENT_MIN_STEPS:
                segments.append((i, j))
                i = j
                continue
        i += 1
    return segments


def _make_sensor_injector(kind: str) -> AnomalyInjector:
    """Build a stuck/drift/dropout injector sharing the segment machinery."""

    def inject(
        signals: dict[str, np.ndarray | None],
        eligible: dict[str, np.ndarray],
        rate: float,
        rng: np.random.Generator,
    ) -> list[InjectionHit]:
        hits: list[InjectionHit] = []
        if rate <= 0.0:
            return hits
        for name in _SENSOR_SIGNALS:
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
            for start, end in segments:
                mask[start:end] = True
                if kind == SENSOR_STUCK:
                    # Freeze at the value just before the fault (or the first value).
                    frozen = values[start - 1] if start > 0 else values[start]
                    values[start:end] = frozen
                elif kind == SENSOR_DRIFT:
                    # Slow linear bias accumulating across the segment, clamped.
                    span = end - start
                    peak = _DRIFT_MAX_BIAS_FRAC * (spec.max_value - spec.min_value)
                    ramp = np.linspace(0.0, peak, span)
                    values[start:end] = np.clip(
                        values[start:end] + ramp, spec.min_value, spec.max_value
                    )
                elif kind == SENSOR_DROPOUT:
                    # Channel goes missing (NULL), distinct from era-NULL.
                    values[start:end] = np.nan
            hits.append(InjectionHit(name, mask, kind))
        return hits

    descriptions = {
        SENSOR_STUCK: "Sensor frozen at one value over a contiguous segment.",
        SENSOR_DRIFT: "Single-channel slow drift (accumulating bias) over a segment.",
        SENSOR_DROPOUT: "Channel drops out (NULL) over a segment — distinct from era-NULL.",
    }
    return AnomalyInjector(anomaly_type=kind, description=descriptions[kind], inject=inject)


# --- the registry ------------------------------------------------------------
# Order matters: earlier injectors claim cells first (the orchestrator masks them
# off for later ones), so at most one anomaly_type lands per cell. Obvious/joint
# outliers (per-cell) run before sensor faults (segments) so a rare point spike
# never silently overwrites a labeled fault segment. The CAN-frame faults (F6,
# transport layer) run last — they corrupt the *encoded* frame, a distinct fault
# class from the value/transducer defects above.

# Imported here (not at module top) to avoid a cycle: frame_faults imports
# ``_fault_segments`` from this module.
from .frame_faults import FRAME_INJECTORS  # noqa: E402

INJECTORS: tuple[AnomalyInjector, ...] = (
    AnomalyInjector(
        anomaly_type=OBVIOUS_OUTLIER,
        description="Single out-of-range spike — impossible on its own (the easy case).",
        inject=_inject_obvious,
    ),
    AnomalyInjector(
        anomaly_type=JOINT_OUTLIER,
        description="In-range value that is impossible in context (jointly inconsistent pair).",
        inject=_inject_joint,
    ),
    _make_sensor_injector(SENSOR_STUCK),
    _make_sensor_injector(SENSOR_DRIFT),
    _make_sensor_injector(SENSOR_DROPOUT),
    *FRAME_INJECTORS,
)

INJECTOR_BY_TYPE: dict[str, AnomalyInjector] = {inj.anomaly_type: inj for inj in INJECTORS}


__all__ = ["INJECTORS", "INJECTOR_BY_TYPE"]
