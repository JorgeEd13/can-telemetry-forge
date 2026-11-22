"""Offline tests for the F2 writers and the end-to-end CLI generate path."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from can_telemetry_forge.cli import main
from can_telemetry_forge.config import config_from_dict
from can_telemetry_forge.io import FORMATS, write_dataset
from can_telemetry_forge.sim import simulate


def small_config(**over):
    base = {"days": 1, "resolution": "5min", "seed": 7}
    base.update(over)
    return config_from_dict(base)


@pytest.mark.parametrize("fmt", FORMATS)
def test_write_dataset_round_trips(fmt: str, tmp_path) -> None:
    ds = simulate(small_config())
    out = write_dataset(ds, tmp_path / fmt, fmt=fmt)

    # Sidecars are always written.
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    assert "NOT real telemetry" in manifest["provenance"]
    assert manifest["n_readings"] == ds.readings.shape[0]
    assert (out / "dataset_dictionary.md").exists()

    # Read the readings table back and confirm it matches the in-memory row count.
    if fmt == "parquet":
        back = pd.read_parquet(out / "readings.parquet")
    elif fmt == "csv":
        back = pd.read_csv(out / "readings.csv")
    else:
        import duckdb

        con = duckdb.connect(str(out / "dataset.duckdb"))
        back = con.execute("SELECT * FROM readings").df()
        con.close()
    assert back.shape[0] == ds.readings.shape[0]


def test_unknown_format_raises(tmp_path) -> None:
    ds = simulate(small_config())
    with pytest.raises(ValueError):
        write_dataset(ds, tmp_path, fmt="xml")


def test_dictionary_documents_signals_and_labels(tmp_path) -> None:
    ds = simulate(small_config())
    out = write_dataset(ds, tmp_path, fmt="csv")
    text = (out / "dataset_dictionary.md").read_text(encoding="utf-8")
    assert "failure_within_h" in text
    assert "coolant_temp_c" in text
    assert "190" in text  # engine speed SPN present in the generated dictionary


def test_cli_generate_end_to_end(tmp_path, capsys) -> None:
    out_dir = tmp_path / "out"
    rc = main(["generate", "--out", str(out_dir), "--days", "1", "--resolution", "5min", "--seed", "3", "--format", "csv"])
    assert rc == 0
    assert (out_dir / "readings.csv").exists()
    assert (out_dir / "manifest.json").exists()
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == 3
    assert manifest["format"] == "csv"


def test_cli_seed_overrides_config(tmp_path) -> None:
    out_dir = tmp_path / "out"
    main(["generate", "--out", str(out_dir), "--days", "1", "--resolution", "5min", "--seed", "99", "--format", "csv"])
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["seed"] == 99


@pytest.mark.parametrize("fmt", FORMATS)
def test_anomaly_cells_table_is_written(fmt: str, tmp_path) -> None:
    ds = simulate(small_config())
    assert not ds.anomaly_cells.empty
    out = write_dataset(ds, tmp_path / fmt, fmt=fmt)
    if fmt == "duckdb":
        import duckdb

        con = duckdb.connect(str(out / "dataset.duckdb"))
        try:
            n = con.execute("select count(*) from anomaly_cells").fetchone()[0]
        finally:
            con.close()
    else:
        n = len(pd.read_parquet(out / "anomaly_cells.parquet") if fmt == "parquet"
                else pd.read_csv(out / "anomaly_cells.csv"))
    assert n == len(ds.anomaly_cells)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["n_anomaly_cells"] == n
    assert sum(manifest["n_anomaly_cells_by_type"].values()) == n


def test_empty_anomaly_cells_keep_text_columns_in_duckdb(tmp_path) -> None:
    import duckdb

    from can_telemetry_forge.anomalies import DEFAULT_ANOMALY_RATES

    ds = simulate(small_config(anomaly_rates=dict.fromkeys(DEFAULT_ANOMALY_RATES, 0.0)))
    assert ds.anomaly_cells.empty
    out = write_dataset(ds, tmp_path, fmt="duckdb")
    con = duckdb.connect(str(out / "dataset.duckdb"))
    try:
        types = dict(con.execute(
            "select column_name, data_type from information_schema.columns "
            "where table_name = 'anomaly_cells'"
        ).fetchall())
    finally:
        con.close()
    assert types["unit_id"] == types["signal"] == types["anomaly_type"] == "VARCHAR"


def test_validate_finds_the_checkout_package_without_cwd_on_path(tmp_path, monkeypatch) -> None:
    # An installed `forge` script has its bin dir, not the cwd, on sys.path.
    import os
    import sys
    from pathlib import Path

    from can_telemetry_forge.cli import _put_checkout_on_path

    repo = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(repo)
    stripped = [p for p in sys.path if Path(p or os.curdir).resolve() != repo]
    monkeypatch.setattr(sys, "path", stripped)
    _put_checkout_on_path()
    assert sys.path[0] == str(repo)
    monkeypatch.chdir(tmp_path)  # no ./validation here → nothing added
    before = list(sys.path)
    _put_checkout_on_path()
    assert sys.path == before
