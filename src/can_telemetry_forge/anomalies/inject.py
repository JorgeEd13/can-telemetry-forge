"""Orchestrator: run the injector registry over one unit's signals (F3, ADR-016).

This is the single entry point the simulator calls. It owns the **labeled-injection
contract**:

1. **Eligibility.** A cell is eligible for a defect only if the signal is present
   for the unit's era (not a structural era-NULL, ADR-008) **and** no earlier
   injector already claimed it. Eligibility is threaded as a per-signal boolean
   mask and shrunk as injectors claim cells, so **at most one defect lands per
   (signal, timestamp) cell** — keeping the single ``anomaly_type`` categorical
   honest (ADR-016).

2. **Per-cell → per-row labels.** Defects are per (signal, timestamp) *cells*, but
   the tidy ``readings`` table is keyed by (unit, timestamp) *rows*. A row can in
   principle carry defects on two different signals at one timestamp. We resolve to
   one label per row by **injector priority = registry order** (obvious outlier
   first … dropout last) and record which **signal** won in ``anomaly_signal``.
   The per-cell ground truth is never lost — it is exactly recoverable by
   re-checking each signal against its range / the labels — but the row-level
   categorical gives downstream ML a clean multiclass target/feature.

3. **Recoverability (ADR-006).** Every injected cell is reflected in the returned
   labels; nothing is injected without a label.

Determinism (ADR-005): one child rng per injector (spawned by the caller's unit
stream) → same config + seed yields byte-identical defects.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .injectors import INJECTORS
from .spec import NO_ANOMALY, VALUE_DISTORTION_TYPES, InjectionHit


@dataclass(frozen=True)
class AnomalyLabels:
    """Per-row anomaly ground truth for one unit (aligned to its reading rows).

    Attributes:
        anomaly_type: object array of tag strings (``""`` where the row is clean);
            the winning defect by injector priority when a row has more than one.
        anomaly_signal: object array of the affected signal name (``""`` if clean).
        is_outlier: boolean rollup — ``True`` where the row carries a
            value-distorting defect (back-compatible with the F2 column). A
            dropout (NULL) is a defect but not a distorted *value*, so it is
            labeled in ``anomaly_type`` but not in ``is_outlier``.
        hits: the raw per-cell hits (for tests/inspection).
    """

    anomaly_type: np.ndarray
    anomaly_signal: np.ndarray
    is_outlier: np.ndarray
    hits: list[InjectionHit]

    def frame_records(self) -> list[tuple[int, str, str, str]]:
        """Per-cell corrupted-frame records for the raw-frame side artifact (F6).

        Returns ``(t_index, signal, anomaly_type, frame_hex)`` tuples — one per cell a
        CAN-frame injector corrupted (the only injectors that populate ``hit.frames``).
        Empty when no frame fault fired, so the artifact is naturally opt-in/empty.
        """
        records: list[tuple[int, str, str, str]] = []
        for hit in self.hits:
            if hit.frames is None:
                continue
            for t_index, frame_hex in hit.frames.items():
                records.append((int(t_index), hit.signal, hit.anomaly_type, frame_hex))
        return records


def apply_anomalies(
    signals: dict[str, np.ndarray | None],
    rates: dict[str, float],
    rngs: dict[str, np.random.Generator],
    n: int,
) -> AnomalyLabels:
    """Inject all registered defects into ``signals`` in place and return labels.

    Args:
        signals: per-signal arrays for one unit (``None`` = era-gated, skipped).
        rates: ``anomaly_type`` → per-cell/segment-start rate. Missing or 0 = off.
        rngs: ``anomaly_type`` → that injector's seeded child generator.
        n: number of timestamps (row count for this unit).

    Returns:
        :class:`AnomalyLabels` — the per-row ground truth. ``signals`` is mutated in
        place where defects were injected.
    """
    # Eligibility starts as "present (non-NULL) for this unit", and shrinks as
    # injectors claim cells so no cell gets two defects.
    eligible: dict[str, np.ndarray] = {
        name: np.zeros(n, dtype=bool) if arr is None else ~np.isnan(arr)
        for name, arr in signals.items()
    }

    all_hits: list[InjectionHit] = []
    for inj in INJECTORS:
        rate = rates.get(inj.anomaly_type, 0.0)
        if rate <= 0.0:
            continue
        rng = rngs[inj.anomaly_type]
        hits = inj.inject(signals, eligible, rate, rng)
        for hit in hits:
            # This injector now owns those cells; later injectors can't reuse them.
            eligible[hit.signal] = eligible[hit.signal] & ~hit.mask
        all_hits.extend(hits)

    return _resolve_row_labels(all_hits, n)


def _resolve_row_labels(hits: list[InjectionHit], n: int) -> AnomalyLabels:
    """Collapse per-cell hits to one label per row by injector priority order.

    ``hits`` already arrive in injector (priority) order; iterating them and only
    writing where the row is still clean makes the first-listed injector win.
    """
    anomaly_type = np.full(n, NO_ANOMALY, dtype=object)
    anomaly_signal = np.full(n, NO_ANOMALY, dtype=object)
    is_outlier = np.zeros(n, dtype=bool)

    for hit in hits:
        unclaimed = hit.mask & (anomaly_type == NO_ANOMALY)
        if unclaimed.any():
            anomaly_type[unclaimed] = hit.anomaly_type
            anomaly_signal[unclaimed] = hit.signal
        # The value-distortion rollup is independent of row-priority resolution:
        # a distorted value is present regardless of which tag won the row.
        if hit.anomaly_type in VALUE_DISTORTION_TYPES:
            is_outlier |= hit.mask

    return AnomalyLabels(
        anomaly_type=anomaly_type,
        anomaly_signal=anomaly_signal,
        is_outlier=is_outlier,
        hits=hits,
    )


# Default per-type rates. Outliers are per-eligible-cell (rare points); sensor
# faults are per-step *segment-start* probabilities (each spawns a ~40-step
# episode), so their cell coverage is much higher than the raw number suggests.
# CAN-frame faults (F6) are rarer still: per-cell point faults (corrupt / error /
# truncated) and a per-step segment-start probability for the stale (held) frame.
DEFAULT_ANOMALY_RATES: dict[str, float] = {
    "obvious_outlier": 0.002,
    "joint_outlier": 0.02,     # of the rows that match a contradiction context
    "sensor_stuck": 2.0e-5,
    "sensor_drift": 2.0e-5,
    "sensor_dropout": 2.0e-5,
    "can_frame_corrupt": 5.0e-4,
    "can_frame_stale": 1.0e-5,        # per-step segment start (held-frame episode)
    "can_frame_error_indicator": 2.0e-4,
    "can_frame_truncated": 2.0e-4,
}


__all__ = ["AnomalyLabels", "apply_anomalies", "DEFAULT_ANOMALY_RATES"]
