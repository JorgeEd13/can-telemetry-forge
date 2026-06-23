# State — can-telemetry-forge

Updated: 2026-06-23

## Current focus

F0 is **done** and **`docs/DATA_DESIGN.md` is now fully co-written**. The data spec
is settled (two-layer realism, CAN capability by model-year era, multi-mode failure
label, environment = thermal + wear + terrain, configurable resolution/scale).
Next is **F1 — the J1939-grounded signal model + `docs/DATA_DICTIONARY.md`**.

## Done

- Project decided and named (`can-telemetry-forge`): the 3rd public vitrine, a
  synthetic J1939-grounded heavy-equipment telemetry generator. MLOps deferred to
  a 4th vitrine that will consume this one.
- Start-of-project decisions taken with the user (domain, grounding, tiers, scope).
- PLAN.md + CLAUDE.md + docs skeletons (this file, ROADMAP, DATA_DESIGN,
  ARCHITECTURE, DECISIONS) written.
- **DATA_DESIGN co-writing session (with the user):** the spec is now full, not a
  skeleton. Key outcomes (ADR-007…011):
  - **Two-layer realism** — fleet composition (operator/region/contract/unit,
    mixes/age/duty) + J1939 signal model; environment couples them.
  - **CAN capability by model-year era** — older units omit newer SPNs (NULL, not
    zero); signature feature.
  - **Multi-mode failure label** (overheat / oil-starvation / bearing-wear),
    superseding the single age/wear label; records horizon + mode.
  - **Environment** = thermal + wear + **terrain/road-quality** modifiers, all
    public-data-grounded.
  - **Configurable** time resolution (default `1min`) and fleet scale
    (medium-leaning default ~100 units × ~90 days).
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

**F1 — signal model.** Per-signal deterministic generators for the Tier-1 signals,
grounded in published J1939 ranges/units/scaling, with documented cross-signal
correlations, **gated by capability era** (NULL for unsupported SPNs). Commit
`docs/DATA_DICTIONARY.md` mapping each field → SPN + unit + capability era. Offline
tests assert ranges, units, correlation signs, era-gating, and seed-reproducibility.

Open specifics to fill during F1 (also listed in DATA_DESIGN "Still open"):
- exact per-SPN J1939 ranges/scaling + the SPN-per-era table;
- the public regional/climate/road-quality sources to cite for environment modifiers;
- (F2) the concrete vehicle-mix / age-curve / units-per-contract distributions.

## Notes

- No GPU, no paid services, no training tokens — generation is local
  NumPy/pandas; CI is free GitHub Actions.
- Clean-room provenance is the load-bearing constraint: standards + physics,
  never a real-log seed; public dataset only for license-checked validation.
