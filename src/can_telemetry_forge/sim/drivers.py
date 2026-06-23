"""Per-unit driver-series synthesis (F2).

Bridges the fleet layer to the F1 signal model: given a :class:`Unit` and its
:class:`~can_telemetry_forge.config.Region`, produce the
:class:`~can_telemetry_forge.signals.DriverSeries` (duty cycle, ambient, altitude,
terrain roughness, accumulated wear) that the F1 generators consume.

The driver channels are where the **environment couples both layers** (DATA_DESIGN
§6): a region's climate shapes ambient temperature (a slow seasonal + diurnal
curve), its altitude and terrain are constant per deployment, and its
``wear_modifier`` plus the unit's class ``wear_rate`` set how fast wear climbs over
the window. Wear is monotonic non-decreasing by construction and normalised so a
high-runtime, hard-worked unit in a harsh region approaches — but is clamped to —
full wear (``1.0``), which the failure label and signal degradation key off.

Determinism (ADR-005): the only randomness is the seeded ``rng`` passed in (small
duty jitter); everything else is a closed-form function of the unit + region.
"""

from __future__ import annotations

import numpy as np

from ..config import Region
from ..signals import DriverSeries
from .fleet import Unit

# Diurnal ambient swing is a fraction of the region's seasonal amplitude; both are
# slow relative to a typical short window but keep the signal honest over long runs.
_DIURNAL_FRACTION = 0.4
# Wear normalisation: hours of hard service that map to "fully worn" at neutral
# modifiers. Tuned so a high-hour legacy unit in a harsh region reaches ~1.0 and a
# young unit on an easy contract stays low. Refined in F5.
_WEAR_FULL_SCALE_H = 28_000.0
# Duty cycle is a daily work rhythm: high while working, near-idle off-shift.
_WORK_HOURS_PER_DAY = 10.0
_DUTY_JITTER_SD = 0.05


def _time_hours(n: int, step_hours: float) -> np.ndarray:
    """Elapsed hours at each timestamp (0, step, 2·step, …)."""
    return np.arange(n, dtype=float) * step_hours


def _ambient_series(region: Region, t_h: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Ambient °C: region mean + slow seasonal + diurnal sinusoids (no clamp).

    The seasonal phase is randomised per unit (seeded) so units don't move in
    lockstep; the diurnal cycle is a 24-hour sinusoid.
    """
    seasonal_phase = rng.uniform(0.0, 2.0 * np.pi)
    days = t_h / 24.0
    seasonal = region.ambient_c_amplitude * np.sin(2.0 * np.pi * days / 365.25 + seasonal_phase)
    diurnal = (
        _DIURNAL_FRACTION
        * region.ambient_c_amplitude
        * np.sin(2.0 * np.pi * (t_h % 24.0) / 24.0)
    )
    return region.ambient_c_mean + seasonal + diurnal


def _duty_series(unit: Unit, t_h: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Daily work rhythm around the unit's duty base, lightly jittered, in [0, 1]."""
    hour_of_day = t_h % 24.0
    working = hour_of_day < _WORK_HOURS_PER_DAY
    duty = np.where(working, unit.duty_base, unit.duty_base * 0.1)
    duty = duty + rng.normal(0.0, _DUTY_JITTER_SD, size=t_h.shape)
    return np.clip(duty, 0.0, 1.0)


def _wear_series(unit: Unit, region: Region, t_h: np.ndarray) -> np.ndarray:
    """Monotonic accumulated wear in [0, 1] over the window.

    Starts from the wear implied by the unit's runtime at window start and climbs
    with elapsed runtime, scaled by class wear-rate and region hazard modifier.
    Deterministic (no noise): wear is a state, not a measurement.
    """
    rate = unit.wear_rate * region.wear_modifier
    accumulated_h = unit.runtime_start_h + t_h  # upper bound (assumes mostly running)
    wear = rate * accumulated_h / _WEAR_FULL_SCALE_H
    return np.clip(wear, 0.0, 1.0)


def drivers_for_unit(
    unit: Unit, region: Region, n: int, step_hours: float, rng: np.random.Generator
) -> DriverSeries:
    """Build the F1 :class:`DriverSeries` for one unit over the window.

    ``region`` must be the unit's region. ``rng`` is the unit's own seeded child
    generator (spawned in :mod:`.simulate`), so per-unit randomness is independent
    yet reproducible.
    """
    t_h = _time_hours(n, step_hours)
    ambient = _ambient_series(region, t_h, rng)
    duty = _duty_series(unit, t_h, rng)
    wear = _wear_series(unit, region, t_h)

    return DriverSeries(
        n=n,
        duty_cycle=duty,
        ambient_c=ambient,
        altitude_m=np.full(n, region.altitude_m),
        terrain_roughness=np.full(n, region.terrain_roughness),
        wear=wear,
        runtime_start_h=unit.runtime_start_h,
        age_days=unit.age_days,
        step_hours=step_hours,
    )


__all__ = ["drivers_for_unit"]
