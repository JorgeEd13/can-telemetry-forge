"""Offline, deterministic tests for the F2 fleet simulator + labels + outliers.

Asserts the F2 Definition of Done: one config produces a documented Tier-1
dataset; the failure label is derived in one place and is monotonic in the right
direction; obvious outliers are present and recoverable from labels; and the whole
run is reproducible (same seed → identical, different seed → differs). No network,
no files (the writers are tested separately).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from can_telemetry_forge.anomalies import inject_obvious_outliers
from can_telemetry_forge.config import config_from_dict, default_config
from can_telemetry_forge.labels import FAILURE_MODES, derive_unit_labels
from can_telemetry_forge.signals import Era, era_for_model_year, generate_unit, signal_names
from can_telemetry_forge.sim import build_fleet, simulate
from can_telemetry_forge.sim.drivers import drivers_for_unit


def small_config(**over):
    """A tiny but complete config so the simulator runs fast in CI."""
    base = {"days": 2, "resolution": "5min", "seed": 7}
    base.update(over)
    return config_from_dict(base)


# --- fleet composition -------------------------------------------------------


def test_build_fleet_is_deterministic_and_assigns_era() -> None:
    cfg = small_config()
    a = build_fleet(cfg.fleet, np.random.default_rng(1))
    b = build_fleet(cfg.fleet, np.random.default_rng(1))
    assert [u.unit_id for u in a] == [u.unit_id for u in b]
    assert [u.build_year for u in a] == [u.build_year for u in b]
    for u in a:
        assert u.era is era_for_model_year(u.build_year)
        assert cfg.fleet.build_year_min <= u.build_year <= cfg.fleet.build_year_max
        assert 0.0 < u.duty_base <= 1.0


def test_build_fleet_respects_region_assignment() -> None:
    cfg = small_config()
    region_ids = {r.id for r in cfg.fleet.regions}
    contract_region = {c.id: c.region_id for c in cfg.fleet.contracts}
    for u in build_fleet(cfg.fleet, np.random.default_rng(0)):
        assert u.region_id in region_ids
        assert u.region_id == contract_region[u.contract_id]


# --- driver series -----------------------------------------------------------


def test_wear_is_monotonic_nondecreasing() -> None:
    cfg = small_config()
    region = cfg.fleet.regions[0]
    units = build_fleet(cfg.fleet, np.random.default_rng(0))
    d = drivers_for_unit(units[0], region, cfg.n_steps(), cfg.step_hours(), np.random.default_rng(0))
    assert np.all(np.diff(d.wear) >= -1e-12)
    assert np.all((d.wear >= 0.0) & (d.wear <= 1.0))


def test_harsher_region_drives_more_wear() -> None:
    # Pick a young, low-runtime unit so wear isn't already clamped to 1.0 in both
    # regions — then the region's wear_modifier difference is visible.
    cfg = default_config()
    units = build_fleet(cfg.fleet, np.random.default_rng(0))
    unit = min(units, key=lambda u: u.runtime_start_h)
    n, step = cfg.n_steps(), cfg.step_hours()
    regions = {r.id: r for r in cfg.fleet.regions}
    harsh = drivers_for_unit(unit, regions["arid_highland"], n, step, np.random.default_rng(1))
    mild = drivers_for_unit(unit, regions["temperate_lowland"], n, step, np.random.default_rng(1))
    assert harsh.wear.mean() > mild.wear.mean()


# --- multi-mode failure label ------------------------------------------------


def _failure_fraction(wear_level: float, seed_count: int = 200) -> float:
    """Share of seeded draws that produce any failure at a given wear level."""
    cfg = small_config()
    region = cfg.fleet.regions[0]
    units = build_fleet(cfg.fleet, np.random.default_rng(0))
    unit = units[0]
    n, step = cfg.n_steps(), cfg.step_hours()
    fails = 0
    for s in range(seed_count):
        drivers = drivers_for_unit(unit, region, n, step, np.random.default_rng(s))
        signals = generate_unit(Era.MODERN, drivers, np.random.default_rng(s))
        wear = np.full(n, wear_level)
        labels = derive_unit_labels(signals, wear, step, cfg.failure_horizon_h, np.random.default_rng(s))
        fails += int(labels.event_index is not None)
    return fails / seed_count


def test_more_wear_yields_more_failures() -> None:
    # Direction is the contract (ADR-009): worse state ⇒ more failures.
    assert _failure_fraction(0.95) > _failure_fraction(0.05)


def test_failure_mode_is_valid_and_horizon_marked() -> None:
    cfg = small_config()
    region = cfg.fleet.regions[0]
    unit = build_fleet(cfg.fleet, np.random.default_rng(0))[0]
    n, step = cfg.n_steps(), cfg.step_hours()
    drivers = drivers_for_unit(unit, region, n, step, np.random.default_rng(3))
    signals = generate_unit(Era.MODERN, drivers, np.random.default_rng(3))
    labels = derive_unit_labels(signals, np.full(n, 0.99), step, cfg.failure_horizon_h, np.random.default_rng(3))
    if labels.event_index is not None:
        assert labels.event_mode in FAILURE_MODES
        # Marked rows lead up to (and include) the event.
        marked = np.nonzero(labels.failure_within_h == 1)[0]
        assert marked[-1] == labels.event_index
        assert (labels.failure_mode[marked] == labels.event_mode).all()


def test_legacy_unit_cannot_fail_on_modern_only_mode() -> None:
    # A Legacy unit has no vibration channel → no bearing-mode evidence.
    cfg = small_config()
    region = cfg.fleet.regions[0]
    unit = build_fleet(cfg.fleet, np.random.default_rng(0))[0]
    n, step = cfg.n_steps(), cfg.step_hours()
    drivers = drivers_for_unit(unit, region, n, step, np.random.default_rng(0))
    signals = generate_unit(Era.LEGACY, drivers, np.random.default_rng(0))
    modes_seen = set()
    for s in range(100):
        labels = derive_unit_labels(signals, np.full(n, 0.99), step, cfg.failure_horizon_h, np.random.default_rng(s))
        if labels.event_index is not None:
            modes_seen.add(labels.event_mode)
    assert "bearing" not in modes_seen  # vibration is era-gated off for Legacy


# --- obvious outliers (labeled, recoverable) ---------------------------------


def test_outliers_are_present_and_recoverable() -> None:
    cfg = default_config()
    region = cfg.fleet.regions[0]
    unit = build_fleet(cfg.fleet, np.random.default_rng(0))[0]
    n, step = cfg.n_steps(), cfg.step_hours()
    drivers = drivers_for_unit(unit, region, n, step, np.random.default_rng(0))
    signals = generate_unit(Era.MODERN, drivers, np.random.default_rng(0))
    masks = inject_obvious_outliers(signals, rate=0.05, rng=np.random.default_rng(0))
    assert masks, "expected some injectable signals"
    # Every injected cell is out of its documented range → recoverable from labels.
    from can_telemetry_forge.signals import get_spec

    for name, mask in masks.items():
        spec = get_spec(name)
        injected = signals[name][mask]
        assert np.all(injected > spec.max_value), f"{name} outlier not out of range"


def test_zero_rate_injects_nothing() -> None:
    cfg = small_config()
    unit = build_fleet(cfg.fleet, np.random.default_rng(0))[0]
    n, step = cfg.n_steps(), cfg.step_hours()
    drivers = drivers_for_unit(unit, cfg.fleet.regions[0], n, step, np.random.default_rng(0))
    signals = generate_unit(Era.MODERN, drivers, np.random.default_rng(0))
    assert inject_obvious_outliers(signals, rate=0.0, rng=np.random.default_rng(0)) == {}


# --- end-to-end simulate -----------------------------------------------------


def test_simulate_shape_and_columns() -> None:
    cfg = small_config()
    ds = simulate(cfg)
    expected_cols = {"unit_id", "t_index", "timestamp_h", *signal_names(),
                     "failure_within_h", "failure_mode", "is_outlier"}
    assert expected_cols <= set(ds.readings.columns)
    # One block of n_steps rows per unit.
    assert ds.readings.shape[0] == ds.units.shape[0] * cfg.n_steps()
    assert set(ds.readings["unit_id"]) == set(ds.units["unit_id"])


def test_era_gated_signals_are_null_not_zero() -> None:
    cfg = small_config()
    ds = simulate(cfg)
    legacy_units = ds.units[ds.units["era"] == "LEGACY"]["unit_id"]
    if len(legacy_units):
        rows = ds.readings[ds.readings["unit_id"].isin(legacy_units)]
        # EGT is Modern-only → must be NaN (NULL), never a real number, for Legacy.
        assert rows["egt_c"].isna().all()


def test_simulate_is_reproducible() -> None:
    a = simulate(small_config(seed=11)).readings
    b = simulate(small_config(seed=11)).readings
    pd.testing.assert_frame_equal(a, b)


def test_simulate_different_seed_differs() -> None:
    a = simulate(small_config(seed=11)).readings
    b = simulate(small_config(seed=12)).readings
    # Fleet composition and/or signals differ; the frames must not be identical.
    assert not a.equals(b)


def test_dimension_tables_are_consistent() -> None:
    ds = simulate(small_config())
    assert set(ds.units["region_id"]) <= set(ds.regions["region_id"])
    assert set(ds.units["contract_id"]) <= set(ds.contracts["contract_id"])
    assert set(ds.units["vehicle_class_id"]) <= set(ds.vehicle_classes["vehicle_class_id"])
