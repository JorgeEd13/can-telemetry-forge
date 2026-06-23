"""Command-line entry point for can-telemetry-forge.

Exposes the ``forge`` command. At F0 the skeleton only wires up argument parsing,
``--version`` and the shape of the future subcommands; the generators land in the
later phases (see ``docs/ROADMAP.md``). Subcommands that are not implemented yet
say so honestly and exit non-zero rather than pretending to work.
"""

from __future__ import annotations

import argparse
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

    # `forge generate` — the headline command, implemented in F2 (Tier 1 ships).
    generate = subparsers.add_parser(
        "generate",
        help="generate a Tier-1 telemetry dataset (coming in F2)",
        description="Generate a reproducible telemetry dataset from a config + seed.",
    )
    generate.add_argument("--config", help="path to the fleet config file")
    generate.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    generate.add_argument("--out", help="output directory for the generated tables")

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


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``forge`` CLI. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    # The pipeline lands phase by phase; until then, fail honestly.
    phase = {"generate": "F2", "validate": "F4"}[args.command]
    parser.exit(
        _NOT_IMPLEMENTED_EXIT,
        f"forge {args.command}: not implemented yet — lands in {phase} "
        f"(see docs/ROADMAP.md).\n",
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
