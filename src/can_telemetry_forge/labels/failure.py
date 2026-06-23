"""Multi-mode failure-label derivation — the single source of ground truth (ADR-009).

The prediction target is **`failure_within_h`** (within the configured horizon),
but failures are **not one thing**. Three distinct modes are modelled, each with
its own *signature* (the signals that build toward it) and its own *hazard*
(rising with accumulated wear/age and sustained abnormal signal conditions,
modified by environment). Derived in **exactly one place** so the dataset and any
downstream consumer can never disagree:

| Mode            | Signature it builds toward                   |
|-----------------|----------------------------------------------|
| ``overheat``    | sustained high coolant temp / EGT            |
| ``oil_starve``  | falling oil pressure under load              |
| ``bearing``     | rising vibration + accumulated wear          |

Method (per unit, all seeded — ADR-005):

1. For each mode, build a per-timestamp **hazard** in ``[0, ∞)`` from the unit's
   generated signals + wear + age. Signals a unit's era gates off simply don't
   contribute to their mode's hazard (a Legacy unit has no EGT/vibration channel),
   so the available evidence shapes which failures are *predictable* for it —
   itself a realistic property.
2. Convert the summed hazard to a per-step failure probability and **sample one
   failure time** per mode (or none). The earliest sampled failure across modes is
   the unit's event; ``failure_within_h`` is 1 for rows within ``horizon`` hours
   *before* that time, and ``failure_mode`` records which mode it was.

The hazard *magnitudes* are first-pass plausible constants (refined in F5); what is
contractual — and asserted in tests — is the **monotonic direction**: worse
signatures and more wear ⇒ more failures.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Modes, in a fixed order (also the column/category order downstream).
FAILURE_MODES: tuple[str, ...] = ("overheat", "oil_starve", "bearing")
NO_FAILURE = ""  # sentinel mode for units that don't fail in the window

# --- hazard shaping constants (first-pass, refined in F5) ---------------------
# Each mode's hazard is a soft-thresholded "stress" times a wear/age gain. The
# base scale converts accumulated stress into a per-step event probability.
_OVERHEAT_COOLANT_C = 100.0   # coolant stress ramps in above this
_OVERHEAT_EGT_C = 520.0       # EGT stress ramps in above this
_OIL_LOW_KPA = 250.0          # oil-pressure stress ramps in below this, under load
_OIL_LOAD_MIN = 0.35          # only counts as starvation while genuinely loaded
_BEARING_VIB_MMS = 7.0        # vibration stress ramps in above this
_WEAR_GAIN = 2.5              # accumulated wear multiplies every mode's hazard
_HAZARD_BASE = 4.0e-6         # per (stress·step) probability scale


@dataclass(frozen=True)
class UnitLabels:
    """Per-timestamp labels for one unit (aligned to its reading rows).

    ``failure_within_h`` is a 0/1 int array; ``failure_mode`` is an object array of
    mode strings (``""`` where ``failure_within_h == 0``). ``event_index`` is the
    row index of the sampled failure (or ``None``), kept for tests/inspection.
    """

    n: int
    failure_within_h: np.ndarray
    failure_mode: np.ndarray
    event_index: int | None
    event_mode: str


def _soft_excess(values: np.ndarray, threshold: float, scale: float) -> np.ndarray:
    """Stress that ramps from 0 once ``values`` exceed ``threshold`` (per ``scale``)."""
    return np.clip((values - threshold) / scale, 0.0, None)


def _soft_deficit(values: np.ndarray, threshold: float, scale: float) -> np.ndarray:
    """Stress that ramps from 0 once ``values`` fall below ``threshold``."""
    return np.clip((threshold - values) / scale, 0.0, None)


def _mode_hazards(
    signals: dict[str, np.ndarray | None], wear: np.ndarray
) -> dict[str, np.ndarray]:
    """Per-timestamp hazard for each mode from the (era-gated) signals + wear.

    A signal gated off for this unit's era contributes nothing to its mode — the
    available evidence is what shapes the predictable hazard.
    """
    wear_gain = 1.0 + _WEAR_GAIN * wear
    hazards: dict[str, np.ndarray] = {}

    # Overheat: sustained high coolant and/or EGT.
    coolant = signals.get("coolant_temp_c")
    egt = signals.get("egt_c")
    overheat = np.zeros_like(wear)
    if coolant is not None:
        overheat = overheat + _soft_excess(coolant, _OVERHEAT_COOLANT_C, 20.0)
    if egt is not None:
        overheat = overheat + _soft_excess(egt, _OVERHEAT_EGT_C, 100.0)
    hazards["overheat"] = overheat * wear_gain

    # Oil starvation: low oil pressure while genuinely loaded.
    oil = signals.get("oil_pressure_kpa")
    load = signals.get("engine_load_pct")
    oil_starve = np.zeros_like(wear)
    if oil is not None:
        deficit = _soft_deficit(oil, _OIL_LOW_KPA, 150.0)
        if load is not None:
            deficit = deficit * (load / 100.0 >= _OIL_LOAD_MIN)
        oil_starve = deficit
    hazards["oil_starve"] = oil_starve * wear_gain

    # Bearing/mechanical: rising vibration (+ wear gain already applied).
    vib = signals.get("vibration_mms")
    bearing = np.zeros_like(wear)
    if vib is not None:
        bearing = _soft_excess(vib, _BEARING_VIB_MMS, 6.0)
    hazards["bearing"] = bearing * wear_gain

    return hazards


def _sample_event(
    hazard: np.ndarray, step_hours: float, rng: np.random.Generator
) -> int | None:
    """Sample the first failure row from a per-step hazard, or None.

    Per-step probability ``p = 1 - exp(-base·hazard·step_hours)``; the first step
    whose Bernoulli draw fires is the event. Seeded → reproducible.
    """
    p = 1.0 - np.exp(-_HAZARD_BASE * hazard * step_hours / (1.0 / 60.0))
    draws = rng.random(size=hazard.shape)
    fired = np.nonzero(draws < p)[0]
    return int(fired[0]) if fired.size else None


def derive_unit_labels(
    signals: dict[str, np.ndarray | None],
    wear: np.ndarray,
    step_hours: float,
    horizon_h: float,
    rng: np.random.Generator,
) -> UnitLabels:
    """Derive the multi-mode failure label for one unit (single source of truth).

    Samples one candidate failure time per mode from its hazard, takes the earliest
    across modes as the unit's event, and marks the ``horizon_h`` hours of rows
    leading up to it as ``failure_within_h = 1`` with the winning ``failure_mode``.
    """
    n = wear.shape[0]
    hazards = _mode_hazards(signals, wear)

    best_index: int | None = None
    best_mode = NO_FAILURE
    for mode in FAILURE_MODES:
        idx = _sample_event(hazards[mode], step_hours, rng)
        if idx is not None and (best_index is None or idx < best_index):
            best_index, best_mode = idx, mode

    within = np.zeros(n, dtype=np.int8)
    mode_col = np.full(n, NO_FAILURE, dtype=object)
    if best_index is not None:
        horizon_steps = int(round(horizon_h / step_hours))
        start = max(0, best_index - horizon_steps)
        within[start : best_index + 1] = 1
        mode_col[start : best_index + 1] = best_mode

    return UnitLabels(
        n=n,
        failure_within_h=within,
        failure_mode=mode_col,
        event_index=best_index,
        event_mode=best_mode,
    )


__all__ = ["FAILURE_MODES", "UnitLabels", "derive_unit_labels"]
