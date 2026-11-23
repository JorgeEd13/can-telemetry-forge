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


# --------------------------------------------------------------------------- #
# The validation gate and the exit-code contract (R4-V2-d, R4-T12-e).
#   0 pass · 1 uncaught error (Python's default) · 2 usage · 3 validation package
#   missing · 4 validation FAILED · 5 bad config / input.
# --------------------------------------------------------------------------- #

_GATE_SEED = 4242  # unique to these tests, so the corrupting hook never touches others


def _tiny_config(tmp_path, **extra):
    import json

    cfg = tmp_path / "tiny.json"
    body = {
        "days": 1,
        "resolution": "5min",
        "fleet": {
            "contracts": [
                {"id": "t", "label": "T", "region_id": "temperate_lowland", "units": 4, "duty_bias": 0.0}
            ]
        },
    }
    body.update(extra)
    cfg.write_text(json.dumps(body), encoding="utf-8")
    return cfg


@pytest.fixture(params=[-1.0, float("-inf")], ids=["finite", "neg_inf"])
def below_min_on_clean_row(monkeypatch, request):
    """Make the validated run carry ONE clean (non-defect) value below its J1939 minimum.

    Wraps the real ``simulate`` the validation package calls, and corrupts only the
    run seeded with ``_GATE_SEED`` (the golden reference run is seeded differently
    and cached, so it must stay untouched).
    """
    import validation.reference as ref

    real = ref.simulate

    def corrupting(config):
        ds = real(config)
        if config.seed == _GATE_SEED:
            r = ds.readings
            clean = ~r["is_outlier"].astype(bool)
            if "anomaly_type" in r:
                clean &= r["anomaly_type"].fillna("").astype(str).eq("")
            rows = r.index[clean & r["engine_speed_rpm"].notna()]
            assert len(rows) > 0
            r.loc[rows[0], "engine_speed_rpm"] = request.param  # SPN 190 minimum is 0 rpm
        return ds

    monkeypatch.setattr(ref, "simulate", corrupting)


def test_validate_failing_dataset_exits_validation_failed(
    tmp_path, below_min_on_clean_row, capsys: pytest.CaptureFixture[str]
) -> None:
    from can_telemetry_forge.cli import _VALIDATION_FAILED_EXIT

    rc = main(["validate", "--config", str(_tiny_config(tmp_path)), "--seed", str(_GATE_SEED)])
    captured = capsys.readouterr()
    assert rc == _VALIDATION_FAILED_EXIT == 4
    assert "forge validate: FAIL" in captured.err
    assert "1 below / 0 above" in captured.out


def test_validate_failing_dataset_via_library(tmp_path, below_min_on_clean_row) -> None:
    from dataclasses import replace

    from validation import run_validation

    from can_telemetry_forge.config import load_config

    run = run_validation(replace(load_config(_tiny_config(tmp_path)), seed=_GATE_SEED))
    assert run.passed is False
    in_spec = next(r for r in run.results if r.adapter == "in_spec")
    failed = [c for c in in_spec.checks if not c.passed]
    assert [c.name.split(" ")[0] for c in failed] == ["engine_speed_rpm"]


def test_validation_failed_code_is_distinct_from_crash_and_usage() -> None:
    from can_telemetry_forge import cli

    codes = {
        1,  # an uncaught exception
        cli._USAGE_EXIT,
        cli._VALIDATION_IMPORT_EXIT,
        cli._VALIDATION_FAILED_EXIT,
        cli._INPUT_ERROR_EXIT,
    }
    assert len(codes) == 5


@pytest.mark.parametrize(
    "argv_tail",
    [
        ["validate", "--config", "{missing}"],
        ["generate", "--out", "{out}", "--config", "{missing}"],
        ["generate", "--out", "{out}", "--config", "{tiny}", "--days", "0"],
        ["validate", "--config", "{bad_json}"],
        ["generate", "--out", "{out}", "--config", "{tiny}", "--seed", "-1"],
        ["validate", "--config", "{tiny}", "--seed", "-1"],
        ["validate", "--config", "{str_seed}"],
        ["validate", "--config", "{nan_days}"],
        ["validate", "--config", "{nan_horizon}"],
        ["validate", "--config", "{inf_days}"],
        ["validate", "--config", "{bad_contract}"],  # TypeError inside config_from_dict
        ["validate", "--config", "{json_list}"],  # AttributeError inside config_from_dict
        ["validate", "--config", "{deep_json}"],  # RecursionError while decoding
        ["validate", "--config", "{tiny}", "--report", "{missing_dir}/r.md"],
        ["generate", "--config", "{tiny}", "--out", "{tiny}"],  # --out is an existing file
    ],
)
def test_bad_config_or_input_exits_input_error_with_one_line(
    tmp_path, argv_tail, capsys: pytest.CaptureFixture[str]
) -> None:
    from can_telemetry_forge.cli import _INPUT_ERROR_EXIT

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{not json", encoding="utf-8")
    def raw(name: str, text: str) -> str:
        f = tmp_path / name
        f.write_text(text, encoding="utf-8")
        return str(f)

    subs = {
        "{str_seed}": raw("s.json", '{"days": 1, "resolution": "5min", "seed": "abc"}'),
        "{nan_days}": raw("n.json", '{"days": NaN, "resolution": "5min"}'),
        "{inf_days}": raw("i.json", '{"days": Infinity, "resolution": "5min"}'),
        "{nan_horizon}": raw("h.json", '{"days": 1, "resolution": "5min", "failure_horizon_h": NaN}'),
        "{bad_contract}": raw("c.json", '{"fleet": {"contracts": [{"id": "a"}]}}'),
        "{json_list}": raw("l.json", "[1]"),
        "{deep_json}": raw("d.json", "[" * 200_000 + "]" * 200_000),
        "{missing_dir}": str(tmp_path / "no_such_dir"),
        "{missing}": str(tmp_path / "nope.json"),
        "{out}": str(tmp_path / "out"),
        "{tiny}": str(_tiny_config(tmp_path)),
        "{bad_json}": str(bad_json),
    }
    argv = [subs.get(a, a) for a in argv_tail]
    argv = [a.replace("{missing_dir}", subs["{missing_dir}"]) for a in argv]
    rc = main(argv)
    err = capsys.readouterr().err
    assert rc == _INPUT_ERROR_EXIT == 5
    lines = [ln for ln in err.splitlines() if ln.strip()]
    assert len(lines) == 1, err
    assert lines[0].startswith(f"forge {argv_tail[0]}: ")
    assert "Traceback" not in err
