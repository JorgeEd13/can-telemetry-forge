# Data Design — can-telemetry-forge

The heart of the project. This document specs **what** the generator produces and
**why it is credible**. The MVP builds **Tier 1**; Tiers 2–3 are specced here as
named later phases (see [ROADMAP](ROADMAP.md)).

The credibility of this dataset does **not** come from any single real telemetry
log — it comes from two grounded layers stacked on top of each other:

1. **Fleet realism** — *how a real heavy-equipment operator is actually composed
   and deployed*: machinery types, fleet age curve, units per contract, which kind
   of vehicle goes to which kind of region, and how the environment there wears the
   machine. This is modeled as a fictional international operator, with proportions
   grounded in **public** statistics and documented plausibility.
2. **Signal realism** — *what a CAN bus of that era actually reports*: J1939
   PGN/SPN structure, ranges, units, scaling, and the documented physical
   relationships between signals.

> **Provenance is load-bearing.** Everything here is grounded in the **public SAE
> J1939 standard + public regional/infrastructure/climate data + documented
> physics**. No proprietary code or telemetry is shipped, seeded from, or
> reproduced. The operator is **fictional**. Output is **synthetic and labeled as
> such** everywhere.

---

## 1. The two-layer model

```
                    fleet realism layer                 signal realism layer
   ┌────────────────────────────────────────┐   ┌──────────────────────────────┐
   config ──▶ operator → contracts → units ──┼──▶ per-unit CAN signal model ────┼──▶ tidy tables
              (region, climate, terrain,      │    (J1939 SPNs gated by          │    + labels
               vehicle mix, age curve)        │     model-year capability era)   │    + data dict
   └────────────────────────────────────────┘   └──────────────────────────────┘
              ▲ environment modifiers (thermal + wear + terrain) flow into both ▲
```

The fleet layer decides *who exists and where they work*. The signal layer decides
*what their bus reports and how the numbers move*. Environment couples the two: a
unit's region/climate/terrain shifts its signal baselines **and** accelerates its
failure hazards.

---

## 2. Entities

| Entity | Key attributes |
|---|---|
| **Operator** | fictional international fleet operator; owns contracts and units. |
| **Region** | a deployment geography with a **climate profile** (ambient temp curve, humidity, altitude, dust) and a **terrain/road-quality profile** (roughness, grade) — both grounded in public data. |
| **Contract** | a job a region runs: duty cycle, expected vehicle mix, fleet size. |
| **Equipment model** | a make/model with a **model year** → a **CAN capability era** (which SPNs its bus reports), a baseline signal profile, and per-mode failure hazards. |
| **Unit** | one physical machine: model, build year, region/contract assignment, accumulated runtime hours, individual wear state. |
| **Reading** | one timestamped row of available CAN signals for one unit. |
| **Label** | ground-truth failure horizon + injected-anomaly markers (recoverable). |

> **Structure now, exact proportions at build time.** This doc fixes the
> *dimensions* (what varies, and how). The concrete vehicle-mix percentages, age
> curve, and units-per-contract distributions are filled into the config catalog
> during F1/F2 — grounded in public sources and documented plausibility — rather
> than hard-coded as guessed numbers in this doc.

---

## 3. Fleet composition (the realism backbone)

A real operator is **not** a uniform pool of identical machines. The generator
models the actual structure:

- **Vehicle / machinery mix** — distinct classes (e.g. haul trucks, loaders,
  excavators, compactors, light support vehicles), in realistic proportions that
  vary **by contract type**. A dense-urban collection contract has a different mix
  than a long-haul or earthworks contract.
- **Fleet age curve** — units are not all new. Build year follows a realistic
  distribution (a tail of older machines still in service), because age drives both
  failure hazard **and** CAN capability (§4).
- **Units per contract** — contract size follows a realistic distribution, not a
  constant.
- **City/region → vehicle fit** — the *kind* of region influences which vehicle
  classes are deployed there and how hard they're run (duty cycle).

All of these are **config-driven and seeded**: change the config → a different but
equally plausible fleet; same seed → the identical fleet.

---

## 4. CAN capability by model-year era (signature feature)

A machine's CAN bus only reports what its electronics support. **Older units
simply do not expose newer SPNs** — and most synthetic CAN datasets ignore this,
which is exactly why modeling it makes ours memorable and realistic.

Model years are grouped into **capability eras**, each exposing a defined subset of
SPNs (illustrative grouping — exact SPN-per-era table is committed in
`DATA_DICTIONARY.md` during F1):

| Era (approx.) | Reports |
|---|---|
| **Legacy** (pre-2005) | core engine: engine speed, coolant temp, oil pressure, runtime hours |
| **Mid** (2005–2014) | + engine load, fuel rate, intake/boost pressure |
| **Modern** (2015+) | + EGT, DEF level, vibration, after-treatment / DPF signals |

**Rule:** a signal a unit's era does not support is emitted as **NULL** (missing),
**never as zero** — and the schema documents which signals are era-gated. This is a
realistic, learnable property (downstream models must handle structural
missingness, not impute it as a real reading).

For the MVP, eras are coarse tiers. Tier-2 (F5, ADR-018) takes the first step toward
a per-model refinement: an `EquipmentModel` may set a `build_year_min` capability
floor (a model that only ever shipped Modern hardware), so its units never fall into
an older era. A full per-model SPN whitelist remains a later refinement.

---

## 5. Core signals (Tier 1)

For each signal: J1939 SPN (where applicable), unit, realistic operating range,
baseline behavior, and its **documented dependencies**. Exact ranges/scaling are
filled from the published J1939 standard in F1 and committed to
`DATA_DICTIONARY.md`.

| Signal | J1939 SPN | Unit | Era gate | Depends on (documented) |
|---|---|---|---|---|
| Engine speed (RPM) | _tbd_ | rpm | Legacy+ | duty cycle, load |
| Coolant temperature | _tbd_ | °C | Legacy+ | ambient temp, load, runtime, climate |
| Oil pressure | _tbd_ | kPa | Legacy+ | RPM, wear, oil temp |
| Runtime hours | n/a | h | Legacy+ | accumulates over time |
| Engine load | _tbd_ | % | Mid+ | duty cycle, terrain grade |
| Fuel rate | _tbd_ | L/h | Mid+ | load · RPM |
| Intake / boost pressure | _tbd_ | kPa | Mid+ | load, altitude |
| EGT (exhaust gas temp) | _tbd_ | °C | Modern+ | load, altitude, after-treatment state |
| DEF level | _tbd_ | % | Modern+ | runtime, consumption rate |
| Vibration | _tbd_ | mm/s | Modern+ | load, **terrain roughness**, bearing wear |
| Equipment age | n/a | days | always | fixed per unit (build year) |

> The **cross-signal correlations** (their signs and rough strengths) are the
> credibility of the dataset. They are documented here, implemented in one place,
> and **asserted in tests** so they can never silently drift:
> - fuel rate ↑ with load·RPM
> - coolant temp ↑ with ambient + load; bounded by thermostat regulation
> - oil pressure ↓ as RPM idles and ↓ with wear/high oil temp
> - EGT ↑ at altitude (thinner air) and under sustained high load
> - vibration ↑ with terrain roughness and accumulated bearing wear

---

## 6. Environment effects (thermal + wear + terrain)

Environment is what makes an **international** fleet visibly diverse — and what a
future drift demo (the 4th vitrine) will shift. Each region carries documented,
seeded modifiers grounded in **public** climate and infrastructure data:

- **Thermal (climate).** Ambient temperature curve, humidity, and **altitude** per
  region shift coolant/oil temperature baselines, fuel efficiency, and EGT
  (thinner air at altitude → higher EGT, lower available power).
- **Wear (climate).** Hot + dusty + humid environments **accelerate** wear hazards:
  oil degradation, filter loading, thermal cycling. This is a hazard modifier, not
  just a baseline shift.
- **Terrain / road quality.** Public road-quality, roughness, and grade data per
  region drives a **mechanical wear** channel: rough terrain raises vibration and
  accelerates suspension/structural/bearing degradation; steep grade raises
  sustained engine load. Smooth highway contracts wear differently than off-road
  earthworks.

All modifiers are documented (source + direction + rough magnitude), seeded, and
testable. MVP may ship a small set of contrasting environments; F5 broadens them.

**MVP regions (shipped in F2, ADR-014).** Four contrasting deployments of the
fictional operator, each pinned to a **named public source class** (the `source`
string travels in the `regions` dimension table of every dataset):

| Region | Climate grounding (public) | Terrain grounding (public) | Effect |
|---|---|---|---|
| **arid_highland** | Köppen **BWk** arid-highland normals (hot, dusty, ~2400 m) | IRI "unpaved/poor" band (~8–12 m/km) | high wear (heat+dust), high EGT at altitude |
| **temperate_lowland** | Köppen **Cfb** temperate-oceanic normals (mild, ~120 m) | IRI "good paved" band (~2–4 m/km) | gentlest baseline + lowest wear |
| **tropical_humid** | Köppen **Af** tropical-rainforest normals (hot, wet, ~200 m) | IRI "off-road/very poor" band (>12 m/km) | high wear (humidity+rough off-road) |
| **cold_continental** | Köppen **Dfb** cold-continental normals (cold winters, ~600 m) | IRI "fair paved" band (~4–6 m/km) | thermal-cycling hazard, mixed terrain |

**Tier-2 broadens this to six regions (shipped in F5, ADR-018)** — two more
contrasting deployments, same public-grounding rule:

| Region | Climate grounding (public) | Terrain grounding (public) | Effect |
|---|---|---|---|
| **hot_desert_lowland** | Köppen **BWh** hot-desert normals (extreme heat, ~80 m) | IRI "poor unsealed" band (~6–9 m/km) | harshest thermal/filter load |
| **alpine_subarctic** | Köppen **Dfc** subarctic normals (severe cold, ~3000 m) | IRI "rough mountain track" band (~8–11 m/km) | deep-cold starts + thin air + rough terrain |

These are **documented plausibility from public climate-type / road-roughness
references for a fictional operator** — never values copied from any private log
(the ADR-011 private-boundary note holds). Concrete constants live in the config
catalog (`src/can_telemetry_forge/config.py`).

**Seasons (shipped in F5, ADR-018).** On top of each region's own curve, a run
carries a named **season** — a configurable anomaly that moves the whole fleet's
ambient baseline and tilts its hazards. The neutral `baseline` is the default; the
others (`heatwave`, `cold_snap`, `wet_season`) are documented public-climate-anomaly
classes and are the knob a future **drift demo** (the 4th vitrine) shifts. A season
sets an `ambient_delta_c`, a `wear_mult`, and per-failure-mode hazard multipliers;
it is recorded in `manifest.json`.

---

## 7. Failure label — multi-mode (Tier 1)

The prediction target is **`failure_within_h`**, but failures are **not one thing**.
The generator models several **distinct failure modes**, each with its own signal
signature and its own hazard, so a downstream model has something real to learn and
discriminate:

| Mode | Signature it builds toward | Driven up by |
|---|---|---|
| **Overheat** | sustained high coolant/EGT, climbing oil temp | hot climate, high load, cooling degradation |
| **Oil starvation** | falling oil pressure under load, rising oil temp | wear, runtime, thermal stress |
| **Bearing / mechanical wear** | rising vibration, secondary temp creep | terrain roughness, runtime, age |

Each mode has a **documented hazard** that rises with accumulated wear/age **and**
sustained abnormal signal conditions, modified by the unit's environment. The label
records both the **horizon** (`failure_within_h`, with `h` configurable) and the
**mode** (so consumers can do per-mode evaluation). Hazard → event sampling is
seeded.

**Tier-2 hazard modifiers (F5, ADR-018).** Each mode's hazard is further scaled by a
per-mode multiplier = the unit's **equipment-model** reliability × the run's
**season**, combined multiplicatively. A failure-prone make in a heatwave fails
sooner than a robust make in a mild baseline — still derived in this one place.

**Derived in exactly one place** so the generator and any downstream consumer agree
on the ground truth.

---

## 8. Anomalies & faults (labeled — F3 + F6, shipped)

Every injected defect carries ground-truth labels so downstream QA/anomaly work is
**verifiable** (recover the injection from the labels). The injectors form a
**declarative registry** (ADR-016) — each defect is one self-describing
`AnomalyInjector` the orchestrator runs with mutual-exclusion eligibility, so at
most one defect lands per (signal, timestamp) cell and era-`NULL` cells are never
targeted. Labels surface as **one open-vocabulary categorical** (`anomaly_type`) +
`anomaly_signal`, with `is_outlier` kept as a value-distortion rollup.

**Value-domain & sensor families (F3)** — each a configurable `anomaly_rates[...]`
knob:

- **`obvious_outlier`** (was the F2 slice): out-of-range spike, impossible on its
  own — the easy univariate case.
- **`joint_outlier`**: each column stays in its own valid range but the **pair** is
  impossible (high fuel rate with near-zero load; hot coolant with the engine at
  idle/off; boost with no load). Only a *contextual* check catches it.
- **Sensor faults**, segment-based (a contiguous degradation episode, not per-cell
  salt), *distinct from* the structural era-NULLs of §4 — a healthy-capable channel
  going bad:
  - **`sensor_stuck`** — frozen at one value over the segment.
  - **`sensor_drift`** — a slow accumulating bias over the segment.
  - **`sensor_dropout`** — the channel goes `NULL` over the segment.

**CAN-frame faults (Tier 3, F6 — shipped, ADR-019).** The corruption class that only
exists once a signal is encoded as an **actual J1939 frame**. ADR-013 recorded each
signal's PGN inert; F6 completes it with a `FrameLayout` (byte/bit placement +
scaling/offset) and a **frame-level encoder/decoder** (`signals/frames.py`). Each
fault encodes the unit's value to its frame, corrupts the **bytes**, and **decodes
back** into the engineering column — exactly what a real receiver would observe — so
the dataset stays decoded (no schema change) and the byte-level truth is optionally
emitted to a `can_frames` side table (`--emit-raw-frames` / `emit_raw_frames`). Four
new `anomaly_type` *values* (ADR-016 — no new column):

- **`can_frame_corrupt`** — a payload byte flips → the field decodes to an
  implausible value (value-distorting).
- **`can_frame_stale`** — a frame is re-sent over a segment → the decoded value
  freezes; a **transport** fault, distinct from `sensor_stuck` (value-distorting).
- **`can_frame_error_indicator`** — the field carries the J1939 error / "not
  available" code → decodes to `NULL`.
- **`can_frame_truncated`** — a short DLC drops the field's bytes → decodes to `NULL`
  (distinct from era-NULL and `sensor_dropout`).

J1939 conventions modeled: little-endian fields, the all-ones "not available" code
and the top-of-range error indicator both decode to `NULL`, frames are ≤8 bytes with
`0xFF` idle fill. The codec **round-trips** every documented signal within one
quantum (tested); the value generators still don't read the layout (the ADR-013
inert-PGN invariant holds, tested).

---

## 9. Diversity (Tier 2 — shipped, F5)

Tier-2 is implemented as **declarative catalog entries that resolve to
multipliers/offsets** over the existing pipeline — no new readings-schema columns
(ADR-018).

- **Regions / climate / terrain** ✅: the §6 modifiers, broadened to **six**
  contrasting international environments (two new in F5).
- **Equipment models** ✅: each `EquipmentModel` carries **per-mode failure-hazard
  multipliers** and small **baseline signature offsets** (so one class hosts a
  robust and a failure-prone make), plus an optional **per-model capability floor**
  (`build_year_min`) — a first step toward the per-model SPN whitelist of §4.
  Surfaced as an `equipment_models` dimension table + `units.model_id`.
- **Seasonality** ✅: a named, configurable **season** (`heatwave` / `cold_snap` /
  `wet_season`, on top of `baseline`) shifting ambient + wear + per-mode hazards —
  the knob a future **drift demo** shifts (§6).
- **Intentionally richer than "Brazilian states"**: a fictional international
  operator with genuinely distinct regional climates, terrains, contracts, and
  equipment makes.

The model × season hazard multipliers **compose multiplicatively** into the single
per-mode factor `derive_unit_labels` applies (§7), so the failure label stays
derived in one place.

---

## 10. Output schema

Tidy **long** tables (one row per unit-timestamp-reading) + **dimension tables**
(units, models, regions/contracts) + **label tables**. Era-gated signals are NULL
where unsupported (§4). Emitted to **Parquet / CSV / DuckDB**.

- **Time resolution is configurable** (`1s` / `1min` / `5min`), **MVP default
  `1min`** — the typical telemetry-platform cadence. 1-second is downsampled from
  J1939's faster native rates; coarser resolutions aggregate.
- **Scale is configurable** (`--units`, `--days`, `--seed`), with a **medium-leaning
  default** (on the order of ~100 units × ~90 days) so a generated dataset has
  enough failures to actually train the future model, while still running locally
  and fitting CI for the small test profile.

A committed **`docs/DATA_DICTIONARY.md`** documents every field, its unit, its
J1939 SPN where applicable, and its capability era.

---

## 11. Reproducibility

Everything regenerates from **config + seed**. Same seed → identical data (fleet,
signals, environment draws, hazard events, injected faults). No global randomness;
a single seeded generator is threaded through every layer.

---

## 12. Resolved design decisions (from the co-writing session)

These are settled; remaining specifics get committed during F1/F2.

- **Signal set:** engine-core + drivetrain extras (boost, EGT, DEF, vibration),
  gated by capability era.
- **Domain strength = fleet composition + environment**, not raw signal logs.
- **CAN capability by model-year era**; unsupported signal = NULL, never zero.
- **Fleet grounded on public data + documented plausibility** (fictional operator).
- **Environment = thermal + wear + terrain/road-quality** modifiers (public-sourced).
- **Time resolution configurable**, default `1min`.
- **Failure label multi-mode** (overheat / oil-starvation / bearing-wear).
- **Scale configurable**, medium-leaning default.

## Still open

- ~~Exact per-SPN J1939 ranges/scaling and the SPN-per-era table~~ → done (F1,
  `DATA_DICTIONARY.md`).
- ~~The concrete vehicle-mix, age-curve, and units-per-contract distributions~~ →
  done (F2, config catalog: 5-class mix, triangular age curve with a legacy tail,
  per-contract sizes drawn around an expected value).
- ~~Which public regional/climate/road-quality sources to cite~~ → done (F2,
  ADR-014: Köppen climate types + IRI road-roughness bands; see §6).
- ~~Which public CAN/OBD/J1939 dataset to validate distributions against (license
  check — F4)~~ → done (F4, ADR-017): the **Vehicle Energy Dataset** (Kaggle,
  CC-BY 4.0), opt-in `forge validate --dataset ved`, fetched at run time, never
  committed; offline `in_spec`/`golden` adapters always run.
- Finer per-region climate normals / per-model SPN whitelists (Tier 2 — F5).
