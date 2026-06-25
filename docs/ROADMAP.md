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

## F3 — Anomaly & fault injection (labeled)  ✅

**Objective.** A labeled-defect contract: every injected anomaly/fault is
recoverable from ground-truth labels.

**How.** Extend the obvious-outlier slice (shipped in F2) with subtle/joint
outliers and sensor faults (stuck channel, single-channel drift, dropout). Each
injection writes a label column / table.

**DoD.** Tests verify each defect type is present at the configured rate and fully
recoverable from labels; ADR for the labeled-injection contract.

**Shipped.** Anomaly layer is now a **declarative injector registry** (ADR-016,
mirroring ADR-012) in `anomalies/`: `spec.py` (the `AnomalyInjector` type + the
`anomaly_type` vocabulary), `injectors.py` (the three families — `obvious_outlier`,
`joint_outlier`, and segment-based `sensor_stuck`/`sensor_drift`/`sensor_dropout`),
`inject.py` (`apply_anomalies` orchestrator: per-signal eligibility shrinks as
injectors claim cells → ≤1 defect per cell, era-`NULL` never targeted, per-row
resolution by injector priority). Labels are **one open-vocabulary categorical**
`anomaly_type` + `anomaly_signal`, with `is_outlier` kept as a value-distortion
rollup (excludes dropout). Rates are per-type config (`anomaly_rates`;
`obvious_outlier_rate` kept as a back-compat alias). Writers emit per-type counts in
`manifest.json` and document the columns in the generated dictionary. **14 new
offline tests (73 total green.)** Verified e2e: 20-day/5-min run → all five families
present, `is_outlier` exactly = the four value-distorting types.

---

## F4 — Distribution validation  ✅

**Objective.** Show the generated distributions are plausible against real-world
data — without shipping anyone's data.

**How.** A `validation/` script/notebook compares generated distributions to a
**license-checked** public CAN/OBD/J1939 dataset (histograms, summary stats) and
emits a self-contained report. Public data fetched at run time, never committed.

**DoD.** Validation report reproducible from a documented command; license note in
README and an ADR; CI does not require the external data (validation is opt-in).

**Shipped.** `validation/` package (outside `src/` — the core never imports it) as a
**declarative registry of reference adapters** (ADR-017, mirroring ADR-012/-016):
`reference.py` (the `ReferenceAdapter` registry + `run_validation` orchestrator),
`compare.py` (pure summary-stat + **histogram-intersection** overlap, NumPy-only),
`report.py` (self-contained Markdown report). Three adapters: **`in_spec`** (offline
— values inside documented J1939 ranges), **`golden`** (offline — mean/std match a
*recomputed* pinned reference run, catching generator drift; nothing committed), and
**`ved`** (opt-in — overlap vs the **Vehicle Energy Dataset**, Kaggle **CC-BY 4.0**,
fetched at run time via the Kaggle API, **never committed**, degrades gracefully when
offline). Offline adapters always run so `forge validate` is reproducible-by-anyone
and CI-safe; `--dataset ved` layers the real-data comparison on top. Real `forge
validate --config --seed --report --dataset` wired over the library; `kaggle` is a
offline-deterministic tests cover the adapters; the VED path is tested via a
fake-local-CSV (overlap math) and its graceful-unavailable branch, never hitting the
network in CI; `forge validate` writes UTF-8 so the report renders on a legacy-codepage
console. **VED verified live** (ADR-017 addendum): the configurable handle
(`--ved-handle`, default `yashseth25/ved-segregated`) fetched via the classic Kaggle
REST endpoint (legacy key, `requests` only) gave histogram overlap **0.48 engine RPM /
0.51 engine load** over 200k VED rows.

---

## F5 — Diversity (Tier 2)  ✅

**Objective.** Deepen realism along the Tier-2 axes: regional/climate diversity,
distinct equipment models with their own failure profiles, and configurable
seasonality (the knob a future drift demo shifts).

**How.** Two more public-grounded regions/contracts; a catalog of **equipment
models** (per-mode hazard multipliers + baseline signature offsets + optional
capability-era floor) assigned per unit; named **seasons** (ambient delta + wear +
per-mode hazard multipliers) selectable by config / `--season`. All as declarative
catalog entries resolving to multipliers/offsets — **no new readings-schema
columns** (ADR-018). Labels stay derived in one place (the model × season hazard
multiplier composes into `derive_unit_labels`).

**DoD.** Config-driven multi-region/multi-model generation tested; the seasonal
modifier tested end-to-end; DATA_DESIGN updated to reflect what shipped.

**Shipped.** `config.py` — `EquipmentModel` + `Season` dataclasses, a catalog (6
regions, 6 contracts, 6 equipment models, 4 seasons), validation, and JSON/preset
resolution (`resolve_season`). `sim/fleet.py` assigns a model per unit (class-only
fallback) honouring per-model `build_year_min`. `sim/drivers.py` applies the
season's ambient delta + wear multiplier and threads model offsets into the signal
layer; `signals/generators.py` adds the offsets inside the J1939 clamp.
`labels/failure.py` takes a per-mode `hazard_mult`; `sim/simulate.py` composes
model × season (`_merge_hazard_mults`), emits an `equipment_models` dimension table
+ `units.model_id`. `io/writers.py` writes the new table and echoes `season` in the
manifest. `--season` on `forge generate`. ADR-018 recorded; DATA_DESIGN §6/§9
updated. **12 new offline tests (102 total green.)** Default fleet → 134 units;
heatwave runs produce more failures than baseline, end-to-end.

---

## F6 — CAN-frame faults (Tier 3) & a frame-level encoder  ✅

**Objective.** The trickier Tier-3 fault patterns: malformed / implausible **CAN
frames** (bad byte/bit layout, out-of-spec PGN payloads), the corruption class that
only exists once signals are encoded as actual J1939 frames.

**How.** Build a frame-level encoder (per-PGN byte/bit layout, scaling/offset) over
the inert PGNs recorded since ADR-013 — that is the seam. Then add CAN-frame fault
injectors as new registry entries (ADR-016): each is a new `anomaly_type` *value*,
no schema change. All configurable, labeled, seeded.

**DoD.** Frame encoder round-trips the documented signals; CAN-frame faults labeled
and recoverable from the labels; tested; DATA_DESIGN §8 updated.

**Shipped.** `SignalSpec` gains a frozen `FrameLayout` (start bit, bit length,
scale/offset, byte order) on the 8 bus signals, completing the J1939 identity ADR-013
left inert (ADR-019). `signals/frames.py` is the **frame-level encoder/decoder**:
`value → raw integer → little-endian frame bytes` and back, modeling the J1939
not-available/error sentinels (both decode to `NULL`) and ≤8-byte frames. Four
CAN-frame fault injectors (`anomalies/frame_faults.py`), each a new `anomaly_type`
value in the same open vocabulary (no schema change): `can_frame_corrupt` (byte flip
→ implausible decode), `can_frame_stale` (re-sent frame → frozen value, a transport
fault), `can_frame_error_indicator` (error/NA code → `NULL`), `can_frame_truncated`
(short DLC → `NULL`). They encode → corrupt the **bytes** → decode back into the
engineering column, so the dataset stays decoded; the byte-level corrupted frames are
optionally emitted to a `can_frames` side table (`--emit-raw-frames` /
`emit_raw_frames`, off by default). `is_outlier` rollup, manifest counts, generated
dictionary, and DATA_DESIGN §8 / DATA_DICTIONARY updated. **30 new offline tests (132
total green.)** Verified e2e: the codec round-trips every signal within one quantum;
all four families present, labeled, recoverable; the raw-frame artifact matches the
labeled cells; the value generators still ignore the layout (ADR-013 invariant holds).
