# Data Design — can-telemetry-forge

The heart of the project. This document specs **what** the generator produces and
**why it is credible**. It is meant to be co-written with operational domain
experience and expanded before/while Phase 1 modeling happens. The MVP builds
**Tier 1**; Tiers 2–3 are fully specced here as named later phases.

> Status: skeleton awaiting the co-writing session (see STATE.md "Next step").
> Sections below are the agreed structure; per-signal numbers/ranges get filled in
> from the J1939 standard + physics + the user's domain experience.

## Provenance (load-bearing)

- **Grounded in the public SAE J1939 standard** (PGN/SPN structure, ranges, units,
  scaling/offset) + **documented physical relationships**. No proprietary data.
- **No real telemetry is shipped or used as a seed.** A permissively-licensed
  public dataset may be used in `validation/` only, license verified first, to
  sanity-check distributions — never committed, never seeded from.
- The output is **synthetic and labeled as such** everywhere.

## Entities

- **Equipment unit** — id, model, manufacture/age, accumulated runtime hours,
  region assignment, (Tier 2) contract.
- **Region / contract** — (Tier 2) climate baseline, seasonal profile, duty cycle.
- **Reading** — a timestamped row of CAN signals for one unit.

## Core signals (Tier 1) — to be filled from J1939 + physics

For each signal: J1939 SPN (where applicable), unit, realistic range, baseline
distribution, and its documented dependencies on other signals / external
variables.

| Signal | J1939 SPN | Unit | Depends on (documented) |
|---|---|---|---|
| Engine speed (RPM) | _tbd_ | rpm | duty cycle, load |
| Engine load | _tbd_ | % | duty cycle |
| Fuel rate | _tbd_ | L/h | load · RPM |
| Coolant temperature | _tbd_ | °C | ambient temp, load, runtime |
| Oil pressure | _tbd_ | kPa | RPM, wear |
| Vibration | _tbd_ | mm/s | load, accumulated wear |
| Runtime hours | n/a | h | accumulates over time |
| Equipment age | n/a | days | fixed per unit |

> The cross-signal correlations (signs and rough strengths) are the credibility of
> the dataset — they get documented here and asserted in tests.

## Failure label (Tier 1)

`failure_within_h` derived from accumulated wear + age + sustained abnormal signal
conditions, with a documented hazard relationship. Derived in **one** place so the
generator and any downstream consumer agree.

## Anomalies & faults (labeled — F3)

Every injected defect carries ground-truth labels so downstream QA/anomaly work is
verifiable.

- **Obvious outliers** (Tier 1, from F2): out-of-range spikes, impossible values.
- **Subtle / joint outliers** (Tier 3): per-column plausible, jointly inconsistent
  (e.g. high fuel rate with low load).
- **Sensor faults** (Tier 3): stuck channel, single-channel drift, dropout/missing.
- **CAN faults** (Tier 3): malformed/implausible frame patterns.

Each has a configurable rate and a label column/table.

## Diversity (Tier 2)

- **Regions / climate**: ambient-temperature baselines and seasonal curves per
  region; a heatwave/cold-snap modifier (this is what a future drift demo shifts).
- **Equipment models**: distinct baseline profiles and failure hazards per model.
- **Seasonality**: duty-cycle and ambient seasonal effects.
- **(Intentionally richer than "Brazilian states")**: a fictional international
  operator with distinct regional climates and contracts.

## Output schema

Tidy **long** tables (one row per unit-timestamp-reading) + dimension tables
(units, regions/contracts) + label tables. Emitted to Parquet / CSV / DuckDB. A
`docs/DATA_DICTIONARY.md` documents every field, its unit, and its J1939 SPN where
applicable.

## Reproducibility

Everything regenerates from `config + seed`. Same seed → identical data. No global
randomness; the seeded generator is threaded through.

## Open questions for the co-writing session

- Exact Tier-1 signal set + per-signal J1939 ranges to commit to.
- Time resolution (per-second? per-minute aggregates?) and dataset size targets.
- Failure hazard shape (which conditions, what horizon `h`).
- Which public dataset to validate against (license check pending — F4).
