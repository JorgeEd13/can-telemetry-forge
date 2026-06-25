"""Command-line entry point for can-telemetry-forge.

Exposes the ``forge`` command. ``forge generate`` (F2) produces a reproducible
Tier-1 dataset from a config + seed; ``forge validate`` (F4) checks the generated
distributions for plausibility and writes a self-contained report. Everything
``generate`` does is a thin wrapper over the library (``config`` → ``sim.simulate``
→ ``io.write_dataset``) so a downstream consumer can import it directly instead of
shelling out.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__

# `forge validate` lives in the opt-in ``validation/`` package (outside ``src/`` —
# the core never imports it). A non-zero exit code if any validation check fails.
_VALIDATION_FAILED_EXIT = 1
_VALIDATION_IMPORT_EXIT = 3


def _write_utf8(stream, text: str) -> None:
    """Write ``text`` to ``stream`` as UTF-8, tolerating a legacy-codepage console.

    The validation report contains non-ASCII status glyphs; a naive ``print`` crashes
    on a cp1252 stdout (common on Windows). Prefer the underlying binary buffer; fall
    back to a replacing encode so output is never lost to a UnicodeEncodeError.
    """
    buffer = getattr(stream, "buffer", None)
    if buffer is not None:
        buffer.write(text.encode("utf-8"))
        buffer.flush()
        return
    encoding = getattr(stream, "encoding", None) or "utf-8"
    stream.write(text.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    stream.flush()


def build_parser() -> argparse.ArgumentParser:
    """Build the ``forge`` argument parser.

    Kept as a function so tests can exercise parsing without invoking ``main``.
    """
    parser = argparse.ArgumentParser(
        prog="forge",
        description=(
            "Generate synthetic, J1939-grounded heavy-equipment telemetry for "
            "predictive-maintenance datasets."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"forge {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # `forge generate` — the headline command (F2, Tier 1 ships).
    generate = subparsers.add_parser(
        "generate",
        help="generate a Tier-1 telemetry dataset",
        description="Generate a reproducible telemetry dataset from a config + seed.",
    )
    generate.add_argument("--config", help="path to a JSON fleet config (default: bundled fleet)")
    generate.add_argument("--seed", type=int, help="random seed (overrides the config seed)")
    generate.add_argument("--out", required=True, help="output directory for the generated tables")
    generate.add_argument(
        "--format",
        choices=("parquet", "csv", "duckdb"),
        default="parquet",
        help="output format (default: parquet)",
    )
    generate.add_argument("--days", type=int, help="window length in days (overrides config)")
    generate.add_argument(
        "--resolution",
        choices=("1s", "1min", "5min"),
        help="time resolution (overrides config)",
    )
    generate.add_argument(
        "--season",
        choices=("baseline", "heatwave", "cold_snap", "wet_season"),
        help=(
            "Tier-2 seasonal modifier (overrides config; default baseline). The knob "
            "a future drift demo shifts — moves ambient + tilts failure hazards."
        ),
    )

    # `forge validate` — distribution validation (F4, opt-in).
    validate = subparsers.add_parser(
        "validate",
        help="validate generated distributions and write a plausibility report",
        description=(
            "Validate generated distributions against the documented J1939 ranges, "
            "a pinned reference run, and (opt-in) a license-checked public dataset "
            "fetched at run time. Never ships or commits real data."
        ),
    )
    validate.add_argument("--config", help="path to a JSON fleet config (default: bundled fleet)")
    validate.add_argument("--seed", type=int, help="random seed (overrides the config seed)")
    validate.add_argument("--report", help="path to write the Markdown report (default: stdout)")
    validate.add_argument(
        "--dataset",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "opt into a network reference dataset (repeatable). 'ved' = Vehicle "
            "Energy Dataset (CC-BY 4.0), fetched at run time, never committed."
        ),
    )
    validate.add_argument(
        "--ved-handle",
        metavar="OWNER/SLUG",
        help=(
            "Kaggle dataset handle for the 'ved' adapter (default: FORGE_VED_HANDLE "
            "env or the bundled default). Must carry the OBD-II engine columns."
        ),
    )

    return parser


def _run_generate(args: argparse.Namespace) -> int:
    """Execute ``forge generate`` over the library. Returns an exit code."""
    from dataclasses import replace

    from .config import load_config, resolve_season
    from .io import write_dataset
    from .sim import simulate

    config = load_config(args.config)
    overrides: dict = {}
    if args.seed is not None:
        overrides["seed"] = args.seed
    if args.days is not None:
        overrides["days"] = args.days
    if args.resolution is not None:
        overrides["resolution"] = args.resolution
    if args.season is not None:
        overrides["season"] = resolve_season(args.season)
    if overrides:
        config = replace(config, **overrides).validate()

    dataset = simulate(config)
    out = write_dataset(dataset, args.out, fmt=args.format)
    print(
        f"forge generate: wrote {dataset.readings.shape[0]:,} readings for "
        f"{dataset.units.shape[0]} units → {out} ({args.format}, seed {config.seed}).",
        file=sys.stderr,
    )
    return 0


def _run_validate(args: argparse.Namespace) -> int:
    """Execute ``forge validate``. Returns an exit code (non-zero on check failure).

    The offline adapters (J1939 in-spec, golden reference run) always run, so the
    command works with no network and is reproducible by anyone. ``--dataset ved``
    layers a real-data overlap on top, fetching the CC-BY VED at run time (never
    committed). The validation package lives outside ``src/`` and is imported here
    lazily so the core library never depends on it.
    """
    from dataclasses import replace

    try:
        from validation import render_report, run_validation
    except ImportError as exc:
        print(
            "forge validate: the opt-in validation package isn't importable "
            f"({exc}). Run from the repo root (it lives in ./validation), and "
            "install the extra: pip install -e '.[validate]'.",
            file=sys.stderr,
        )
        return _VALIDATION_IMPORT_EXIT

    from .config import load_config

    config = load_config(args.config)
    if args.seed is not None:
        config = replace(config, seed=args.seed).validate()

    datasets = tuple(args.dataset)
    run = run_validation(config, datasets=datasets, ved_handle=args.ved_handle)
    report = render_report(run, datasets=datasets)

    if args.report:
        from pathlib import Path

        Path(args.report).write_text(report, encoding="utf-8")
        print(f"forge validate: wrote report -> {args.report}", file=sys.stderr)
    else:
        # The report carries non-ASCII (status glyphs); write UTF-8 directly so it
        # doesn't crash on a legacy-codepage console (e.g. Windows cp1252).
        _write_utf8(sys.stdout, report + "\n")

    print(
        f"forge validate: {'PASS' if run.passed else 'FAIL'} "
        f"(seed {config.seed}; adapters: "
        f"{', '.join(r.adapter for r in run.results) or 'none'}).",
        file=sys.stderr,
    )
    return 0 if run.passed else _VALIDATION_FAILED_EXIT


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``forge`` CLI. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "generate":
        return _run_generate(args)

    if args.command == "validate":
        return _run_validate(args)

    parser.print_help()  # pragma: no cover - argparse rejects unknown commands first
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
