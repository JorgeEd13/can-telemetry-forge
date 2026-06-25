"""Offline, deterministic tests for the F5 Tier-2 diversity layer.

Asserts the F5 Definition of Done for Tier 2: config-driven **equipment models**
(distinct reliability + signature profiles) and **seasons** (a configurable
ambient/hazard modifier — the knob a future drift demo shifts) are assigned,
applied, labeled, written out, and reproducible. No network, no real data — the
catalog is documented plausibility for a fictional operator.
"""

from __future__ import annotations

import json

import numpy as np

from can_telemetry_forge.config import (
    SEASONS,
    EquipmentModel,
    Season,
    config_from_dict,
    default_config,
    resolve_season,
)
from can_telemetry_forge.labels import derive_unit_labels
from can_telemetry_forge.signals import Era, generate_unit
from can_telemetry_forge.sim import build_fleet, simulate
from can_telemetry_forge.sim.drivers import drivers_for_unit
from can_telemetry_forge.sim.simulate import _merge_hazard_mults

_BASELINE = SEASONS["baseline"]


def small_config(**over):
    base = {"days": 2, "resolution": "5min", "seed": 7}
    base.update(over)
    return config_from_dict(base)


# --- equipment models --------------------------------------------------------


def test_units_are_assigned_catalogued_models() -> None:
    cfg = default_config()
    units = build_fleet(cfg.fleet, np.random.default_rng(0))
    model_ids = {m.id for m in cfg.fleet.equipment_models}
    classes_with_models = {m.vehicle_class_id for m in cfg.fleet.equipment_models}
    for u in units:
        if u.vehicle_class_id in classes_with_models:
            # A class that has models must hand every unit a valid one…
            assert u.model_id in model_ids
            assert any(
                m.id == u.model_id and m.vehicle_class_id == u.vehicle_class_id
                for m in cfg.fleet.equipment_models
            )
        else:
            # …a class without models stays a generic (class-only) profile.
            assert u.model_id == ""


def test_class_only_fallback_when_no_models() -> None:
    # Strip the catalog: every unit must fall back to the empty (class-only) model.
    cfg = config_from_dict({"fleet": {"equipment_models": []}})
    units = build_fleet(cfg.fleet, np.random.default_rng(1))
    assert units
    assert all(u.model_id == "" for u in units)
    assert all(u.hazard_mult == {} for u in units)


def test_model_build_year_floor_is_respected() -> None:
    # A model that only ever shipped Modern hardware must never be born Legacy.
    cfg = default_config()
    floor_models = {
        m.id: m.build_year_min
        for m in cfg.fleet.equipment_models
        if m.build_year_min is not None
    }
    assert floor_models, "expected at least one capability-floored model (ht_vulcan)"
    units = build_fleet(cfg.fleet, np.random.default_rng(3))
    for u in units:
        if u.model_id in floor_models:
            assert u.build_year >= floor_models[u.model_id]


def test_model_signature_offset_shifts_baseline() -> None:
    # A model carrying a positive coolant offset must run measurably hotter than a
    # zero-offset twin under identical drivers — the offset rides through the clamp.
    cfg = small_config()
    units = build_fleet(cfg.fleet, np.random.default_rng(0))
    base_unit = units[0]
    n, step = cfg.n_steps(), cfg.step_hours()

    cool = base_unit.__class__(**{**base_unit.__dict__, "coolant_offset_c": 0.0})
    hot = base_unit.__class__(**{**base_unit.__dict__, "coolant_offset_c": 8.0})
    region = cfg.fleet.regions[0]

    d_cool = drivers_for_unit(cool, region, _BASELINE, n, step, np.random.default_rng(5))
    d_hot = drivers_for_unit(hot, region, _BASELINE, n, step, np.random.default_rng(5))
    s_cool = generate_unit(Era.MODERN, d_cool, np.random.default_rng(5))
    s_hot = generate_unit(Era.MODERN, d_hot, np.random.default_rng(5))
    assert np.nanmean(s_hot["coolant_temp_c"]) > np.nanmean(s_cool["coolant_temp_c"])


def test_model_hazard_multiplier_changes_failure_rate() -> None:
    # A failure-prone model (hazard > 1) must fail more often than a robust one
    # (hazard < 1) under identical signals/wear — the Tier-2 reliability contract.
    cfg = small_config()
    region = cfg.fleet.regions[0]
    unit = build_fleet(cfg.fleet, np.random.default_rng(0))[0]
    n, step = cfg.n_steps(), cfg.step_hours()
    drivers = drivers_for_unit(unit, region, _BASELINE, n, step, np.random.default_rng(0))
    signals = generate_unit(Era.MODERN, drivers, np.random.default_rng(0))
    wear = np.full(n, 0.9)

    def fail_fraction(mult: dict[str, float]) -> float:
        fails = 0
        for s in range(200):
            labels = derive_unit_labels(
                signals, wear, step, cfg.failure_horizon_h, np.random.default_rng(s), mult
            )
            fails += int(labels.event_index is not None)
        return fails / 200

    prone = {"overheat": 2.0, "oil_starve": 2.0, "bearing": 2.0}
    robust = {"overheat": 0.3, "oil_starve": 0.3, "bearing": 0.3}
    assert fail_fraction(prone) > fail_fraction(robust)


def test_merge_hazard_mults_is_multiplicative_and_total() -> None:
    merged = _merge_hazard_mults({"overheat": 1.5}, {"overheat": 2.0, "bearing": 1.2})
    assert merged["overheat"] == 3.0  # 1.5 × 2.0
    assert merged["bearing"] == 1.2
    assert merged["oil_starve"] == 1.0  # absent everywhere → neutral
    # Every known mode is present so callers can index safely.
    assert set(merged) == {"overheat", "oil_starve", "bearing"}


# --- seasons -----------------------------------------------------------------


def test_resolve_season_named_and_inline() -> None:
    assert resolve_season("heatwave") is SEASONS["heatwave"]
    inline = resolve_season({"id": "x", "label": "X", "ambient_delta_c": 3.0})
    assert isinstance(inline, Season) and inline.ambient_delta_c == 3.0


def test_season_shifts_ambient_and_wear() -> None:
    cfg = small_config()
    region = cfg.fleet.regions[0]
    unit = build_fleet(cfg.fleet, np.random.default_rng(0))[0]
    n, step = cfg.n_steps(), cfg.step_hours()

    base = drivers_for_unit(unit, region, _BASELINE, n, step, np.random.default_rng(9))
    heat = drivers_for_unit(
        unit, region, SEASONS["heatwave"], n, step, np.random.default_rng(9)
    )
    # Heatwave adds a constant ambient delta and a wear multiplier (> 1).
    assert np.isclose(
        np.mean(heat.ambient_c - base.ambient_c), SEASONS["heatwave"].ambient_delta_c
    )
    assert heat.wear.mean() >= base.wear.mean()


def test_heatwave_raises_overheat_hazard_end_to_end() -> None:
    # A heatwave run should produce more failures than a baseline run of the same
    # fleet/seed — the hot ambient + overheat-hazard tilt compounds. (Aggregate over
    # the whole fleet so it isn't sensitive to a single unit's draw.)
    base = simulate(small_config(season="baseline", days=4))
    heat = simulate(small_config(season="heatwave", days=4))
    assert (
        heat.readings["failure_within_h"].sum()
        > base.readings["failure_within_h"].sum()
    )


def test_simulation_is_reproducible_under_a_nonbaseline_season() -> None:
    a = simulate(small_config(season="wet_season"))
    b = simulate(small_config(season="wet_season"))
    assert a.readings.equals(b.readings)
    assert a.equipment_models.equals(b.equipment_models)


# --- writers / provenance ----------------------------------------------------


def test_equipment_models_table_and_season_in_manifest(tmp_path) -> None:
    from can_telemetry_forge.io import write_dataset

    ds = simulate(small_config(season="cold_snap"))
    assert not ds.equipment_models.empty
    assert {"model_id", "hazard_overheat", "build_year_min"} <= set(
        ds.equipment_models.columns
    )

    out = write_dataset(ds, tmp_path, fmt="parquet")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["season"]["id"] == "cold_snap"
    assert manifest["season"]["ambient_delta_c"] == SEASONS["cold_snap"].ambient_delta_c
    # The new dimension table is written alongside the others.
    assert (out / "equipment_models.parquet").exists()


def test_invalid_model_and_season_configs_raise() -> None:
    import pytest

    # Unknown failure-mode key in a model's hazard map.
    bad_model = EquipmentModel(
        id="x", label="x", vehicle_class_id="haul_truck", hazard_mult={"nope": 1.0}
    )
    with pytest.raises(ValueError):
        config_from_dict({"fleet": {"equipment_models": [bad_model.__dict__]}})

    # Unknown named season.
    with pytest.raises(ValueError):
        config_from_dict({"season": "monsoon"})
