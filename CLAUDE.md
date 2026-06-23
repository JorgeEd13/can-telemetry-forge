# CLAUDE.md — conventions for AI-assisted development

Guidance for any AI collaborator (and humans) working in this repo. Read this
first, then [`docs/STATE.md`](docs/STATE.md) for where things currently stand.

## What this project is

`can-telemetry-forge` is a **public portfolio project**: a synthetic
heavy-equipment telemetry generator grounded in the published **SAE J1939** CAN
Bus standard and documented physics. It produces realistic predictive-maintenance
datasets for a fictional international fleet operator. Clean room — it models the
standard and known physical relationships from scratch and contains **no
proprietary code or data**.

It is the 3rd public showcase (after `receivables-agent` and `machine_scanner`).
A future MLOps vitrine will consume this generator as its data source.

## How to resume (reading order)

1. [`docs/STATE.md`](docs/STATE.md) — current focus, done, next step. **Always.**
2. [`docs/ROADMAP.md`](docs/ROADMAP.md) — phases (F0…F5) with Objective / How / DoD.
3. [`docs/DATA_DESIGN.md`](docs/DATA_DESIGN.md) — the signal model + data tiers (the heart).
4. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — the generator/simulator/writer design.
5. [`docs/DECISIONS.md`](docs/DECISIONS.md) — ADRs (why J1939, why labeled injection, …).
6. [`PLAN.md`](PLAN.md) / [`README.md`](README.md) — plan + product-level usage.

## Golden rules

1. **English everywhere.** Names, comments, commits, docs — all English.
2. **Clean room.** Never copy code or data from private projects. The signal
   model is reimplemented from the **public J1939 standard + documented physics**.
   No real telemetry is a source.
3. **Clean-room data provenance.** No real CAN dataset is shipped or used as a
   seed. A permissively-licensed public dataset may appear **only** under
   `validation/` to sanity-check distributions, license verified first, fetched at
   run time, never committed.
4. **Honest output.** The data is synthetic and labeled as such everywhere — never
   implied to be real telemetry.
5. **Reproducible.** Everything regenerates from a config + fixed seed. Same seed
   → same data. No hidden global randomness.
6. **Secrets hygiene.** Nothing secret here; never commit generated data
   (`.gitignore` covers output dirs and downloaded validation data).
7. **Plan before you code.** Record non-obvious choices in `docs/DECISIONS.md`.
8. **Token economy.** Volatile state in `docs/STATE.md`; durable design in
   `docs/ARCHITECTURE.md` / `docs/DATA_DESIGN.md`; decisions in `docs/DECISIONS.md`.

## Architecture in one paragraph

A **config** (fleet, regions, climate, season, anomaly rates, seed) drives a
**signal model** (J1939-grounded per-signal generators with documented
cross-signal correlations), wrapped by a **fleet simulator** (N units emitting
time-series with regional/climate/seasonal modifiers). **Anomaly & fault
injection** adds labeled outliers and sensor faults; **label derivation** produces
the failure target; **writers** emit tidy Parquet / CSV / DuckDB tables plus a
data dictionary. A **CLI** (`forge generate` / `forge validate`) ties it together.
Downstream consumers import the library or read the tables.

## Where things live (target layout)

- `src/can_telemetry_forge/signals/`   — per-signal generators (J1939-grounded)
- `src/can_telemetry_forge/sim/`        — fleet simulator (units, time-series, modifiers)
- `src/can_telemetry_forge/anomalies/`  — labeled outlier + sensor-fault injectors
- `src/can_telemetry_forge/labels/`     — failure-label derivation
- `src/can_telemetry_forge/io/`         — writers (parquet / csv / duckdb) + data dictionary
- `src/can_telemetry_forge/config.py`   — config schema + seed plumbing
- `src/can_telemetry_forge/cli.py`      — argparse/typer entry point (`forge`)
- `validation/`                         — distribution validation vs a public dataset (not shipped)
- `tests/`                              — offline, deterministic pytest
- `docs/`                               — STATE, ROADMAP, DATA_DESIGN, ARCHITECTURE, DECISIONS, DATA_DICTIONARY

## Conventions

- Python ≥ 3.11, type hints, `from __future__ import annotations`.
- All randomness flows through a seeded generator passed down — never a bare
  `random`/`np.random` global call. Determinism is a hard requirement.
- Every injected anomaly/fault is **labeled** — the ground truth is recoverable.
- J1939-derived fields carry their SPN/units in the data dictionary.
- Unit tests stay offline and deterministic (no network, no downloaded data).

## Watch for portfolio-worthy findings

This is a career-showcase repo. When something genuinely CV/post-worthy appears (a
clever standards-grounded technique, a shipped capability, a number), note it for
`repo-base-career/sistema/ACHADOS.md` — even unprompted. Sanitize to the public
level (it is already clean-room; standard/method are free to mention).

## Definition of done (per feature)

- Code + type hints + a focused offline, deterministic test.
- `docs/STATE.md` updated (what changed, what's next); phase marked in `ROADMAP`.
- An ADR in `docs/DECISIONS.md` if a non-obvious choice was made.
