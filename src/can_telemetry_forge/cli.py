"""Command-line entry point for can-telemetry-forge.

Exposes the ``forge`` command. ``forge generate`` (F2) produces a reproducible
Tier-1 dataset from a config + seed; ``forge validate`` (F4) is still a stub that
fails honestly. Everything ``generate`` does is a thin wrapper over the library
(``config`` → ``sim.simulate`` → ``io.write_dataset``) so a downstream consumer can
import it directly instead of shelling out.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from . import __version__

_NOT_IMPLEMENTED_EXIT = 2


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

    # `forge validate` — distribution validation, implemented in F4 (opt-in).
    validate = subparsers.add_parser(
        "validate",
        help="validate generated distributions vs a public dataset (coming in F4)",
        description=(
            "Compare generated distributions against a license-checked public "
            "dataset fetched at run time. Never ships or commits real data."
        ),
    )
    validate.add_argument("--report", help="path to write the validation report")

    return parser


def _run_generate(args: argparse.Namespace) -> int:
    """Execute ``forge generate`` over the library. Returns an exit code."""
    from dataclasses import replace

    from .config import load_config
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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``forge`` CLI. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "generate":
        return _run_generate(args)

    # `forge validate` lands in F4; until then, fail honestly.
    parser.exit(
        _NOT_IMPLEMENTED_EXIT,
        "forge validate: not implemented yet — lands in F4 (see docs/ROADMAP.md).\n",
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
