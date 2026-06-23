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


@pytest.mark.parametrize(
    ("command", "phase"),
    [("generate", "F2"), ("validate", "F4")],
)
def test_unimplemented_subcommands_fail_honestly(
    command: str,
    phase: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc:
        main([command])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "not implemented" in err.lower()
    assert phase in err


def test_generate_defaults_parse() -> None:
    args = build_parser().parse_args(["generate"])
    assert args.command == "generate"
    assert args.seed == 42
