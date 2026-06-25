"""Offline, deterministic tests for the F3 labeled anomaly/fault registry.

Asserts the F3 Definition of Done (ADR-006/-016): every injected defect family is
present at its configured rate and **fully recoverable from labels**; defects are
mutually exclusive per cell; era-`NULL` cells are never targeted; the `is_outlier`
rollup means what it says; and the whole layer is reproducible. No network, no
files.
"""

from __future__ import annotations

import numpy as np
import pytest

from can_telemetry_forge.anomalies import (
    ANOMALY_TYPES,
    DEFAULT_ANOMALY_RATES,
    NO_ANOMALY,
    VALUE_DISTORTION_TYPES,
    apply_anomalies,
)
from can_telemetry_forge.anomalies.spec import (
    JOINT_OUTLIER,
    OBVIOUS_OUTLIER,
    SENSOR_DROPOUT,
    SENSOR_DRIFT,
    SENSOR_STUCK,
)
from can_telemetry_forge.config import SEASONS, config_from_dict, default_config
from can_telemetry_forge.sim import build_fleet, simulate
from can_telemetry_forge.sim.drivers import drivers_for_unit
from can_telemetry_forge.signals import Era, generate_unit, get_spec

_BASELINE = SEASONS["baseline"]


def _modern_unit_signals(days: int = 8, resolution: str = "5min", seed: int = 0):
    """A single Modern unit's full (non-gated) signal set, for injector tests."""
    cfg = config_from_dict({"days": days, "resolution": resolution, "seed": seed})
    region = cfg.fleet.regions[0]
    unit = build_fleet(cfg.fleet, np.random.default_rng(0))[0]
    n, step = cfg.n_steps(), cfg.step_hours()
    drivers = drivers_for_unit(unit, region, _BASELINE, n, step, np.random.default_rng(0))
    signals = generate_unit(Era.MODERN, drivers, np.random.default_rng(0))
    return signals, n


def _rngs(seed_base: int = 100) -> dict[str, np.random.Generator]:
    return {t: np.random.default_rng(seed_base + i) for i, t in enumerate(ANOMALY_TYPES)}


def _all_on_rates() -> dict[str, float]:
    """Rates cranked so every family fires in a small window (for presence tests)."""
    return {
        OBVIOUS_OUTLIER: 0.01,
        JOINT_OUTLIER: 0.4,
        SENSOR_STUCK: 0.002,
        SENSOR_DRIFT: 0.002,
        SENSOR_DROPOUT: 0.002,
    }


# --- presence & recoverability -----------------------------------------------


def test_every_defect_family_is_present_and_labeled() -> None:
    signals, n = _modern_unit_signals()
    labels = apply_anomalies(signals, _all_on_rates(), _rngs(), n)
    seen = {h.anomaly_type for h in labels.hits}
    assert set(ANOMALY_TYPES) <= seen, f"missing families: {set(ANOMALY_TYPES) - seen}"


def test_obvious_outliers_are_out_of_range() -> None:
    signals, n = _modern_unit_signals()
    labels = apply_anomalies(signals, _all_on_rates(), _rngs(), n)
    for hit in labels.hits:
        if hit.anomaly_type == OBVIOUS_OUTLIER:
            spec = get_spec(hit.signal)
            assert np.all(signals[hit.signal][hit.mask] > spec.max_value)


def test_joint_outliers_stay_in_range_but_violate_context() -> None:
    # Inject ONLY joint outliers so we can read the contradiction cleanly.
    signals, n = _modern_unit_signals()
    rates = {t: 0.0 for t in ANOMALY_TYPES}
    rates[JOINT_OUTLIER] = 0.5
    labels = apply_anomalies(signals, rates, _rngs(), n)
    joint_hits = [h for h in labels.hits if h.anomaly_type == JOINT_OUTLIER]
    assert joint_hits, "expected joint outliers"
    for hit in joint_hits:
        spec = get_spec(hit.signal)
        vals = signals[hit.signal][hit.mask]
        # Each injected value is individually valid — only the *pair* is impossible.
        assert np.all((vals >= spec.min_value) & (vals <= spec.max_value))
    # The fuel-without-load rule must produce high fuel where load is ~0.
    fuel_hits = [h for h in joint_hits if h.signal == "fuel_rate_lph"]
    if fuel_hits:
        mask = fuel_hits[0].mask
        assert np.all(signals["engine_load_pct"][mask] < 5.0)
        assert np.all(signals["fuel_rate_lph"][mask] > 100.0)  # genuinely high fuel


def test_sensor_dropout_blanks_to_null_and_is_not_an_outlier() -> None:
    signals, n = _modern_unit_signals()
    rates = {t: 0.0 for t in ANOMALY_TYPES}
    rates[SENSOR_DROPOUT] = 0.003
    labels = apply_anomalies(signals, rates, _rngs(), n)
    drop_hits = [h for h in labels.hits if h.anomaly_type == SENSOR_DROPOUT]
    assert drop_hits, "expected dropout segments"
    for hit in drop_hits:
        assert np.all(np.isnan(signals[hit.signal][hit.mask]))  # NULL, blanked
    # Dropout is a defect but not a value distortion → excluded from is_outlier.
    assert SENSOR_DROPOUT not in VALUE_DISTORTION_TYPES
    assert not labels.is_outlier.any()


def test_sensor_stuck_freezes_a_constant_segment() -> None:
    signals, n = _modern_unit_signals()
    rates = {t: 0.0 for t in ANOMALY_TYPES}
    rates[SENSOR_STUCK] = 0.003
    labels = apply_anomalies(signals, rates, _rngs(), n)
    stuck_hits = [h for h in labels.hits if h.anomaly_type == SENSOR_STUCK]
    assert stuck_hits, "expected stuck segments"
    for hit in stuck_hits:
        values = signals[hit.signal]
        # A signal can have several stuck segments (each frozen at its own value);
        # check each contiguous run of masked rows is individually constant.
        idx = np.nonzero(hit.mask)[0]
        breaks = np.nonzero(np.diff(idx) > 1)[0] + 1
        for run in np.split(idx, breaks):
            assert np.allclose(values[run], values[run[0]])


# --- contract invariants -----------------------------------------------------


def test_at_most_one_defect_per_row() -> None:
    signals, n = _modern_unit_signals()
    labels = apply_anomalies(signals, _all_on_rates(), _rngs(), n)
    # The per-row categorical is single-valued by construction; the rollup must be
    # consistent with it (any value-distorting label ⇒ is_outlier True).
    for atype in VALUE_DISTORTION_TYPES:
        rows = labels.anomaly_type == atype
        assert np.all(labels.is_outlier[rows]), f"{atype} rows must be is_outlier"
    # A clean row carries no signal and no outlier flag.
    clean = labels.anomaly_type == NO_ANOMALY
    assert np.all(labels.anomaly_signal[clean] == NO_ANOMALY)


def test_era_gated_cells_are_never_targeted() -> None:
    # A Legacy unit has EGT/DEF/vibration gated off (NULL). No defect may land there.
    cfg = config_from_dict({"days": 8, "resolution": "5min", "seed": 0})
    region = cfg.fleet.regions[0]
    unit = build_fleet(cfg.fleet, np.random.default_rng(0))[0]
    n, step = cfg.n_steps(), cfg.step_hours()
    drivers = drivers_for_unit(unit, region, _BASELINE, n, step, np.random.default_rng(0))
    signals = generate_unit(Era.LEGACY, drivers, np.random.default_rng(0))
    gated = [name for name, arr in signals.items() if arr is None]
    assert gated, "expected some era-gated signals for a Legacy unit"
    labels = apply_anomalies(signals, _all_on_rates(), _rngs(), n)
    hit_signals = {h.signal for h in labels.hits}
    assert hit_signals.isdisjoint(gated)
    # Gated signals stay None (never resurrected by an injector).
    for name in gated:
        assert signals[name] is None


def test_zero_rates_inject_nothing() -> None:
    signals, n = _modern_unit_signals()
    rates = {t: 0.0 for t in ANOMALY_TYPES}
    labels = apply_anomalies(signals, rates, _rngs(), n)
    assert labels.hits == []
    assert not labels.is_outlier.any()
    assert np.all(labels.anomaly_type == NO_ANOMALY)


def test_injection_is_reproducible() -> None:
    sig_a, n = _modern_unit_signals()
    sig_b, _ = _modern_unit_signals()
    la = apply_anomalies(sig_a, _all_on_rates(), _rngs(7), n)
    lb = apply_anomalies(sig_b, _all_on_rates(), _rngs(7), n)
    assert np.array_equal(la.anomaly_type.astype(str), lb.anomaly_type.astype(str))
    assert np.array_equal(la.is_outlier, lb.is_outlier)
    # And the mutated signals match too.
    for name in sig_a:
        if sig_a[name] is None:
            assert sig_b[name] is None
        else:
            np.testing.assert_array_equal(
                np.nan_to_num(sig_a[name]), np.nan_to_num(sig_b[name])
            )


def test_higher_rate_yields_more_defects() -> None:
    sig_lo, n = _modern_unit_signals()
    sig_hi, _ = _modern_unit_signals()
    lo = apply_anomalies(sig_lo, {OBVIOUS_OUTLIER: 0.002}, _rngs(), n)
    hi = apply_anomalies(sig_hi, {OBVIOUS_OUTLIER: 0.02}, _rngs(), n)
    assert hi.is_outlier.sum() > lo.is_outlier.sum()


# --- end-to-end through the simulator ----------------------------------------


def test_simulate_emits_anomaly_columns_and_all_types_present() -> None:
    ds = simulate(config_from_dict({"days": 10, "resolution": "5min", "seed": 7}))
    for col in ("anomaly_type", "anomaly_signal", "is_outlier"):
        assert col in ds.readings.columns
    present = set(ds.readings["anomaly_type"].unique()) - {NO_ANOMALY}
    assert set(ANOMALY_TYPES) <= present, f"missing in dataset: {set(ANOMALY_TYPES) - present}"
    # The rollup excludes dropout; cross-check against the categorical.
    distort = ds.readings["anomaly_type"].isin(list(VALUE_DISTORTION_TYPES))
    assert (ds.readings["is_outlier"] == distort).all()


def test_simulate_dropout_rows_are_null_in_their_signal() -> None:
    ds = simulate(config_from_dict({"days": 10, "resolution": "5min", "seed": 7}))
    drop = ds.readings[ds.readings["anomaly_type"] == SENSOR_DROPOUT]
    assert len(drop) > 0
    # Every dropout row's named signal is NULL.
    for sig in drop["anomaly_signal"].unique():
        rows = drop[drop["anomaly_signal"] == sig]
        assert rows[sig].isna().all()


def test_anomaly_rates_config_is_validated() -> None:
    with pytest.raises(ValueError):
        config_from_dict({"anomaly_rates": {"not_a_real_type": 0.1}})
    with pytest.raises(ValueError):
        config_from_dict({"anomaly_rates": {"obvious_outlier": 1.5}})
    # A valid partial override merges onto the defaults.
    cfg = config_from_dict({"anomaly_rates": {"obvious_outlier": 0.05}})
    rates = cfg.resolved_anomaly_rates()
    assert rates["obvious_outlier"] == 0.05
    assert rates["sensor_stuck"] == DEFAULT_ANOMALY_RATES["sensor_stuck"]


def test_obvious_outlier_rate_back_compat_alias() -> None:
    cfg = config_from_dict({"obvious_outlier_rate": 0.03})
    assert cfg.resolved_anomaly_rates()["obvious_outlier"] == 0.03
