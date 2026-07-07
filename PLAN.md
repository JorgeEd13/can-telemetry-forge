# PLAN — can-telemetry-forge

A public, clean-room portfolio project: a **synthetic heavy-equipment telemetry
generator** grounded in the published **SAE J1939** CAN Bus standard and
documented physical relationships. Goal: a navigable, runnable repo that produces
realistic predictive-maintenance datasets — diverse, statistically credible, and
reproducible — for a fictional international fleet operator.

The data is the product. The generator emits correlated CAN signals over time for
a configurable fleet, injects **labeled** anomalies and sensor faults, derives a
failure label, and writes tidy tables ready for any downstream ML. A later,
separate MLOps vitrine will consume this generator as its data source.

## Why this exists (portfolio framing)

This is the **3rd public showcase** (after `receivables-agent` and
`machine_scanner`). It targets the data-engineering + domain-depth axis: building
a configurable, standards-grounded synthetic-data engine for industrial telemetry
is rarer and more memorable than "I trained a model", and it makes operational /
CAN Bus domain knowledge **visible as code** without exposing any private data.

The originally-planned **MLOps** vitrine becomes the **4th** project: it imports
this generator as its data source (train → MLflow tracking → model registry →
FastAPI serving → drift monitoring). Two repos that compose into one story —
"built the data engine, then the production ML system on top of it."

## Principles

- **English everywhere**; clean room (reimplement from standards/physics, never
  copy private code/data); secrets hygiene (nothing secret here, but no real logs
  committed).
- **Clean-room data provenance.** The signal model is grounded in the **publicly
  documented J1939 standard** (PGN/SPN structure, ranges, units, scaling) plus
  **textbook physical correlations** — not in any proprietary or non-redistributable
  dataset. A permissively-licensed public CAN/OBD dataset may be used **only to
  validate** that generated distributions look plausible (compare histograms);
  its license is verified first, and it is **never shipped or seeded from**.
- **Reproducible by construction.** Every dataset is regenerable from a config
  file + a fixed seed. Same seed → same data.
- **Plan first**; record non-obvious choices as ADRs in `docs/DECISIONS.md`.
- **Honest framing** (`feedback_honest_cv_framing`): the README states clearly
  that the output is *synthetic, modeled on J1939 + physics* — never implied to be
  real telemetry. Mark what is shipped vs. designed.
- A great README and a clean architecture count as much as the feature count.
- **No GPU, no paid services, no training tokens.** Generation is plain
  NumPy/pandas locally; validation and tests run in free GitHub Actions CI.

## Grounding sources (to cite in README)

- **SAE J1939** — the heavy-duty CAN application layer. Publicly documented
  message structure: PGNs (Parameter Group Numbers), SPNs (Suspect Parameter
  Numbers), value ranges, units, scaling/offset. Used to model the *encoding* and
  *realistic ranges* of engine RPM, coolant temperature, fuel rate, engine load,
  oil pressure, etc.
- **Documented physical relationships** — e.g. coolant temperature responding to
  ambient temperature and load; fuel rate tracking load and RPM; vibration rising
  with load and accumulated wear; failure probability increasing with runtime
  hours and equipment age.
- **(Validation only)** a permissively-licensed public CAN/OBD-II/J1939 dataset,
  license-checked, to sanity-check generated distributions. Used in a notebook /
  script under `validation/`, never committed as data nor used to seed.

## The reality check (scope-defining)

Real CAN Bus telemetry is proprietary and its public datasets are often
license-restricted. We do **not** chase a real seed log. Credibility comes from
encoding the *public standard + known physics*, which is more defensible and fully
citable. The validation step confirms our distributions are plausible without
shipping anyone's data.

## Architecture (target)

```
config (fleet, regions, climate, season, anomaly rates, seed)
   │
   ▼
signal model  ── J1939-grounded per-signal generators (RPM, coolant temp,
   │              fuel rate, load, oil pressure, vibration, runtime, age)
   │              with documented cross-signal correlations
   ▼
fleet simulator ── N equipment units (models, ages) emitting time-series
   │               with regional/climate/seasonal modifiers
   ▼
anomaly + fault injection ── labeled outliers (obvious + subtle/joint) and
   │                          sensor faults (stuck / drifting / dropout)
   ▼
label derivation ── failure_within_h target from signals + wear + age
   ▼
writers ── tidy tables → Parquet / CSV / DuckDB  (+ a data dictionary)
   │
   ▼
CLI ── `forge generate --config … --out …`  ;  `forge validate …`
```

The generator is a **library + CLI**; downstream consumers (the future MLOps
repo) import the library or read the emitted tables. See `docs/ARCHITECTURE.md`.

## Data tiers (richness sequenced — see `docs/DATA_DESIGN.md`)

- **Tier 1 (MVP data):** one equipment fleet; core J1939 signals (RPM, coolant
  temp, fuel rate, engine load, oil pressure, vibration, runtime hours, age);
  documented correlations; age/wear-driven failure label; deliberate bad data and
  **obvious** labeled outliers. Enough structure that the model is non-trivial and
  drift is demonstrable downstream.
- **Tier 2:** multiple regions/contracts with different climate baselines;
  multiple equipment models with distinct failure profiles; seasonal effects.
  This is what makes a future drift demo *rich* (a regional heatwave shifts that
  segment's inputs).
- **Tier 3:** subtle / correlated (joint) outliers; sensor-fault patterns (stuck
  channel, single-channel drift, dropout); CAN-fault injection. The "looks fine
  per column, wrong jointly" cases.

`docs/DATA_DESIGN.md` specs all three tiers in full; the MVP **builds Tier 1**,
Tiers 2–3 are named later phases. Nothing is cut — it is sequenced.

## Phases

### Phase 0 — Foundations & runnable skeleton
src-layout package; README / CLAUDE.md / PLAN.md / docs skeletons (ARCHITECTURE,
DECISIONS, DATA_DESIGN, STATE, ROADMAP); MIT license; `.gitignore` (ignore
generated data); pyproject; minimal CLI that prints help and `--version`; first
offline pytest + green CI (Linux + Windows).

### Phase 1 — Signal model (J1939-grounded core)
Per-signal generators for the Tier-1 signals with published ranges/units/scaling
and documented cross-signal correlations; deterministic seed plumbing; a data
dictionary (`docs/DATA_DICTIONARY.md`) mapping each field to its J1939 SPN where
applicable. Offline tests assert ranges, units, correlation signs, and
seed-reproducibility. → ADR: J1939 + physics as the grounding (not real logs).

### Phase 2 — Fleet simulator + writers (Tier 1 ships)
Configurable fleet of N units over a time window → tidy long tables; writers to
Parquet / CSV / DuckDB; `forge generate` CLI (config file + seed + output). The
failure label derived in one place. **This is the MVP cut** — a reproducible,
documented Tier-1 dataset from one command.

### Phase 3 — Anomaly & fault injection (labeled)
Deliberate bad data + obvious outliers (Tier 1, present from Phase 2) extended
with subtle/joint outliers and sensor faults (stuck / drift / dropout) — **all
carrying ground-truth labels** so downstream anomaly/QA work is verifiable. → ADR:
labeled-injection contract (every injected defect is recoverable from a label).

### Phase 4 — Distribution validation
A `validation/` script/notebook that compares generated distributions against a
**license-checked** public CAN/OBD dataset (histograms / summary stats), plus a
self-contained HTML/plots report. The public dataset is fetched at validation
time, never committed. → ADR: validation-only use + license note.

### Phase 5 — Diversity (Tier 2) and richer faults (Tier 3)
Regions / climate / seasonality modifiers; multiple equipment models with distinct
profiles; subtle joint outliers and CAN-fault patterns. Clearly-scoped extensions
that deepen realism and set up the future MLOps drift demo.

### Phase 6 — Richer failure modes (PROPOSED — not yet built)
**Motivation.** The label layer models three failure modes today
(`overheat` / `oil_starve` / `bearing` — `labels/failure.py:FAILURE_MODES`). A
predictive-maintenance dataset that only knows three modes under-sells the "full
CAN Bus data" premise; more distinct modes make both the data and the downstream
model story richer, and exercise the `boost_pressure_kpa` / `def_level_pct` signals
that currently drive no failure.

**Extension points (all local edits — the same "data + a small behaviour" pattern
as the anomaly registry).** Per new mode: (1) add its name to `FAILURE_MODES`;
(2) a hazard in `_mode_hazards` (soft-thresholded stress × wear-gain); (3) a
degradation signature in `_DEGRADATION` (signal → peak engineering-unit excursion,
sized to clear the hazard knee); (4) threshold constants; (5) per-class and
per-season `hazard_mult` entries in `config.py`. The `failure_mode` schema stays
closed (one categorical), open vocabulary — a new mode is a new *value*, never a
new column.

**Candidate modes, chosen for *distinct* signatures** (so a classifier can separate
them, and so they use the two idle signals):

| mode | pre-failure signature | why distinct |
|---|---|---|
| `turbo_underboost` | boost ↓ under load, EGT ↑, fuel ↑ | the boost **drop** separates it from `overheat` (coolant+EGT) |
| `aftertreatment_derate` (DEF/SCR) | DEF level ↓ → engine-load ceiling | uses `def_level_pct`, unused by any current mode |
| `injector_fouling` | fuel ↑ decoupled from load, rough RPM | fuel-vs-load decoupling is its own pattern |

**Two constraints the design must honour:**
- **Avoid the mode↔missingness confound.** `oil_starve` currently strikes an older
  sensor-era that lacks egt/DEF/vibration, so a downstream model can partly detect
  it via *which sensors are NULL* rather than the physics. A mode keyed on
  `def_level` would only exist on DEF-equipped (newer) units — the same trap. Either
  base signatures on widely-present signals, or deliberately spread each mode across
  eras (and document the choice). *(Surfaced 2026-07-06 building the downstream demo
  fixture — see forge-pdm-mlops ADR-019.)*
- **Downstream ripple is part of the phase.** New modes force the consumer
  (`forge-pdm-mlops`) to regenerate the full dataset, re-baseline overall + per-mode
  AUC, regenerate its multi-mode smoke fixture (its builder already iterates
  `FAILURE_MODES`, so it auto-covers new modes), and add + validate a `/demo` preset
  per mode. Treat that as the phase's definition-of-done, not an afterthought.

**Recommended first cut:** `turbo_underboost` + `aftertreatment_derate` (cleanest
separation, and they light up the two idle signals), as one phase with its own ADR;
`injector_fouling` and any coolant-loss variant follow if the separation holds.

## MVP cut

Phases 0–2 plus the obvious-outlier slice of Phase 3: a reproducible, documented,
**Tier-1** predictive-maintenance dataset generated from one command, with a clean
data dictionary, offline tests and green CI. That alone is a navigable showcase of
standards-grounded synthetic data engineering. Validation (Phase 4) and
diversity/richer faults (Phase 5) are named extensions.

## Out of scope (for now)

- **A fully general, domain-agnostic data-generation framework.** The
  predictive-maintenance / J1939 core is the deliverable; a generic engine is a
  tempting trap, explicitly deferred to a possible future project.
- **Shipping or seeding from any real CAN dataset** — provenance is standards +
  physics; real data appears only in license-checked validation, never committed.
- **The ML model itself and MLOps tooling** — those belong to the 4th vitrine,
  which consumes this generator as its data source.
