"""Offline, deterministic tests for the F4 validation layer.

These never hit the network. They exercise the offline adapters (`in_spec`,
`golden`), the pure comparison math, the report renderer, and the `forge validate`
CLI path. The `ved` adapter is only tested via its *graceful-unavailable* path
(empty cache + no Kaggle) — its network fetch is opt-in and out of CI by design.
"""

from __future__ import annotations

import numpy as np
import pytest

from can_telemetry_forge.cli import main
from can_telemetry_forge.config import config_from_dict
from can_telemetry_forge.signals import get_spec, signal_names

from validation import compare_distributions, render_report, run_validation
from validation.compare import histogram_overlap, summarise_signal
from validation.reference import (
    GOLDEN_PROFILE,
    OFFLINE_ADAPTERS,
    REFERENCE_ADAPTERS,
    _check_ved,
    run_validation as run_validation_direct,
)


# A deliberately tiny fleet (one small contract) so each validation run simulates in
# well under a second — the validation tests call run_validation many times.
def small_config(**over):
    base = {
        "days": 1,
        "resolution": "5min",
        "seed": 7,
        "fleet": {
            "contracts": [
                {
                    "id": "t",
                    "label": "Test contract",
                    "region_id": "temperate_lowland",
                    "units": 5,
                    "duty_bias": 0.0,
                }
            ]
        },
    }
    base.update(over)
    return config_from_dict(base)


# --- comparison math ----------------------------------------------------------


def test_histogram_overlap_identical_is_one() -> None:
    rng = np.random.default_rng(0)
    x = rng.normal(size=5000)
    assert histogram_overlap(x, x) == pytest.approx(1.0, abs=1e-9)


def test_histogram_overlap_disjoint_is_zero() -> None:
    a = np.zeros(1000)
    b = np.full(1000, 100.0)
    assert histogram_overlap(a, b) == 0.0


def test_histogram_overlap_empty_is_zero() -> None:
    assert histogram_overlap(np.array([]), np.array([1.0, 2.0])) == 0.0


def test_summarise_drops_nulls() -> None:
    values = np.array([1.0, 2.0, np.nan, 4.0])
    cmp = summarise_signal("x", "u", values)
    assert cmp.n == 3  # the NaN (era-gated NULL) is excluded
    assert cmp.overlap is None  # no reference supplied
    assert cmp.gen_min == 1.0 and cmp.gen_max == 4.0


def test_compare_distributions_covers_present_signals() -> None:
    ds_cols = {"engine_speed_rpm": np.array([800.0, 1500.0, 2000.0])}
    out = compare_distributions(ds_cols, None, {"engine_speed_rpm": "rpm"})
    assert len(out) == 1 and out[0].signal == "engine_speed_rpm"


# --- offline adapters ---------------------------------------------------------


def test_offline_adapters_are_the_non_network_ones() -> None:
    assert set(OFFLINE_ADAPTERS) == {"in_spec", "golden"}
    assert REFERENCE_ADAPTERS["ved"].network is True
    assert REFERENCE_ADAPTERS["in_spec"].network is False


def test_in_spec_passes_on_a_clean_run() -> None:
    run = run_validation(small_config())
    in_spec = next(r for r in run.results if r.adapter == "in_spec")
    assert in_spec.available
    assert in_spec.checks  # at least some signals were range-checked
    assert in_spec.passed, [c for c in in_spec.checks if not c.passed]


def test_in_spec_catches_out_of_range_values() -> None:
    # Build a run, then corrupt one signal beyond its J1939 max and re-check.
    from validation.reference import _check_in_spec, _units_map

    ds = run_validation(small_config())  # noqa: F841 - warms the path
    cfg = small_config()
    from can_telemetry_forge.sim import simulate

    readings = simulate(cfg).readings.copy()
    spec = get_spec("engine_speed_rpm")
    readings.loc[readings.index[0], "engine_speed_rpm"] = spec.max_value + 10_000.0
    result = _check_in_spec(readings, _units_map())
    bad = [c for c in result.checks if not c.passed]
    assert bad and "engine_speed_rpm" in bad[0].name
    assert not result.passed


def test_golden_drift_guard_passes() -> None:
    # The golden adapter is config-independent: it validates the recomputed golden
    # run (in-spec + seed-stable). On an undrifted generator it must pass.
    run = run_validation(small_config())
    golden = next(r for r in run.results if r.adapter == "golden")
    assert golden.available and golden.checks
    assert golden.passed, [c for c in golden.checks if not c.passed]


def test_validation_run_passes_offline() -> None:
    run = run_validation(small_config())
    # No network adapters requested → only offline checks → overall pass.
    assert run.passed
    assert {r.adapter for r in run.results} == set(OFFLINE_ADAPTERS)


# --- ved graceful-unavailable (no network in CI) ------------------------------


def test_ved_degrades_when_fetch_fails(tmp_path, monkeypatch) -> None:
    # When the opt-in VED fetch can't produce data, the adapter reports unavailable —
    # never raises, never fakes a result. We force the failure deterministically so
    # the test is offline regardless of whether `kaggle` is installed or authed.
    import validation.reference as ref
    from can_telemetry_forge.sim import simulate

    def _boom(cache_dir):
        raise RuntimeError("forced: no VED in test")

    monkeypatch.setattr(ref, "_load_ved_frame", _boom)
    readings = simulate(small_config()).readings
    result = ref._check_ved(readings, ref._units_map(), cache_dir=tmp_path / "empty")
    assert result.adapter == "ved"
    assert result.available is False
    assert "unavailable" in result.note.lower()


def test_ved_overlap_with_a_fake_local_csv(tmp_path, monkeypatch) -> None:
    # With a cached CSV present, no network is touched (the fetch branch is skipped),
    # and the adapter computes real overlap on the mapped engine channels.
    import pandas as pd

    import validation.reference as ref
    from can_telemetry_forge.sim import simulate

    cache = tmp_path / "ved"
    cache.mkdir()
    # Minimal VED-schema CSV covering two mapped columns.
    pd.DataFrame(
        {
            "Engine RPM[RPM]": np.linspace(700, 2200, 500),
            "Absolute Load[%]": np.linspace(5, 95, 500),
        }
    ).to_csv(cache / "trip.csv", index=False)
    # Guard: importing kaggle must never happen on the cached path.
    monkeypatch.setattr(
        ref, "_load_ved_frame",
        lambda cache_dir: pd.read_csv(sorted(cache_dir.glob("*.csv"))[0]),
    )
    readings = simulate(small_config()).readings
    result = ref._check_ved(readings, ref._units_map(), cache_dir=cache)
    assert result.available is True
    assert result.comparisons  # at least the two mapped channels compared
    assert any(c.overlap is not None for c in result.comparisons)


def test_run_validation_unknown_dataset_is_skipped(capsys) -> None:
    run = run_validation_direct(small_config(), datasets=("nope",))
    out = capsys.readouterr()
    assert "unknown dataset" in out.err
    assert {r.adapter for r in run.results} == set(OFFLINE_ADAPTERS)


# --- report -------------------------------------------------------------------


def test_report_is_self_contained_markdown() -> None:
    run = run_validation(small_config())
    md = render_report(run)
    assert md.startswith("# Distribution validation report")
    assert "Provenance" in md
    assert "Not real telemetry" in md
    assert "CC-BY 4.0" in md
    for name in signal_names():
        if name in {"runtime_hours", "equipment_age_days"}:
            continue
        # engine-core signals should appear in at least one distribution table
    assert "`in_spec`" in md and "`golden`" in md


# --- CLI ----------------------------------------------------------------------


def _tiny_config_file(tmp_path) -> str:
    # A tiny JSON config so `forge validate` doesn't generate the 90-day default fleet.
    import json

    path = tmp_path / "tiny.json"
    path.write_text(
        json.dumps(
            {
                "days": 1,
                "resolution": "5min",
                "fleet": {
                    "contracts": [
                        {
                            "id": "t",
                            "label": "Test",
                            "region_id": "temperate_lowland",
                            "units": 5,
                            "duty_bias": 0.0,
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return str(path)


def test_cli_validate_writes_report(tmp_path, capsys) -> None:
    report = tmp_path / "report.md"
    rc = main(["validate", "--config", _tiny_config_file(tmp_path), "--seed", "7", "--report", str(report)])
    assert rc == 0  # offline checks pass
    assert report.exists()
    text = report.read_text(encoding="utf-8")
    assert "Distribution validation report" in text
    assert "seed `7`" in text


def test_cli_validate_to_stdout(tmp_path, capsys) -> None:
    rc = main(["validate", "--config", _tiny_config_file(tmp_path), "--seed", "7"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Distribution validation report" in out
