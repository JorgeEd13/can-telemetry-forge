"""Offline tests for the F2 config schema, catalog, and JSON merge."""

from __future__ import annotations

import json

import pytest

from can_telemetry_forge.config import (
    RESOLUTION_STEP_HOURS,
    ForgeConfig,
    config_from_dict,
    default_config,
    load_config,
)


def test_default_config_is_valid_and_runnable_scale() -> None:
    cfg = default_config()
    # A medium-leaning default (ADR-011): enough units/steps to hold failures.
    assert cfg.fleet.contracts
    assert cfg.n_steps() == round(cfg.days * 24.0 / cfg.step_hours())
    assert cfg.step_hours() == RESOLUTION_STEP_HOURS[cfg.resolution]


def test_regions_carry_a_public_source_citation() -> None:
    # Provenance is load-bearing (ADR-014): every region cites a public source.
    for region in default_config().fleet.regions:
        assert region.source, f"{region.id} missing public source citation"


def test_config_from_dict_merges_onto_defaults() -> None:
    cfg = config_from_dict({"days": 7, "seed": 99, "resolution": "5min"})
    assert cfg.days == 7
    assert cfg.seed == 99
    assert cfg.resolution == "5min"
    # Untouched fleet keys fall through from the default.
    assert cfg.fleet.operator_name == default_config().fleet.operator_name


def test_load_config_none_returns_default() -> None:
    assert load_config(None).fleet.operator_name == default_config().fleet.operator_name


def test_load_config_from_file(tmp_path) -> None:
    path = tmp_path / "fleet.json"
    path.write_text(json.dumps({"days": 3, "seed": 5}), encoding="utf-8")
    cfg = load_config(path)
    assert (cfg.days, cfg.seed) == (3, 5)


@pytest.mark.parametrize(
    "bad",
    [
        {"resolution": "1h"},
        {"days": 0},
        {"obvious_outlier_rate": 1.5},
        {"failure_horizon_h": -1.0},
    ],
)
def test_invalid_config_raises(bad: dict) -> None:
    with pytest.raises(ValueError):
        config_from_dict(bad)


def test_invalid_fleet_references_raise() -> None:
    base = default_config()
    bad_fleet = {
        "contracts": [
            {"id": "x", "label": "x", "region_id": "nope", "units": 3, "duty_bias": 0.0}
        ]
    }
    with pytest.raises(ValueError):
        config_from_dict({"fleet": bad_fleet})
