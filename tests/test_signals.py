"""Offline, deterministic tests for the F1 signal model.

These assert the F1 Definition of Done: documented operating **ranges**, the
declared **units** (registry self-consistency), cross-signal **correlation signs**,
**era-gating** (an unsupported SPN is NULL, never zero), and **seed
reproducibility**. No network, no generated files.

The correlation tests build contrasting driver series (e.g. low-load vs high-load)
and assert the *sign* of the response — never a magnitude — so refining the
first-pass constants in F5 cannot break the contract as long as the physics
direction holds.
"""

from __future__ import annotations

import numpy as np
import pytest

from can_telemetry_forge.signals import (
    Era,
    TIER1_SIGNALS,
    DriverSeries,
    era_for_model_year,
    gated_signal_names,
    generate_unit,
    get_spec,
    signal_names,
    supported_signal_names,
    supports,
)
from can_telemetry_forge.signals.spec import (
    DRIVER_ALTITUDE_M,
    DRIVER_AMBIENT_C,
    DRIVER_TERRAIN_ROUGHNESS,
    DRIVER_WEAR,
    SignalSpec,
)

N = 240  # a 4-hour window at 1-minute resolution
STEP_H = 1.0 / 60.0


def make_drivers(
    *,
    duty: float = 0.5,
    ambient_c: float = 25.0,
    altitude_m: float = 0.0,
    terrain: float = 0.2,
    wear: float = 0.1,
    runtime_start_h: float = 1000.0,
    age_days: float = 800.0,
    n: int = N,
) -> DriverSeries:
    """A constant-condition driver series; handy for contrasting two scenarios."""
    ones = np.ones(n)
    return DriverSeries(
        n=n,
        duty_cycle=ones * duty,
        ambient_c=ones * ambient_c,
        altitude_m=ones * altitude_m,
        terrain_roughness=ones * terrain,
        wear=ones * wear,
        runtime_start_h=runtime_start_h,
        age_days=age_days,
        step_hours=STEP_H,
    )


def mean_of(era: Era, drivers: DriverSeries, signal: str, seed: int = 0) -> float:
    """Mean of one generated signal under a fresh seeded rng."""
    rng = np.random.default_rng(seed)
    out = generate_unit(era, drivers, rng)
    values = out[signal]
    assert values is not None, f"{signal} unexpectedly gated off"
    return float(np.mean(values))


# --- registry self-consistency -----------------------------------------------


def test_registry_names_unique_and_nonempty() -> None:
    names = signal_names()
    assert len(names) == len(set(names))
    assert all(name and name == name.lower() for name in names)


def test_specs_have_sane_ranges_and_units() -> None:
    for spec in TIER1_SIGNALS:
        assert isinstance(spec, SignalSpec)
        assert spec.unit, f"{spec.name} missing unit"
        assert spec.min_value < spec.max_value, f"{spec.name} bad range"


def test_pgn_recorded_but_inert_by_default() -> None:
    # ADR-013: PGNs are captured for J1939 signals but not used in generation yet.
    j1939_signals = [s for s in TIER1_SIGNALS if s.spn is not None]
    assert j1939_signals, "expected some J1939-backed signals"
    assert any(s.pgn is not None for s in j1939_signals), "PGNs should be recorded"


# --- ranges ------------------------------------------------------------------


@pytest.mark.parametrize("era", [Era.LEGACY, Era.MID, Era.MODERN])
def test_all_signals_within_documented_range(era: Era) -> None:
    drivers = make_drivers(duty=0.9, ambient_c=45.0, altitude_m=3000.0, wear=0.9)
    rng = np.random.default_rng(7)
    out = generate_unit(era, drivers, rng)
    for name, values in out.items():
        if values is None:
            continue
        spec = get_spec(name)
        assert np.all(values >= spec.min_value - 1e-9), f"{name} below min"
        assert np.all(values <= spec.max_value + 1e-9), f"{name} above max"


# --- era gating (NULL, never zero) -------------------------------------------


def test_legacy_unit_gates_modern_signals_to_none() -> None:
    out = generate_unit(Era.LEGACY, make_drivers(), np.random.default_rng(1))
    # Modern-only signals must be NULL (None), not present and not zero.
    for name in ("egt_c", "def_level_pct", "vibration_mms"):
        assert out[name] is None, f"{name} should be gated off for a Legacy unit"
    # Mid signals also gated for Legacy.
    assert out["engine_load_pct"] is None
    # Core engine signals are present.
    assert out["engine_speed_rpm"] is not None
    assert out["coolant_temp_c"] is not None


def test_modern_unit_reports_all_signals() -> None:
    out = generate_unit(Era.MODERN, make_drivers(), np.random.default_rng(1))
    assert all(values is not None for values in out.values())


def test_supported_and_gated_partition_the_schema() -> None:
    for era in (Era.LEGACY, Era.MID, Era.MODERN):
        supported = set(supported_signal_names(era))
        gated = set(gated_signal_names(era))
        assert supported.isdisjoint(gated)
        assert supported | gated == set(signal_names())


def test_non_gated_fields_always_present() -> None:
    # runtime_hours and equipment_age_days are never era-gated.
    for era in (Era.LEGACY, Era.MID, Era.MODERN):
        assert supports(era, get_spec("runtime_hours"))
        assert supports(era, get_spec("equipment_age_days"))


def test_era_for_model_year_boundaries() -> None:
    assert era_for_model_year(1999) is Era.LEGACY
    assert era_for_model_year(2004) is Era.LEGACY
    assert era_for_model_year(2005) is Era.MID
    assert era_for_model_year(2014) is Era.MID
    assert era_for_model_year(2015) is Era.MODERN
    assert era_for_model_year(2026) is Era.MODERN


# --- cross-signal correlation SIGNS (DATA_DESIGN §5) -------------------------


def test_fuel_rate_rises_with_load() -> None:
    low = mean_of(Era.MODERN, make_drivers(duty=0.2), "fuel_rate_lph")
    high = mean_of(Era.MODERN, make_drivers(duty=0.9), "fuel_rate_lph")
    assert high > low


def test_coolant_rises_with_ambient_and_load() -> None:
    base = mean_of(Era.MODERN, make_drivers(ambient_c=10.0, duty=0.3), "coolant_temp_c")
    hot = mean_of(Era.MODERN, make_drivers(ambient_c=45.0, duty=0.3), "coolant_temp_c")
    loaded = mean_of(Era.MODERN, make_drivers(ambient_c=10.0, duty=0.9), "coolant_temp_c")
    assert hot > base
    assert loaded > base


def test_coolant_rises_with_cooling_wear() -> None:
    healthy = mean_of(Era.MODERN, make_drivers(wear=0.05), "coolant_temp_c")
    worn = mean_of(Era.MODERN, make_drivers(wear=0.95), "coolant_temp_c")
    assert worn > healthy


def test_oil_pressure_falls_with_wear() -> None:
    healthy = mean_of(Era.MODERN, make_drivers(wear=0.05), "oil_pressure_kpa")
    worn = mean_of(Era.MODERN, make_drivers(wear=0.95), "oil_pressure_kpa")
    assert worn < healthy


def test_egt_rises_with_altitude_and_load() -> None:
    sea = mean_of(Era.MODERN, make_drivers(altitude_m=0.0, duty=0.4), "egt_c")
    high = mean_of(Era.MODERN, make_drivers(altitude_m=3500.0, duty=0.4), "egt_c")
    loaded = mean_of(Era.MODERN, make_drivers(altitude_m=0.0, duty=0.95), "egt_c")
    assert high > sea
    assert loaded > sea


def test_boost_falls_with_altitude() -> None:
    sea = mean_of(Era.MODERN, make_drivers(altitude_m=0.0, duty=0.6), "boost_pressure_kpa")
    high = mean_of(Era.MODERN, make_drivers(altitude_m=4000.0, duty=0.6), "boost_pressure_kpa")
    assert high < sea


def test_vibration_rises_with_terrain_and_wear() -> None:
    smooth = mean_of(Era.MODERN, make_drivers(terrain=0.05, wear=0.1), "vibration_mms")
    rough = mean_of(Era.MODERN, make_drivers(terrain=0.95, wear=0.1), "vibration_mms")
    worn = mean_of(Era.MODERN, make_drivers(terrain=0.05, wear=0.95), "vibration_mms")
    assert rough > smooth
    assert worn > smooth


def test_runtime_hours_monotonic_nondecreasing() -> None:
    out = generate_unit(Era.MODERN, make_drivers(duty=0.8), np.random.default_rng(3))
    runtime = out["runtime_hours"]
    assert runtime is not None
    assert np.all(np.diff(runtime) >= -1e-9)
    assert runtime[-1] >= runtime[0]


# --- determinism / reproducibility -------------------------------------------


def test_same_seed_same_output() -> None:
    drivers = make_drivers(duty=0.7, wear=0.4)
    a = generate_unit(Era.MODERN, drivers, np.random.default_rng(123))
    b = generate_unit(Era.MODERN, drivers, np.random.default_rng(123))
    for name in signal_names():
        if a[name] is None:
            assert b[name] is None
        else:
            np.testing.assert_array_equal(a[name], b[name])


def test_different_seed_differs_somewhere() -> None:
    drivers = make_drivers(duty=0.7, wear=0.4)
    a = generate_unit(Era.MODERN, drivers, np.random.default_rng(1))
    b = generate_unit(Era.MODERN, drivers, np.random.default_rng(2))
    # At least one noisy signal must differ (hour-meter/age are noise-free).
    assert not np.array_equal(a["coolant_temp_c"], b["coolant_temp_c"])
