# Architecture — can-telemetry-forge

> Skeleton — fleshed out as phases land. The data semantics live in
> `DATA_DESIGN.md`; this file is about code structure and data flow.

## Pipeline

```
config (fleet, regions, climate, season, anomaly rates, seed)
   │
   ▼
signal model        per-signal generators, J1939-grounded, seeded
   │                cross-signal correlations documented in DATA_DESIGN
   ▼
fleet simulator     N units (model, age) → time-series with regional /
   │                climate / seasonal modifiers
   ▼
anomaly + faults    labeled outliers (obvious + subtle/joint) and sensor
   │                faults (stuck / drift / dropout); each writes a label
   ▼
label derivation    failure_within_h from signals + wear + age (single source)
   ▼
writers             tidy tables → Parquet / CSV / DuckDB + data dictionary
   │
   ▼
CLI                 forge generate … ;  forge validate …
```

## Design rules

- **Deterministic by construction.** A single seeded random generator is created
  from the config and threaded through every stage. No module touches a global
  random source. Same seed → byte-identical tables.
- **Separation of concerns.** The signal model knows nothing about fleets; the
  simulator composes signals; injection and labeling are post-processing stages
  over generated tables; writers are pure I/O and never generate.
- **Labels are first-class.** Anomaly/fault injection always emits ground truth so
  the dataset is usable for *supervised* anomaly/QA work downstream.
- **Standards traceability.** J1939-derived fields carry their SPN/units into the
  data dictionary, so the dataset is self-describing.
- **Library + CLI.** Everything the CLI does is callable as a library function, so
  the future MLOps repo can import the generator directly instead of shelling out.

## Layout (target)

```
src/can_telemetry_forge/
  config.py        config schema + seed plumbing
  signals/         per-signal generators (J1939-grounded)
  sim/             fleet simulator (units, time-series, modifiers)
  anomalies/       labeled outlier + sensor-fault injectors
  labels/          failure-label derivation
  io/              writers (parquet / csv / duckdb) + data dictionary emit
  cli.py           `forge` entry point
validation/        distribution validation vs a public dataset (not shipped)
tests/             offline, deterministic pytest
docs/              STATE, ROADMAP, DATA_DESIGN, ARCHITECTURE, DECISIONS, DATA_DICTIONARY
```

## Dependencies (intended, minimal)

- **NumPy / pandas** — generation and tidy tables.
- **DuckDB / pyarrow** — Parquet + DuckDB writers.
- **typer or argparse** — CLI (decide in F0; argparse keeps deps minimal).
- Validation extras (plotting, the public dataset fetch) are an optional `[validate]`
  group so the core install and CI stay lean.
