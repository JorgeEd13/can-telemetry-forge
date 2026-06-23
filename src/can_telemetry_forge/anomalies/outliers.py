"""Obvious labeled outliers — the Tier-1 bad-data slice (ADR-006).

Real telemetry has glitches: out-of-range spikes, stuck-to-impossible values. The
MVP injects the *obvious* ones (subtle/joint outliers and sensor faults are F3),
and — crucially — **labels every one** so the defect is recoverable from ground
truth (this is what makes the dataset usable for *supervised* data-quality work).

Each affected reading-cell gets the spike written into the signal array and a
matching ``True`` in a boolean ``is_outlier`` mask aligned to the same rows. Only
non-NULL (era-supported) cells are eligible — we never resurrect an era-gated
signal. Seeded (ADR-005): same rng + rate → identical injection.
"""

from __future__ import annotations

import numpy as np

from ..signals import get_spec, signal_names

# Signals we inject obvious spikes into (engineering signals with a meaningful
# out-of-range "impossible" value). Monotonic/derived fields (runtime, age) and
# DEF level are left alone — a spike there isn't an *obvious* sensor glitch.
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


def inject_obvious_outliers(
    signals: dict[str, np.ndarray | None],
    rate: float,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Inject obvious out-of-range spikes in place and return per-signal masks.

    Args:
        signals: per-signal arrays for one unit (``None`` = era-gated, skipped).
        rate: probability per eligible cell of being an injected outlier.
        rng: the unit's seeded child generator.

    Returns:
        ``{signal_name: bool mask}`` for every injectable, non-NULL signal — the
        ground-truth ``is_outlier`` label aligned to the reading rows. The arrays
        in ``signals`` are mutated in place where an outlier is injected.
    """
    masks: dict[str, np.ndarray] = {}
    if rate <= 0.0:
        return masks

    for name in signal_names():
        if name not in _OUTLIER_SIGNALS:
            continue
        values = signals.get(name)
        if values is None:
            continue
        spec = get_spec(name)
        n = values.shape[0]
        mask = rng.random(size=n) < rate
        if mask.any():
            # An "impossible" spike: push well past the documented max (a clearly
            # out-of-range value a downstream QA step should flag).
            spike = spec.max_value * 1.5 + 1.0
            values[mask] = spike
        masks[name] = mask
    return masks


__all__ = ["inject_obvious_outliers"]
