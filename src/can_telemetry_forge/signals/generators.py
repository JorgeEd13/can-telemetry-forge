"""Deterministic per-signal generators for one unit's time-series.

This is the heart of F1: each Tier-1 signal is produced by a pure, **deterministic**
function of (a) its documented drivers, (b) the unit's wear/environment state, and
(c) a seeded ``numpy`` generator. No module here touches global randomness — the
``rng`` is threaded in from the caller (ADR-005), so the same seed yields the same
series byte-for-byte.

What "grounded" means in practice (DATA_DESIGN §5, ADR-003/-012):

* Every output is clamped to the signal's documented J1939 operating range
  (``SignalSpec.min_value/max_value``).
* The **cross-signal correlation signs** are structural properties of these
  functions — fuel rate rises with load·RPM, coolant temp rises with ambient+load,
  oil pressure falls with wear, EGT rises with altitude+load, vibration rises with
  terrain roughness+wear. The tests assert these signs over a generated series so
  they can never silently drift.
* Magnitudes (the slopes/offsets below) are first-pass plausible values, not tuned
  against any real log. They live here as named constants so F5 can refine them
  without changing the dependency structure.

Scope note (F1): this models **one unit's** signals given driver series the fleet
simulator will supply in F2 (duty cycle, ambient, altitude, terrain, wear). The
era gate (``eras.py``) decides which of these columns a given unit actually emits;
unsupported signals are NULL, not produced here.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .eras import supports
from .spec import Era, SignalSpec, TIER1_SIGNALS, get_spec

# --- physical/plausibility constants (first-pass, refined in F5) --------------
# Engine speed
_IDLE_RPM = 700.0
_RATED_RPM = 2100.0
# Coolant: cold-start near ambient, regulated toward a thermostat band under load.
_THERMOSTAT_C = 88.0
_COOLANT_LOAD_GAIN_C = 25.0  # extra °C at full load before regulation
_COOLANT_WEAR_GAIN_C = 12.0  # cooling degradation adds headroom at high wear
# Oil pressure: rises with RPM, falls with wear/high oil temp.
_OIL_BASE_KPA = 100.0
_OIL_RPM_GAIN_KPA = 350.0  # added across idle→rated
_OIL_WEAR_LOSS_KPA = 180.0  # lost across no-wear→full-wear
# Fuel rate: dominated by load·RPM.
_FUEL_FULL_LPH = 220.0  # at full load and rated RPM (mid heavy engine)
# Boost: rises with load, falls with altitude (thinner air).
_BOOST_FULL_KPA = 250.0
_BOOST_ALT_LOSS_KPA_PER_KM = 22.0
# EGT: baseline + load, and rises at altitude (leaner mixture, less cooling air).
_EGT_BASE_C = 300.0
_EGT_LOAD_GAIN_C = 250.0
_EGT_ALT_GAIN_C_PER_KM = 18.0
# DEF: drains slowly with runtime; tops up on refill cycles (modelled as sawtooth).
_DEF_DRAIN_PCT_PER_H = 0.6
# Vibration: floor + load + terrain + wear.
_VIB_FLOOR_MMS = 1.5
_VIB_LOAD_GAIN_MMS = 3.0
_VIB_TERRAIN_GAIN_MMS = 6.0
_VIB_WEAR_GAIN_MMS = 8.0

# Small multiplicative measurement noise (seeded). Kept low so correlation signs
# dominate; tests assert signs, not exact values.
_NOISE_SD = 0.02


@dataclass(frozen=True)
class DriverSeries:
    """Per-timestamp driver inputs for one unit over a window (F2 supplies these).

    All arrays share length ``n`` (the number of timestamps). ``wear`` and
    ``duty_cycle`` are unitless in ``[0, 1]``; ``ambient_c`` is °C; ``altitude_m``
    is metres; ``terrain_roughness`` is unitless in ``[0, 1]``. ``runtime_start_h``
    and ``age_days`` are scalars fixed per unit.
    """

    n: int
    duty_cycle: np.ndarray
    ambient_c: np.ndarray
    altitude_m: np.ndarray
    terrain_roughness: np.ndarray
    wear: np.ndarray
    runtime_start_h: float
    age_days: float
    step_hours: float  # time between timestamps, in hours (e.g. 1/60 for 1-min)


def _noise(rng: np.random.Generator, n: int) -> np.ndarray:
    """Seeded multiplicative noise centred on 1.0."""
    return 1.0 + rng.normal(0.0, _NOISE_SD, size=n)


def _clamp(values: np.ndarray, spec: SignalSpec) -> np.ndarray:
    """Clamp to the signal's documented J1939 operating range."""
    return np.clip(values, spec.min_value, spec.max_value)


# --- per-signal deterministic functions --------------------------------------
# Each takes the resolved driver series + already-computed upstream signals and a
# seeded rng, and returns the clamped engineering-unit array. Computed in registry
# order so a signal's drivers are always available before it (the registry is
# authored in dependency order; ``generate_unit`` relies on that).


def _engine_speed_rpm(d: DriverSeries, rng: np.random.Generator) -> np.ndarray:
    spec = get_spec("engine_speed_rpm")
    rpm = _IDLE_RPM + d.duty_cycle * (_RATED_RPM - _IDLE_RPM)
    return _clamp(rpm * _noise(rng, d.n), spec)


def _engine_load_pct(d: DriverSeries, rng: np.random.Generator) -> np.ndarray:
    spec = get_spec("engine_load_pct")
    # Load follows duty cycle and is pushed up by rough/steep terrain.
    load = 100.0 * d.duty_cycle * (0.85 + 0.30 * d.terrain_roughness)
    return _clamp(load * _noise(rng, d.n), spec)


def _coolant_temp_c(
    d: DriverSeries, load_pct: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    spec = get_spec("coolant_temp_c")
    load = load_pct / 100.0
    # Regulated toward the thermostat band; ambient and load add headroom, and
    # cooling-system wear raises the achievable temperature.
    temp = (
        _THERMOSTAT_C
        + 0.15 * (d.ambient_c - 25.0)
        + _COOLANT_LOAD_GAIN_C * load
        + _COOLANT_WEAR_GAIN_C * d.wear
    )
    return _clamp(temp * _noise(rng, d.n), spec)


def _oil_pressure_kpa(
    d: DriverSeries, rpm: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    spec = get_spec("oil_pressure_kpa")
    rpm_frac = (rpm - _IDLE_RPM) / (_RATED_RPM - _IDLE_RPM)
    rpm_frac = np.clip(rpm_frac, 0.0, 1.0)
    press = (
        _OIL_BASE_KPA
        + _OIL_RPM_GAIN_KPA * rpm_frac
        - _OIL_WEAR_LOSS_KPA * d.wear
    )
    return _clamp(press * _noise(rng, d.n), spec)


def _fuel_rate_lph(
    d: DriverSeries, load_pct: np.ndarray, rpm: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    spec = get_spec("fuel_rate_lph")
    rpm_frac = np.clip(rpm / _RATED_RPM, 0.0, 1.5)
    fuel = _FUEL_FULL_LPH * (load_pct / 100.0) * rpm_frac
    return _clamp(fuel * _noise(rng, d.n), spec)


def _boost_pressure_kpa(
    d: DriverSeries, load_pct: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    spec = get_spec("boost_pressure_kpa")
    boost = (
        _BOOST_FULL_KPA * (load_pct / 100.0)
        - _BOOST_ALT_LOSS_KPA_PER_KM * (d.altitude_m / 1000.0)
    )
    return _clamp(boost * _noise(rng, d.n), spec)


def _egt_c(
    d: DriverSeries, load_pct: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    spec = get_spec("egt_c")
    egt = (
        _EGT_BASE_C
        + _EGT_LOAD_GAIN_C * (load_pct / 100.0)
        + _EGT_ALT_GAIN_C_PER_KM * (d.altitude_m / 1000.0)
    )
    return _clamp(egt * _noise(rng, d.n), spec)


def _runtime_hours(d: DriverSeries, rng: np.random.Generator) -> np.ndarray:
    spec = get_spec("runtime_hours")
    # Monotonic accumulation; engine accrues hours only while running (duty>0).
    running = (d.duty_cycle > 0.0).astype(float)
    increments = running * d.step_hours
    hours = d.runtime_start_h + np.cumsum(increments)
    return _clamp(hours, spec)  # deterministic, no noise on an hour-meter


def _def_level_pct(
    d: DriverSeries, runtime_hours: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    spec = get_spec("def_level_pct")
    # Drains with elapsed runtime; refills modelled as a sawtooth (top-up at 0).
    elapsed = runtime_hours - d.runtime_start_h
    drained = (_DEF_DRAIN_PCT_PER_H * elapsed) % 100.0
    level = 100.0 - drained
    return _clamp(level, spec)


def _vibration_mms(
    d: DriverSeries, load_pct: np.ndarray, rng: np.random.Generator
) -> np.ndarray:
    spec = get_spec("vibration_mms")
    vib = (
        _VIB_FLOOR_MMS
        + _VIB_LOAD_GAIN_MMS * (load_pct / 100.0)
        + _VIB_TERRAIN_GAIN_MMS * d.terrain_roughness
        + _VIB_WEAR_GAIN_MMS * d.wear
    )
    return _clamp(vib * _noise(rng, d.n), spec)


def _equipment_age_days(d: DriverSeries, rng: np.random.Generator) -> np.ndarray:
    spec = get_spec("equipment_age_days")
    # Fixed per unit, but advances by one step's worth of days over the window so a
    # long window still reflects ageing. Deterministic, no noise.
    days = d.age_days + np.arange(d.n) * (d.step_hours / 24.0)
    return _clamp(days, spec)


def generate_unit(
    unit_era: Era,
    drivers: DriverSeries,
    rng: np.random.Generator,
) -> dict[str, np.ndarray | None]:
    """Generate all Tier-1 signals for one unit over the driver window.

    Returns a dict ``{signal_name: array}`` in canonical registry order. Signals
    the unit's ``unit_era`` does not support are present with value ``None``
    (the writer emits them as NULL columns — never zero; ADR-008). Determinism:
    the same ``rng`` state + drivers + era → identical output.
    """
    # Compute the full physics first (cheap, vectorised), then gate. Computing the
    # gated signals anyway keeps the upstream dependencies (e.g. load feeds coolant)
    # consistent regardless of which columns survive the era gate.
    rpm = _engine_speed_rpm(drivers, rng)
    load = _engine_load_pct(drivers, rng)
    coolant = _coolant_temp_c(drivers, load, rng)
    oil = _oil_pressure_kpa(drivers, rpm, rng)
    runtime = _runtime_hours(drivers, rng)
    fuel = _fuel_rate_lph(drivers, load, rpm, rng)
    boost = _boost_pressure_kpa(drivers, load, rng)
    egt = _egt_c(drivers, load, rng)
    def_level = _def_level_pct(drivers, runtime, rng)
    vibration = _vibration_mms(drivers, load, rng)
    age = _equipment_age_days(drivers, rng)

    computed: dict[str, np.ndarray] = {
        "engine_speed_rpm": rpm,
        "coolant_temp_c": coolant,
        "oil_pressure_kpa": oil,
        "runtime_hours": runtime,
        "engine_load_pct": load,
        "fuel_rate_lph": fuel,
        "boost_pressure_kpa": boost,
        "egt_c": egt,
        "def_level_pct": def_level,
        "vibration_mms": vibration,
        "equipment_age_days": age,
    }

    out: dict[str, np.ndarray | None] = {}
    for spec in TIER1_SIGNALS:
        out[spec.name] = computed[spec.name] if supports(unit_era, spec) else None
    return out


__all__ = ["DriverSeries", "generate_unit"]
