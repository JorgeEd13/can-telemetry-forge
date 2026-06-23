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
