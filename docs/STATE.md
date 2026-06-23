# State — can-telemetry-forge

Updated: 2026-06-23

## Current focus

F0 is **done**: the package is installable and the `forge` CLI runs, with offline
tests green and CI configured for Linux + Windows. Next is co-writing
`docs/DATA_DESIGN.md` in full with the user, then F1 (the J1939-grounded signal
model).

## Done

- Project decided and named (`can-telemetry-forge`): the 3rd public vitrine, a
  synthetic J1939-grounded heavy-equipment telemetry generator. MLOps deferred to
  a 4th vitrine that will consume this one.
- Start-of-project decisions taken with the user (domain, grounding, tiers, scope).
- PLAN.md + CLAUDE.md + docs skeletons (this file, ROADMAP, DATA_DESIGN,
  ARCHITECTURE, DECISIONS) written.
- **F0 — Foundations & runnable skeleton:**
  - src-layout package `src/can_telemetry_forge` (`__init__` with `__version__`
    sourced from installed metadata + literal fallback; `cli.py`).
  - `forge` CLI (argparse, zero extra deps): `--version`, `--help`, and stub
    `generate` / `validate` subcommands that fail honestly (exit 2, "lands in Fx").
  - First offline, deterministic pytest (`tests/test_cli.py`, 7 tests passing).
  - GitHub Actions CI (`.github/workflows/ci.yml`): Linux + Windows × Py 3.11/3.12,
    installs `-e .[dev]`, runs `forge --version` and pytest.
  - README status updated (plan-stage → F0 skeleton).
  - **DoD verified locally:** `pip install -e .` works, `forge --version` → `forge
    0.1.0`, `pytest` green offline.

## Next step (concrete)

1. Co-write `docs/DATA_DESIGN.md` in full with the user (their operational
   experience with heavy equipment) — the signal list, ranges, units, and the
   cross-signal correlations — before F1 begins.
2. F1 — signal model: per-signal deterministic generators for the Tier-1 signals,
   grounded in published J1939 ranges/units/scaling, with documented correlations
   and `docs/DATA_DICTIONARY.md` mapping fields to SPNs.

## Notes

- No GPU, no paid services, no training tokens — generation is local
  NumPy/pandas; CI is free GitHub Actions.
- Clean-room provenance is the load-bearing constraint: standards + physics,
  never a real-log seed; public dataset only for license-checked validation.
