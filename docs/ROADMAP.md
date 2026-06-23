# Roadmap — can-telemetry-forge

Phases with Objective / How / Definition of Done. Volatile status lives in
`STATE.md`; this file is the stable phase contract. The **MVP cut is F0–F2 plus
the obvious-outlier slice of F3**.

Status legend: ☐ not started · ◑ in progress · ✅ done

---

## F0 — Foundations & runnable skeleton  ✅

**Objective.** A runnable, installable, CI-green skeleton with all conventions in
place.

**How.** src-layout package `can_telemetry_forge`; README (hero, tagline, honest
"synthetic, modeled on J1939 + physics" framing, badges); CLAUDE.md; PLAN.md;
docs (this roadmap, DATA_DESIGN, ARCHITECTURE, DECISIONS, STATE); MIT LICENSE;
`.gitignore` (generated data + downloaded validation data); pyproject; minimal
`forge` CLI (`--help`, `--version`); first offline pytest.

**DoD.** `pip install -e .` works; `forge --version` runs; pytest passes offline;
CI green on Linux + Windows.

---

## F1 — Signal model (J1939-grounded core)  ✅

**Objective.** Per-signal generators for the Tier-1 signals, grounded in published
J1939 ranges/units/scaling and documented cross-signal correlations.

**How.** Signals (engine-core + drivetrain extras, see DATA_DESIGN §5): engine RPM,
coolant temp, oil pressure, runtime hours, engine load, fuel rate, intake/boost
pressure, EGT, DEF level, vibration, equipment age. Each generator seeded and
deterministic; correlations documented (e.g. fuel rate ↔ load·RPM, coolant temp ↔
ambient + load, EGT ↔ altitude + load, vibration ↔ terrain + wear). Signals are
**gated by capability era** — a unit's era omits unsupported SPNs (NULL, not zero).
`docs/DATA_DICTIONARY.md` maps each field to its J1939 SPN + unit + capability era.

**DoD.** Offline tests assert ranges, units, correlation signs, **era-gating**
(unsupported SPN → NULL), and seed-reproducibility; data dictionary committed; ADRs
for the J1939+physics grounding and era-gating (ADR-008) recorded.

**Shipped.** `signals/` package: declarative `SignalSpec` registry (ADR-012) with
the 11 Tier-1 signals' real J1939 SPN/PGN/unit/range, era gating (`eras.py`,
NULL-not-zero), deterministic per-signal generators (`generators.py`) threading one
seeded rng. `docs/DATA_DICTIONARY.md` committed. 21 offline tests (28 total green).
PGNs recorded but inert (ADR-013).

---

## F2 — Fleet simulator + writers (Tier 1 ships)  ✅  ← MVP

**Objective.** Generate a reproducible Tier-1 dataset for a configurable fleet
from one command.

**How.** Fleet of N units (models, ages) over a time window → tidy long tables;
writers to Parquet / CSV / DuckDB; failure label derived in one place; `forge
generate --config … --seed … --out …`. Deliberate bad data + obvious labeled
outliers included.

**DoD.** One command produces a documented Tier-1 dataset; same seed → identical
output (tested); README shows the one-command run; offline tests for the writers
and label derivation.

**Shipped.** `config.py` (declarative config + public-grounded fleet/region
catalog + seed plumbing; JSON config merging onto a runnable default, ADR-015).
`sim/` (fleet composition: 5-class mix, triangular age curve with a legacy tail,
per-contract sizes; per-unit driver synthesis from region climate/terrain/wear;
the simulator threading one spawned `SeedSequence` per unit per stage).
`labels/failure.py` (multi-mode `failure_within_h` + `failure_mode`, derived in one
place, ADR-009). `anomalies/outliers.py` (labeled obvious outliers, recoverable —
the F3 slice that ships now, ADR-006). `io/writers.py` (Parquet/CSV/DuckDB +
`manifest.json` provenance + generated `dataset_dictionary.md`). `forge generate
--config --seed --out --format --days --resolution` wired over the library. Regions
pinned to cited public sources (ADR-014). **31 new offline tests (59 total green).**
Verified end-to-end: default fleet → 106 units, 915,840 readings, all three failure
modes present, EGT NULL for the pre-Modern 57%.

---

## F3 — Anomaly & fault injection (labeled)  ☐

**Objective.** A labeled-defect contract: every injected anomaly/fault is
recoverable from ground-truth labels.

**How.** Extend the obvious-outlier slice (shipped in F2) with subtle/joint
outliers and sensor faults (stuck channel, single-channel drift, dropout). Each
injection writes a label column / table.

**DoD.** Tests verify each defect type is present at the configured rate and fully
recoverable from labels; ADR for the labeled-injection contract.

---

## F4 — Distribution validation  ☐

**Objective.** Show the generated distributions are plausible against real-world
data — without shipping anyone's data.

**How.** A `validation/` script/notebook compares generated distributions to a
**license-checked** public CAN/OBD/J1939 dataset (histograms, summary stats) and
emits a self-contained report. Public data fetched at run time, never committed.

**DoD.** Validation report reproducible from a documented command; license note in
README and an ADR; CI does not require the external data (validation is opt-in).

---

## F5 — Diversity (Tier 2) & richer faults (Tier 3)  ☐

**Objective.** Deepen realism: regional/climate/seasonal diversity and the
trickier fault patterns that set up a future drift demo.

**How.** Regions/contracts with climate baselines; multiple equipment models with
distinct failure profiles; seasonal effects (Tier 2). Subtle joint outliers and
CAN-fault patterns (Tier 3). All configurable, all labeled, all seeded.

**DoD.** Config-driven multi-region/multi-model generation tested; richer faults
labeled and tested; DATA_DESIGN updated to reflect what shipped.
