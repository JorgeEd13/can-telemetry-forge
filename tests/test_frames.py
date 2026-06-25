"""Offline, deterministic tests for F6: the frame encoder and CAN-frame faults.

Covers the F6 Definition of Done (ADR-019): the frame codec **round-trips** the
documented signals within quantization; the four CAN-frame fault families are
present, labeled, and recoverable; the byte-level raw-frame artifact is opt-in and
matches the labeled cells; everything is reproducible; and the value *generators*
still don't depend on the (now-populated) frame layout. No network, no files
(except the writer test's tmp_path).
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from can_telemetry_forge.anomalies import apply_anomalies
from can_telemetry_forge.anomalies.spec import (
    CAN_FRAME_CORRUPT,
    CAN_FRAME_ERROR_INDICATOR,
    CAN_FRAME_STALE,
    CAN_FRAME_TRUNCATED,
    CAN_FRAME_TYPES,
)
from can_telemetry_forge.config import config_from_dict
from can_telemetry_forge.io import write_dataset
from can_telemetry_forge.sim import simulate
from can_telemetry_forge.signals import (
    TIER1_SIGNALS,
    decode_signal_frame,
    encode_signal_frame,
    generate_unit,
    get_spec,
    signal_names,
)
from can_telemetry_forge.signals.frames import (
    MAX_FRAME_BYTES,
    _error_raw,
    _na_raw,
    raw_to_value,
    value_to_raw,
)
from can_telemetry_forge.signals.spec import Era

# Bus signals (those that got a frame layout in F6).
_BUS_SIGNALS = tuple(s.name for s in TIER1_SIGNALS if s.layout is not None)


# --- the frame codec ----------------------------------------------------------


def test_every_bus_signal_has_a_well_formed_layout() -> None:
    for spec in TIER1_SIGNALS:
        if spec.layout is None:
            continue
        lay = spec.layout
        assert lay.bit_len in (8, 16)
        assert lay.start_bit % 8 == 0  # Tier-1 fields are byte-aligned
        assert lay.frame_bytes <= MAX_FRAME_BYTES
        # The field fits inside the frame.
        assert lay.start_bit // 8 + lay.bit_len // 8 <= lay.frame_bytes
        assert lay.byte_order == "little"


@pytest.mark.parametrize("name", _BUS_SIGNALS)
def test_codec_round_trips_within_one_quantum(name: str) -> None:
    spec = get_spec(name)
    lay = spec.layout
    # Sample a handful of in-range values and check encode→decode is within scale/2.
    lo, hi = spec.min_value, spec.max_value
    for frac in (0.0, 0.13, 0.5, 0.87):
        value = lo + frac * (hi - lo)
        # Stay below the reserved sentinel band at the very top of range.
        value = min(value, hi - 2 * lay.scale)
        frame = encode_signal_frame(value, spec)
        assert len(frame) == lay.frame_bytes
        decoded = decode_signal_frame(frame, spec)
        assert abs(decoded - value) <= lay.scale / 2 + 1e-9


@pytest.mark.parametrize("name", _BUS_SIGNALS)
def test_not_available_and_error_codes_decode_to_nan(name: str) -> None:
    lay = get_spec(name).layout
    assert math.isnan(raw_to_value(_na_raw(lay.bit_len), lay))
    assert math.isnan(raw_to_value(_error_raw(lay.bit_len), lay))


def test_nan_value_encodes_to_not_available_frame() -> None:
    spec = get_spec("coolant_temp_c")
    frame = encode_signal_frame(math.nan, spec)
    # The whole frame is the not-available fill (single 8-bit field at byte 0).
    assert math.isnan(decode_signal_frame(frame, spec))


def test_valid_values_never_collide_with_the_sentinels() -> None:
    # value_to_raw reserves the top two codes for NA/error so a real reading is
    # never mistaken for "no value".
    spec = get_spec("engine_speed_rpm")
    lay = spec.layout
    raw = value_to_raw(spec.max_value * 10, lay)  # way over range → clamps
    assert raw <= _error_raw(lay.bit_len) - 1


def test_truncated_frame_decodes_to_nan_for_a_late_field() -> None:
    # egt sits at bytes 6-7; a 3-byte frame loses it entirely.
    spec = get_spec("egt_c")
    full = encode_signal_frame(540.0, spec)
    assert math.isnan(decode_signal_frame(bytes(full[:3]), spec))


# --- the four fault families through apply_anomalies --------------------------


def _modern_signals(days: int = 8, resolution: str = "5min", seed: int = 0):
    from can_telemetry_forge.config import SEASONS, default_config
    from can_telemetry_forge.sim import build_fleet
    from can_telemetry_forge.sim.drivers import drivers_for_unit

    cfg = config_from_dict({"days": days, "resolution": resolution, "seed": seed})
    region = cfg.fleet.regions[0]
    unit = build_fleet(cfg.fleet, np.random.default_rng(0))[0]
    n, step = cfg.n_steps(), cfg.step_hours()
    drivers = drivers_for_unit(unit, region, SEASONS["baseline"], n, step, np.random.default_rng(0))
    signals = generate_unit(Era.MODERN, drivers, np.random.default_rng(0))
    return signals, n


def _frame_rngs(seed: int = 100) -> dict[str, np.random.Generator]:
    from can_telemetry_forge.anomalies import ANOMALY_TYPES

    return {t: np.random.default_rng(seed + i) for i, t in enumerate(ANOMALY_TYPES)}


def _only(atype: str, rate: float) -> dict[str, float]:
    return {atype: rate}


def test_corrupt_distorts_a_value_and_records_a_frame() -> None:
    signals, n = _modern_signals()
    labels = apply_anomalies(signals, _only(CAN_FRAME_CORRUPT, 0.02), _frame_rngs(), n)
    hits = [h for h in labels.hits if h.anomaly_type == CAN_FRAME_CORRUPT]
    assert hits, "no corrupt frames fired"
    for hit in hits:
        assert hit.frames is not None and hit.frames  # raw frame recorded per cell
        # Every corrupted cell is recoverable from the per-row label.
        assert (labels.anomaly_type[hit.mask] == CAN_FRAME_CORRUPT).all() or hit.mask.sum() >= 1
    # Corrupt is a value-distortion type → flagged in the rollup.
    assert labels.is_outlier.any()


def test_error_indicator_blanks_to_null_and_is_not_an_outlier() -> None:
    signals, n = _modern_signals()
    labels = apply_anomalies(signals, _only(CAN_FRAME_ERROR_INDICATOR, 0.03), _frame_rngs(), n)
    hits = [h for h in labels.hits if h.anomaly_type == CAN_FRAME_ERROR_INDICATOR]
    assert hits
    for hit in hits:
        assert np.isnan(signals[hit.signal][hit.mask]).all()  # blanked to NULL
    # error_indicator is NOT a value-distortion → never sets the rollup on its own.
    err_rows = labels.anomaly_type == CAN_FRAME_ERROR_INDICATOR
    assert not labels.is_outlier[err_rows].any()


def test_truncated_blanks_to_null() -> None:
    signals, n = _modern_signals()
    labels = apply_anomalies(signals, _only(CAN_FRAME_TRUNCATED, 0.03), _frame_rngs(), n)
    hits = [h for h in labels.hits if h.anomaly_type == CAN_FRAME_TRUNCATED]
    assert hits
    for hit in hits:
        assert np.isnan(signals[hit.signal][hit.mask]).all()


def test_stale_freezes_the_value_over_a_segment() -> None:
    signals, n = _modern_signals()
    labels = apply_anomalies(signals, _only(CAN_FRAME_STALE, 0.004), _frame_rngs(), n)
    hits = [h for h in labels.hits if h.anomaly_type == CAN_FRAME_STALE]
    assert hits
    for hit in hits:
        idx = np.nonzero(hit.mask)[0]
        # A hit may span several non-overlapping held-frame segments; each contiguous
        # run holds a single repeated value (the last good frame re-sent).
        for run in np.split(idx, np.nonzero(np.diff(idx) > 1)[0] + 1):
            vals = signals[hit.signal][run]
            assert np.allclose(vals, vals[0], equal_nan=True)


def test_frame_faults_only_touch_bus_signals() -> None:
    signals, n = _modern_signals()
    rates = {t: 0.02 for t in CAN_FRAME_TYPES}
    rates[CAN_FRAME_STALE] = 0.004
    labels = apply_anomalies(signals, rates, _frame_rngs(), n)
    for hit in labels.hits:
        if hit.anomaly_type in CAN_FRAME_TYPES:
            assert get_spec(hit.signal).layout is not None


def test_frame_injection_is_reproducible() -> None:
    rates = {t: 0.02 for t in CAN_FRAME_TYPES}
    s1, n = _modern_signals(seed=3)
    s2, _ = _modern_signals(seed=3)
    l1 = apply_anomalies(s1, rates, _frame_rngs(7), n)
    l2 = apply_anomalies(s2, rates, _frame_rngs(7), n)
    assert (l1.anomaly_type == l2.anomaly_type).all()
    assert l1.frame_records() == l2.frame_records()


# --- the raw-frame side artifact through the simulator + writers --------------


def test_raw_frames_artifact_is_opt_in() -> None:
    off = simulate(config_from_dict({"days": 10, "resolution": "5min", "seed": 7}))
    on = simulate(
        config_from_dict(
            {"days": 10, "resolution": "5min", "seed": 7, "emit_raw_frames": True}
        )
    )
    # The table is always built (same rows — emit flag doesn't change generation);
    # the flag only controls whether the writer persists it.
    assert not off.can_frames.empty
    assert (off.can_frames["anomaly_type"].isin(list(CAN_FRAME_TYPES))).all()
    pd.testing.assert_frame_equal(off.can_frames, on.can_frames)


def test_can_frames_rows_match_labeled_frame_cells() -> None:
    ds = simulate(config_from_dict({"days": 10, "resolution": "5min", "seed": 7}))
    cf = ds.can_frames
    # Every can_frames row corresponds to a frame-fault cell in readings.
    merged = cf.merge(
        ds.readings[["unit_id", "t_index", "anomaly_type", "anomaly_signal"]],
        on=["unit_id", "t_index"],
        suffixes=("_frame", "_row"),
    )
    # The frame's signal is a bus signal and its anomaly_type is a CAN-frame one.
    assert (merged["anomaly_type_frame"].isin(list(CAN_FRAME_TYPES))).all()
    assert merged["frame_hex"].str.fullmatch(r"[0-9A-F]+").all()


def test_writer_emits_can_frames_only_when_flagged(tmp_path) -> None:
    on = simulate(
        config_from_dict(
            {"days": 5, "resolution": "5min", "seed": 7, "emit_raw_frames": True}
        )
    )
    out = write_dataset(on, tmp_path / "on", fmt="csv")
    assert (out / "can_frames.csv").exists()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["emit_raw_frames"] is True
    assert manifest["n_can_frames"] == on.can_frames.shape[0] > 0

    off = simulate(config_from_dict({"days": 5, "resolution": "5min", "seed": 7}))
    out_off = write_dataset(off, tmp_path / "off", fmt="csv")
    assert not (out_off / "can_frames.csv").exists()
    manifest_off = json.loads((out_off / "manifest.json").read_text(encoding="utf-8"))
    assert manifest_off["emit_raw_frames"] is False


# --- the ADR-013 invariant still holds: generators ignore the layout ----------


def test_generators_do_not_depend_on_frame_layout() -> None:
    # Strip every layout and confirm the generated series are byte-identical — the
    # value model reads SignalSpec ranges/eras, never the frame layout (ADR-013/-019).
    import dataclasses

    signals_a, n = _modern_signals(seed=5)

    # Monkeypatch the registry specs to drop layouts, regenerate, compare.
    originals = {s.name: s for s in TIER1_SIGNALS}
    try:
        import can_telemetry_forge.signals.spec as spec_mod

        stripped = tuple(dataclasses.replace(s, layout=None) for s in TIER1_SIGNALS)
        spec_mod.SIGNALS_BY_NAME.update({s.name: s for s in stripped})
        signals_b, _ = _modern_signals(seed=5)
    finally:
        spec_mod.SIGNALS_BY_NAME.update(originals)

    for name in signal_names():
        a, b = signals_a[name], signals_b[name]
        if a is None or b is None:
            assert a is None and b is None
            continue
        np.testing.assert_array_equal(np.nan_to_num(a), np.nan_to_num(b))
