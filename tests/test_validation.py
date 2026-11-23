"""Offline, deterministic tests for the F4 validation layer.

These never hit the network. They exercise the offline adapters (`in_spec`,
`golden`), the pure comparison math, the report renderer, and the `forge validate`
CLI path. The `ved` adapter is only tested via its *graceful-unavailable* path
(empty cache + no Kaggle) — its network fetch is opt-in and out of CI by design.
"""

from __future__ import annotations

import numpy as np
import pytest
from validation import compare_distributions, render_report, run_validation
from validation.compare import histogram_overlap, summarise_signal
from validation.reference import (
    OFFLINE_ADAPTERS,
    REFERENCE_ADAPTERS,
)
from validation.reference import (
    run_validation as run_validation_direct,
)

from can_telemetry_forge.cli import main
from can_telemetry_forge.config import config_from_dict
from can_telemetry_forge.signals import get_spec, signal_names


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


def test_histogram_overlap_empty_side_cannot_compare() -> None:
    # R4-T10-b: "cannot compare" is None, the same as in summarise_signal (was 0.0).
    assert histogram_overlap(np.array([]), np.array([1.0, 2.0])) is None
    assert histogram_overlap(np.array([1.0, 2.0]), np.array([np.nan])) is None


def test_histogram_overlap_identical_constants_is_one() -> None:
    # R4-T10-b: two identical constants used to score 0.0 (degenerate range).
    assert histogram_overlap(np.full(100, 3.0), np.full(50, 3.0)) == pytest.approx(1.0)
    assert histogram_overlap(np.full(100, 3.0), np.full(50, 4.0)) == 0.0


def test_histogram_overlap_single_outlier_does_not_collapse_the_grid() -> None:
    # R4-T10-b measurement: N(0,1) vs N(1,1) = 0.610; adding one value of 1,000 used
    # to stretch the grid into one bin and score 1.000.
    rng = np.random.default_rng(0)
    a = rng.normal(0.0, 1.0, 5000)
    b = rng.normal(1.0, 1.0, 5000)
    base = histogram_overlap(a, b)
    assert base == pytest.approx(0.61, abs=0.05)
    for extreme in (1e3, -1e3, 1e9):
        assert histogram_overlap(np.append(a, extreme), b) == pytest.approx(base, abs=0.01)
        assert histogram_overlap(a, np.append(b, extreme)) == pytest.approx(base, abs=0.01)


@pytest.mark.parametrize(("n", "k"), [(1000, 5), (200, 1), (10000, 50)])
def test_histogram_overlap_tolerates_outliers_up_to_half_a_percent(n, k) -> None:
    # Exactly 0.5% extreme values on either side, at either end, must not stretch the
    # grid (an interpolated percentile did: 0.011 -> 0.995 at 5/1000).
    rng = np.random.default_rng(0)
    a = rng.normal(0.0, 1.0, n)
    b = rng.normal(5.0, 1.0, n)
    base = histogram_overlap(a, b)
    assert base < 0.05
    for extreme in (1e9, -1e9, 1e12):
        assert histogram_overlap(a, np.r_[b[: n - k], np.full(k, extreme)]) < base + 0.01
        assert histogram_overlap(np.r_[a[: n - k], np.full(k, extreme)], b) < base + 0.01


def test_histogram_overlap_huge_finite_values_do_not_crash() -> None:
    # hi - lo overflowed to inf and gave NaN bin edges (ValueError).
    assert histogram_overlap(np.full(10, -1e308), np.full(10, 1e308)) == 0.0
    x = np.linspace(-1.0, 1.0, 100) * 1e308
    assert histogram_overlap(x, x) == pytest.approx(1.0)
    # Shared 10% cluster at -1e308, the rest disjoint: the data must be rescaled too.
    g = np.r_[np.full(10, -1e308), np.full(90, 0.15e308)]
    r = np.r_[np.full(10, -1e308), np.full(90, 0.85e308)]
    assert histogram_overlap(g, r) == pytest.approx(0.1)


def test_summarise_overlap_is_none_when_the_reference_has_no_values() -> None:
    cmp = summarise_signal("x", "u", np.arange(10, dtype=float), np.full(5, np.nan))
    assert cmp.overlap is None and cmp.ref_n == 0


def test_report_table_shows_the_overlap_score() -> None:
    from validation.compare import SignalComparison
    from validation.report import _comparison_table

    row = SignalComparison("x", "u", 3, 0.0, 2.0, 1.0, 0.8, 0.1, 1.0, 1.9, overlap=0.5, ref_n=3)
    assert _comparison_table([row])[-1].endswith("| 0.500 |")


def test_histogram_overlap_disjoint_with_an_outlier_stays_near_zero() -> None:
    # R4-V2-h measurement: this pair scored 0.9990 (1000/1001); without 1e6, 0.0.
    rng = np.random.default_rng(0)
    ref = np.append(rng.normal(1500.0, 300.0, 1000), 1e6)
    assert histogram_overlap(np.zeros(1000), ref) < 0.01


def test_summarise_percentiles_are_in_order() -> None:
    # R4-V2-h: a p50/p95 swap left the suite green.
    cmp = summarise_signal("x", "u", np.arange(101, dtype=float))
    assert (cmp.gen_p05, cmp.gen_p50, cmp.gen_p95) == pytest.approx((5.0, 50.0, 95.0))
    assert (cmp.gen_min, cmp.gen_max, cmp.n) == (0.0, 100.0, 101)


def test_compare_distributions_uses_the_reference_sample() -> None:
    # R4-V2-h: compare_distributions ignoring ref_columns left the suite green.
    x = np.linspace(0.0, 10.0, 500)
    out = compare_distributions(
        {"a": x, "b": x}, {"a": x, "b": x + 100.0}, {"a": "u", "b": "u"}
    )
    by = {c.signal: c for c in out}
    assert by["a"].ref_n == 500 and by["a"].overlap == pytest.approx(1.0)
    assert by["b"].overlap == 0.0


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
    # R4-T10-d: dropping signals from the golden run must not stay green — every
    # Tier-1 signal carries all four pinned stats.
    from validation.reference import GOLDEN_STATS

    assert sorted(c.name for c in golden.checks) == sorted(
        f"{name} golden {stat}" for name in signal_names() for stat in GOLDEN_STATS
    )


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

    def _boom(cache_dir, handle=None):
        raise RuntimeError("forced: no VED in test")

    monkeypatch.setattr(ref, "_load_ved_frame", _boom)
    readings = simulate(small_config()).readings
    result = ref._check_ved(readings, ref._units_map(), cache_dir=tmp_path / "empty")
    assert result.adapter == "ved"
    assert result.available is False
    assert "unavailable" in result.note.lower()


def test_ved_handle_is_configurable(monkeypatch) -> None:
    # Default, env override, and explicit arg precedence for the VED dataset handle.
    import validation.reference as ref

    monkeypatch.delenv("FORGE_VED_HANDLE", raising=False)
    assert ref._resolve_ved_handle(None) == ref.DEFAULT_VED_HANDLE
    assert ref._resolve_ved_handle("owner/slug") == "owner/slug"  # explicit wins
    monkeypatch.setenv("FORGE_VED_HANDLE", "envowner/envslug")
    assert ref._resolve_ved_handle(None) == "envowner/envslug"  # env over default
    assert ref._resolve_ved_handle("owner/slug") == "owner/slug"  # explicit over env


def test_ved_overlap_with_a_fake_local_csv(tmp_path, monkeypatch) -> None:
    # With a cached CSV present, no network is touched (the fetch branch is skipped),
    # and the adapter computes real overlap on the mapped engine channels.
    import pandas as pd
    import validation.reference as ref

    from can_telemetry_forge.sim import simulate

    cache = tmp_path / "ved"
    cache.mkdir()
    # Minimal VED-schema CSV covering the two mapped columns (current VED schema).
    pd.DataFrame(
        {
            "Engine_RPM_RPM": np.linspace(700, 2200, 500),
            "Absolute_Load_pct": np.linspace(5, 95, 500),
        }
    ).to_csv(cache / "trip.csv", index=False)
    # Guard: no network on the cached path — return the fake frame directly.
    monkeypatch.setattr(
        ref, "_load_ved_frame",
        lambda cache_dir, handle=None: pd.read_csv(sorted(cache_dir.glob("*.csv"))[0]),
    )
    readings = simulate(small_config()).readings
    result = ref._check_ved(readings, ref._units_map(), cache_dir=cache)
    assert result.available is True
    assert result.comparisons  # at least the two mapped channels compared
    assert any(c.overlap is not None for c in result.comparisons)


def test_run_validation_unknown_dataset_is_an_error() -> None:
    # R4-V2-a: an unknown name used to be a stderr warning followed by PASS.
    with pytest.raises(ValueError, match="unknown dataset 'nope'"):
        run_validation_direct(small_config(), datasets=("nope",))


# --- report -------------------------------------------------------------------


def test_report_is_self_contained_markdown() -> None:
    run = run_validation(small_config())
    md = render_report(run)
    assert md.startswith("# Distribution validation report")
    assert "Provenance" in md
    assert "Not real telemetry" in md
    assert "CC-BY 4.0" in md
    # R4-T10-d / R4-V2-h: this loop used to assert nothing, and a report without
    # distribution tables stayed green. Every signal gets a row in a table.
    assert "**Distributions**" in md
    assert "| Signal | Unit | n | min | p05 | p50 | mean | p95 | max | overlap |" in md
    for name in signal_names():
        assert f"| `{name}` |" in md, name
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


# --- golden is a real drift guard (R4-T10-a) ----------------------------------


def test_golden_fails_on_a_shifted_generator(monkeypatch) -> None:
    # The mutation that used to pass: +40 degC on coolant. The mean stays inside the
    # J1939 range, so only a comparison against pinned values can catch it.
    from validation import reference

    real_simulate = reference.simulate

    def shifted(config):
        ds = real_simulate(config)
        ds.readings["coolant_temp_c"] = ds.readings["coolant_temp_c"] + 40.0
        return ds

    reference._golden_drift_result.cache_clear()
    monkeypatch.setattr(reference, "simulate", shifted)
    try:
        checks, _ = reference._golden_drift_result()
    finally:
        reference._golden_drift_result.cache_clear()
    failed = {c.name for c in checks if not c.passed}
    assert "coolant_temp_c golden mean" in failed
    assert not any(n.startswith("engine_speed_rpm") for n in failed)


@pytest.mark.parametrize("stat", ["mean", "std", "p05", "p95"])
def test_compare_to_pins_catches_each_stat_and_missing_signals(stat) -> None:
    from validation.golden_pins import GOLDEN_PINS
    from validation.reference import compare_to_pins

    assert all(c.passed for c in compare_to_pins(GOLDEN_PINS, GOLDEN_PINS))
    moved = {k: dict(v) for k, v in GOLDEN_PINS.items()}
    moved["oil_pressure_kpa"][stat] += 1.0  # 1 kPa = 10x the tolerance on a 1000 kPa span
    assert [c.name for c in compare_to_pins(moved, GOLDEN_PINS) if not c.passed] == [
        f"oil_pressure_kpa golden {stat}"
    ]
    dropped = {k: v for k, v in GOLDEN_PINS.items() if k != "def_level_pct"}
    assert not all(c.passed for c in compare_to_pins(dropped, GOLDEN_PINS))


def test_golden_tolerance_boundary_is_1e4_of_the_span() -> None:
    from validation.golden_pins import GOLDEN_PINS
    from validation.reference import compare_to_pins

    tol = 1e-4 * 250.0  # coolant span: -40..210 degC
    for shift, ok in ((0.9 * tol, True), (1.1 * tol, False)):
        moved = {k: dict(v) for k, v in GOLDEN_PINS.items()}
        moved["coolant_temp_c"]["mean"] += shift
        mean_check = next(
            c for c in compare_to_pins(moved, GOLDEN_PINS) if c.name == "coolant_temp_c golden mean"
        )
        assert mean_check.passed is ok, shift


# --- no PASS without a comparison (P1-01: R4-T10-c, R4-T11-b, R4-V2-a, R4-V2-b) ---


def _ved_fails(monkeypatch) -> None:
    import validation.reference as ref

    def _boom(cache_dir, handle=None):
        raise RuntimeError("forced: no VED in test")

    monkeypatch.setattr(ref, "_load_ved_frame", _boom)


def test_requested_but_unavailable_ved_is_not_a_pass(monkeypatch) -> None:
    _ved_fails(monkeypatch)
    run = run_validation(small_config(), datasets=("ved",))
    ved = next(r for r in run.results if r.adapter == "ved")
    assert ved.available is False
    assert not run.passed
    md = render_report(run, datasets=("ved",))
    assert "all checks passed" not in md
    assert "`ved`" in md.split("## Adapters")[0]  # the summary names what did not run


def test_cli_requested_but_unavailable_ved_exits_non_zero(tmp_path, monkeypatch, capsys) -> None:
    _ved_fails(monkeypatch)
    rc = main(["validate", "--config", _tiny_config_file(tmp_path), "--dataset", "ved"])
    assert rc != 0
    assert "FAIL" in capsys.readouterr().err


def test_cli_unknown_dataset_is_a_usage_error(tmp_path, capsys) -> None:
    rc = main(["validate", "--config", _tiny_config_file(tmp_path), "--dataset", "nosuch"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "nosuch" in err and "PASS" not in err


def test_ved_mirror_without_mapped_columns_is_unavailable(tmp_path) -> None:
    # R4-T11-b: a real cached zip whose CSV has none of the mapped columns used to read
    # every column, compare nothing, and report `ved` available with zero checks.
    import zipfile

    import validation.reference as ref

    from can_telemetry_forge.sim import simulate

    cache = tmp_path / "ved"
    cache.mkdir()
    with zipfile.ZipFile(cache / "owner__slug.zip", "w") as z:
        z.writestr("combustion_master.csv", "RPM,Load,X\n800,10,1\n1500,50,2\n")
    readings = simulate(small_config()).readings
    result = ref._check_ved(readings, ref._units_map(), cache_dir=cache, handle="owner/slug")
    assert result.available is False
    assert "Engine_RPM_RPM" in result.note
    assert not result.passed


def test_adapter_with_zero_checks_is_not_a_pass() -> None:
    from validation.reference import ReferenceResult, ValidationRun

    empty = ReferenceResult(adapter="x", description="d", available=True)
    assert not empty.passed
    assert not ValidationRun(config=small_config(), results=[empty]).passed


def test_in_spec_with_every_row_flagged_is_not_a_pass() -> None:
    from validation.reference import _check_in_spec, _units_map

    from can_telemetry_forge.sim import simulate

    readings = simulate(small_config()).readings.copy()
    readings["is_outlier"] = True
    assert not _check_in_spec(readings, _units_map()).passed


def test_expected_signal_with_no_values_fails_validation(monkeypatch) -> None:
    # R4-V2-b: a signal the run's eras should report, NULL everywhere, used to drop
    # its check silently and leave the run passing.
    from validation import reference

    real_simulate = reference.simulate

    def nulled(config):
        ds = real_simulate(config)
        ds.readings["engine_speed_rpm"] = np.nan
        return ds

    reference._golden_drift_result.cache_clear()
    monkeypatch.setattr(reference, "simulate", nulled)
    try:
        run = run_validation(small_config())
    finally:
        reference._golden_drift_result.cache_clear()
    by = {r.adapter: r for r in run.results}
    assert [c.name for c in by["in_spec"].checks if not c.passed] == [
        "engine_speed_rpm has values"
    ]
    assert not by["golden"].passed
    assert not run.passed


def _dropping(monkeypatch, mutate) -> object:
    """Run validation on the small config with ``mutate`` applied to the user's readings."""
    from validation import reference

    real_simulate = reference.simulate

    def patched(config):
        ds = real_simulate(config)
        if config.seed == 7:  # the user run only; the golden profile stays untouched
            mutate(ds)
        return ds

    monkeypatch.setattr(reference, "simulate", patched)
    return run_validation(small_config())


def test_expected_signal_missing_column_fails_validation(monkeypatch) -> None:
    run = _dropping(monkeypatch, lambda ds: ds.readings.drop(columns="equipment_age_days", inplace=True))
    in_spec = next(r for r in run.results if r.adapter == "in_spec")
    assert "equipment_age_days has values" in [c.name for c in in_spec.checks if not c.passed]
    assert not run.passed


def test_expected_signal_null_for_one_era_fails_validation(monkeypatch) -> None:
    from can_telemetry_forge.signals import Era, supported_signal_names
    from can_telemetry_forge.sim import simulate

    units = simulate(small_config()).units
    eras = set(units["era"].astype(str))
    assert len(eras) > 1, eras  # the test needs an era to hide behind another
    era = min(eras, key=lambda e: Era[e].value)
    signal = supported_signal_names(Era[era])[0]
    ids = set(units.loc[units["era"].astype(str) == era, "unit_id"])

    def null_one_era(ds):
        ds.readings.loc[ds.readings["unit_id"].isin(ids), signal] = np.nan

    run = _dropping(monkeypatch, null_one_era)
    in_spec = next(r for r in run.results if r.adapter == "in_spec")
    assert f"{signal} has values" in [c.name for c in in_spec.checks if not c.passed]
    assert not run.passed


def test_empty_validation_run_is_not_a_pass() -> None:
    from validation.reference import ValidationRun

    assert not ValidationRun(config=small_config(), results=[]).passed


def test_ved_frame_without_mapped_columns_is_unavailable(monkeypatch) -> None:
    import pandas as pd
    import validation.reference as ref

    from can_telemetry_forge.sim import simulate

    monkeypatch.setattr(
        ref, "_load_ved_frame", lambda cache_dir, handle=None: pd.DataFrame({"RPM": [800.0]})
    )
    result = ref._check_ved(simulate(small_config()).readings, ref._units_map())
    assert result.available is False and not result.passed
    assert "Engine_RPM_RPM" in result.note


def test_ved_zero_overlap_is_a_failing_check(monkeypatch) -> None:
    import pandas as pd
    import validation.reference as ref

    from can_telemetry_forge.sim import simulate

    far = pd.DataFrame({"Engine_RPM_RPM": np.full(500, 1e7), "Absolute_Load_pct": np.full(500, 1e7)})
    monkeypatch.setattr(ref, "_load_ved_frame", lambda cache_dir, handle=None: far)
    result = ref._check_ved(simulate(small_config()).readings, ref._units_map())
    assert result.checks and not result.passed


def test_ved_compares_only_clean_rows(monkeypatch) -> None:
    # R4-V2-c: the ved path compared injected-defect rows that in_spec excludes.
    import pandas as pd
    import validation.reference as ref

    from can_telemetry_forge.sim import simulate

    readings = simulate(small_config()).readings.copy()
    clean = ~readings["is_outlier"].to_numpy().astype(bool)
    readings.loc[readings.index[:3], "engine_speed_rpm"] = 1e6
    readings.loc[readings.index[:3], "is_outlier"] = True
    clean[:3] = False
    ved = pd.DataFrame(
        {"Engine_RPM_RPM": np.linspace(700, 2200, 500), "Absolute_Load_pct": np.linspace(5, 95, 500)}
    )
    monkeypatch.setattr(ref, "_load_ved_frame", lambda cache_dir, handle=None: ved)
    result = ref._check_ved(readings, ref._units_map())
    rpm = next(c for c in result.comparisons if c.signal == "engine_speed_rpm")
    want = readings["engine_speed_rpm"].to_numpy(dtype=float)[clean]
    want = want[np.isfinite(want)]
    assert rpm.n == want.size
    assert rpm.gen_max == want.max() < 1e6


def test_report_overall_glyph_is_fail_when_a_reference_did_not_run(monkeypatch) -> None:
    _ved_fails(monkeypatch)
    md = render_report(run_validation(small_config(), datasets=("ved",)), datasets=("ved",))
    overall = next(line for line in md.splitlines() if line.startswith("- **Overall:**"))
    assert "❌" in overall and "✅" not in overall
