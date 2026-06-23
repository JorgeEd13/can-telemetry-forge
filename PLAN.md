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
