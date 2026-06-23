# State — can-telemetry-forge

Updated: 2026-06-23

## Current focus

Plan-first stage. PLAN.md, CLAUDE.md and docs skeletons are written and awaiting
the user's approval before any code is scaffolded. No package/code yet.

## Done

- Project decided and named (`can-telemetry-forge`): the 3rd public vitrine, a
  synthetic J1939-grounded heavy-equipment telemetry generator. MLOps deferred to
  a 4th vitrine that will consume this one.
- Start-of-project decisions taken with the user (domain, grounding, tiers, scope).
- PLAN.md + CLAUDE.md + docs skeletons (this file, ROADMAP, DATA_DESIGN,
  ARCHITECTURE, DECISIONS) written.

## Next step (concrete)

1. Get the PLAN approved by the user.
2. Phase 0 — scaffold: src-layout package, README with hero/badges/honest framing,
   MIT license, `.gitignore` (ignore generated + downloaded data), pyproject,
   minimal `forge` CLI (`--help`/`--version`), first offline pytest + green CI.
3. Co-write `docs/DATA_DESIGN.md` in full with the user (their operational
   experience) before Phase 1 signal modeling begins.

## Notes

- No GPU, no paid services, no training tokens — generation is local
  NumPy/pandas; CI is free GitHub Actions.
- Clean-room provenance is the load-bearing constraint: standards + physics,
  never a real-log seed; public dataset only for license-checked validation.
