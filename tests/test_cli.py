"""Offline, deterministic tests for the F0 skeleton.

These exercise the CLI surface and the version plumbing only — no generation
exists yet. They must run with no network and no downloaded data.
"""

from __future__ import annotations

import re

import pytest

import can_telemetry_forge
from can_telemetry_forge.cli import build_parser, main


def test_version_is_pep440_string() -> None:
    version = can_telemetry_forge.__version__
    assert isinstance(version, str)
    # Loose PEP 440 / semver-ish shape: at least major.minor.patch.
    assert re.match(r"^\d+\.\d+\.\d+", version), version


def test_version_flag_prints_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert can_telemetry_forge.__version__ in out
    assert out.startswith("forge ")


def test_no_command_prints_help_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = main([])
    assert rc == 0
    out = capsys.readouterr().out
    assert "usage:" in out.lower()


def test_help_flag_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out.lower()


def test_validate_runs_offline_and_passes(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    # `forge validate` (F4) runs the offline adapters with no network and exits 0
    # when the generated run is in-spec. (Network/VED checks are opt-in, not here.)
    # A tiny config keeps it off the 90-day default fleet.
    import json

    cfg = tmp_path / "tiny.json"
    cfg.write_text(
        json.dumps(
            {
                "days": 1,
                "resolution": "5min",
                "fleet": {
                    "contracts": [
                        {"id": "t", "label": "T", "region_id": "temperate_lowland", "units": 4, "duty_bias": 0.0}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    rc = main(["validate", "--config", str(cfg), "--seed", "7"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Distribution validation report" in out


def test_generate_requires_out() -> None:
    # `--out` is required now that generate actually writes files.
    with pytest.raises(SystemExit):
        build_parser().parse_args(["generate"])


def test_generate_defaults_parse() -> None:
    args = build_parser().parse_args(["generate", "--out", "x"])
    assert args.command == "generate"
    assert args.seed is None  # falls back to the config seed when unset
    assert args.format == "parquet"
