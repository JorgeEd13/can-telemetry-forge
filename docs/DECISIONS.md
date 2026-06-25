# Decisions (ADRs) — can-telemetry-forge

Architecture Decision Records. One entry per non-obvious choice: context →
decision → consequences. Newest at the bottom.

> These ADRs are the *plan-stage* decisions taken with the user before scaffolding.
> Implementation-stage ADRs (CLI lib, file formats, etc.) get appended as phases land.

---

## ADR-001 — The data is the product; MLOps is a separate, later vitrine

**Context.** The original brief was a "light MLOps" vitrine to close the MLOps
gate. While scoping the synthetic data the model would need, it became clear that a
realistic, standards-grounded telemetry generator is itself a strong, rarer
showcase — and that a great generator would otherwise be buried as a module inside
an ML repo.

**Decision.** Split: **this** repo (`can-telemetry-forge`) is the 3rd vitrine and
its product is the **synthetic data generator**. The MLOps vitrine becomes the
**4th** project and imports this generator as its data source.

**Consequences.** Two public repos that compose into one narrative ("built the data
engine, then the production ML on top"). The MLOps gate is deferred, not dropped.
This repo must stand alone (its own README, tests, CI) and expose a clean library
API for the future consumer.

---

## ADR-002 — Domain: heavy-equipment predictive maintenance

**Context.** Needed a domain that is recruiter-legible, close to the user's real
expertise, and where a drift story (for the future MLOps repo) is natural.

**Decision.** Heavy-equipment fleet telemetry with a predictive-maintenance
framing. Adjacent to the user's real fleet domain but with **zero** private / GPS /
the employer data.

**Consequences.** Domain depth is showable; drift is naturally demonstrable
downstream (sensors degrade, climate shifts). Requires care to stay clean-room.

---

## ADR-003 — Provenance: J1939 standard + physics, not a real-log seed

**Context.** "Grounding in reality" is tempting via a real CAN dataset, but public
CAN datasets are often license-restricted and shipping/seeding from them breaks
clean-room and risks implying the output is real telemetry.

**Decision.** Ground the signal model in the **publicly documented SAE J1939
standard** (PGN/SPN ranges, units, scaling) plus **documented physical
relationships**. Cite these in the README. A permissively-licensed public dataset
is used **only to validate** generated distributions (F4), license verified first,
fetched at run time, never committed, never used as a seed.

**Consequences.** Provenance is fully citable and more defensible than "found a
CSV". Output is honestly synthetic. Adds a license-check step before any external
dataset is touched.

---

## ADR-004 — Tiered data richness; Tier 1 is the MVP

**Context.** The user's vision (multi-region, climate, equipment models,
seasonality, CAN-fault patterns, subtle joint outliers) is excellent but could
balloon into an infinite data-sim project and bury the showcase.

**Decision.** Three tiers. **Tier 1** (one fleet, core J1939 signals, age/wear
failure label, deliberate bad data + obvious labeled outliers) is the **MVP**.
Tiers 2 (regions/climate/models/seasonality) and 3 (subtle/joint outliers, sensor
& CAN faults) are fully specced in `DATA_DESIGN.md` as named later phases (F5).

**Consequences.** Ships a navigable link fast; richness grows on a roadmap; nothing
from the vision is lost — it is sequenced. Matches the disciplined scope of the
prior two vitrines.

---

## ADR-005 — Determinism: a single seeded generator threaded through

**Context.** A synthetic-data repo's credibility depends on reproducibility; ad-hoc
global randomness makes datasets irreproducible and tests flaky.

**Decision.** All randomness flows from one seeded generator built from the config
and passed down every stage. No module calls a global random source.

**Consequences.** Same seed → identical data; tests can assert exact
reproducibility; the dataset is regenerable by anyone from `config + seed`.

---

## ADR-006 — Labeled anomaly/fault injection (every defect is recoverable)

**Context.** Injected outliers/faults are only useful downstream if their ground
truth is known (for supervised anomaly/QA work and for honest evaluation).

**Decision.** Every injected anomaly or sensor/CAN fault writes a ground-truth
label (column/table). The injection rate is configurable; the defect is always
recoverable from labels.

**Consequences.** The dataset supports supervised anomaly detection and verifiable
QA. Tests assert each defect type is present at its configured rate and fully
label-recoverable. (Detailed in F3.)

---

## ADR-007 — Two-layer realism: fleet composition + signal model

**Context.** The natural assumption was that "domain experience" means modeling the
telemetry signals from real logs. It does not — usable real telemetry is
effectively absent. The genuine domain strength is knowing **how a real operator is
composed and deployed**: machinery mix, fleet age curve, units per contract, which
region gets which vehicle, and how each environment wears the machine.

**Decision.** Model the dataset in **two grounded layers**: a **fleet-composition
layer** (operator → regions → contracts → units, with realistic mixes/age/duty) and
a **signal layer** (J1939-grounded per-signal model). Environment couples them
(climate/terrain shift baselines *and* failure hazards). Credibility comes from both
layers being independently defensible, not from any single real log.

**Consequences.** The showcase leads with a rarer strength (realistic fleet
structure) rather than competing on signal fidelity alone. The fleet layer's exact
proportions are grounded in **public** data + documented plausibility and filled
into the config catalog at build time, not guessed in the design doc.

---

## ADR-008 — CAN capability gated by model-year era

**Context.** Real machines only report the SPNs their electronics support; an older
unit's bus simply does not expose newer signals. Most synthetic CAN datasets ignore
this and emit a full uniform schema, which is both unrealistic and a missed
learning challenge.

**Decision.** Group model years into **capability eras** (e.g. Legacy / Mid /
Modern); each era exposes a defined SPN subset. A signal a unit's era does not
support is emitted as **NULL (missing), never zero**, and the schema documents which
signals are era-gated. MVP uses coarse eras; a per-model SPN whitelist is a Tier-2
(F5) refinement.

**Consequences.** Distinctive, realistic structural missingness that downstream
models must handle (not impute as a real reading). Couples to the fleet age curve
(ADR-007): an older fleet yields a sparser schema. Requires keeping era→SPN mapping
in the data dictionary as the single source of truth.

---

## ADR-009 — Multi-mode failure label (supersedes the age/wear label in ADR-004)

**Context.** ADR-004's Tier-1 sketch used a single age/wear failure label. A single
near-deterministic label gives a downstream model little to learn and no failure
signature to discriminate.

**Decision.** Model **several distinct failure modes** (overheat, oil-starvation,
bearing/mechanical wear), each with its own signal signature and its own
documented hazard rising with accumulated wear/age **and** sustained abnormal
conditions, modified by environment. The label records both the **horizon**
(`failure_within_h`, `h` configurable) and the **mode**, and is derived in exactly
one place. Hazard→event sampling is seeded.

**Consequences.** Richer, genuinely learnable target with per-mode evaluation
downstream; sets up a more interesting future model and drift story. More to model
and test than a single label, but still Tier-1-scoped. This replaces the single
age/wear label framing in ADR-004.

---

## ADR-010 — Environment modifiers grounded in public climate + terrain data

**Context.** An international operator's diversity should be more than cosmetic
baseline shifts. Environment genuinely changes how machines wear — and it must be
grounded without any private data.

**Decision.** Each region carries **seeded, documented modifiers** from **public**
sources: a **thermal** channel (ambient/humidity/altitude → coolant/oil/EGT
baselines and fuel efficiency), a **wear** channel (hot/dusty/humid → accelerated
oil/filter/thermal-cycling hazards), and a **terrain/road-quality** channel (public
roughness/grade data → vibration and suspension/structural/bearing wear, sustained
load on grade). Each modifier documents source, direction, and rough magnitude.

**Consequences.** Visible, defensible international diversity and a natural seam for
the future drift demo (shift a region's climate). Adds a dependency on citing public
regional/infrastructure sources (tracked as open in DATA_DESIGN §"Still open").

---

## ADR-011 — Configurable time resolution and fleet scale, with defaults

**Context.** Resolution and scale trade realism against file size, test speed, and
how many failures a dataset contains.

**Decision.** Make **time resolution** a config knob (`1s` / `1min` / `5min`),
default **`1min`** (typical telemetry-platform cadence; `1s` downsamples J1939's
faster native rates, coarser values aggregate). Make **fleet scale**
(`--units`/`--days`/`--seed`) configurable with a **medium-leaning default**
(~100 units × ~90 days) so a default run holds enough failures to train the future
model, while a small test profile stays CI-friendly.

**Consequences.** One command scales from a browsable demo to a trainable dataset.
Tests run on the small profile; the README documents both. More config surface to
validate.

> **Provenance note (private boundary).** The *plausibility intuition* behind fleet
> proportions may be informed privately by the author's real-world operational
> experience, but **no private data, numbers, or source is ever committed,
> documented, or exposed here** — the repo is grounded solely on the fictional
> operator + public sources. (Boundary recorded outside this repo.)

---

## ADR-012 — Signal model as a declarative registry of self-describing signals

**Context.** F1 needs per-signal generators. The obvious approach is constants and
correlations hard-coded inline across the generator functions. But the project's
long-run ambition (stated with the user at F1 kickoff) is for this engine to be
**reusable to generate other rich synthetic datasets**, possibly becoming the
late-stage objective. Inline constants optimise for a single fixed signal set and
make a different domain's signal set a cross-cutting rewrite.

**Decision.** Make the signal set a **declarative registry** (`signals/spec.py`):
each signal is a frozen `SignalSpec` carrying its own metadata (name, SPN, unit,
range, capability era, **driver list**) — data, not behaviour. The deterministic
generators and the era gate read the registry; `DATA_DICTIONARY.md` mirrors it.
What generalises is the *shape* — a signal = `(drivers, state, seeded rng) →
values` plus its metadata — not a table of tunable coefficients (which would only
vary magnitudes of a fixed structure). Magnitudes stay as named constants in the
generators, to be refined in F5 without touching the dependency structure.

**Consequences.** Adding/removing a signal — or, later, describing a different
domain — is a local edit to one spec + its generator, not a scattered change. The
`drivers` field doubles as the dependency graph the simulator orders by. Correlation
**signs** (not magnitudes) are asserted in tests, so refinement can't break the
contract while the physics direction holds.

---

## ADR-013 — Record J1939 PGNs now, keep them inert until a frame-level encoder

**Context.** Each Tier-1 SPN belongs to a J1939 Parameter Group (PGN). The MVP
emits **engineering-unit time-series**, not raw CAN frames, so the PGN (and the
byte/bit layout within it) is not needed to generate values. But re-researching the
standard later to add frame-level output would be wasted effort.

**Decision.** Capture each J1939 signal's **PGN in the registry now**, but leave it
**inert** (unused in generation) — "disabled by default", per the user's call at F1.
Byte/bit layout is deliberately *not* modelled yet; the PGN field is the seam a
future raw-frame encoder switches on. A test asserts PGNs are recorded but the
generator does not depend on them.

**Consequences.** The standards grounding is captured at the moment it's researched,
at near-zero cost, without adding frame-encoding complexity to the MVP. When a
frame-level output mode is wanted (noted in DATA_DICTIONARY "Not yet in Tier 1"),
the PGN is already there.

---

## ADR-014 — Regions grounded in cited public climate + road-quality sources now

**Context.** ADR-010 set environment modifiers (thermal/wear/terrain) as the
realism lever and flagged the concrete regional constants as "still open". For F2
the choice was: ship fictional archetype numbers now and cite real sources later
(F5), or pin each region to a named public source class immediately.

**Decision.** Pin the MVP regions to **named public source classes now**: each
region's climate constants are documented plausibility from a public **Köppen
climate type** (e.g. BWk arid-highland, Cfb temperate-oceanic, Af tropical,
Dfb cold-continental), and its terrain roughness from a public **International
Roughness Index (IRI)** road-quality band. The `source` string travels *in the
data* (the `regions` dimension table) and is traced in DATA_DESIGN §6. The operator
remains **fictional**; the numbers are public-grounded plausibility, not values
copied from any private log (the private-boundary note in ADR-011 still holds).

**Consequences.** Provenance is defensible at MVP, not deferred — a reader can see
*why* a region's baselines are what they are, and the citation ships with every
dataset. F5 still broadens the set and can move to finer per-region normals.

---

## ADR-015 — Config is JSON (stdlib), not YAML

**Context.** The generator is config-driven. The README sketch used `fleet.yaml`,
but YAML needs a third-party parser (PyYAML), which would be a new core dependency
purely for config ergonomics — against the "lean core + lean CI" principle.

**Decision.** Use **JSON** config files, parsed with the standard library. A config
file overrides any subset of the bundled default (nested fleet keys merge), so a
small file can tweak just `seed`/`days`. The bundled `default_config()` is a
complete, runnable fleet, so `--config` is optional.

**Consequences.** Zero added dependencies; config loads with stdlib; CI stays lean.
Cost is JSON's lack of comments (mitigated with a `_comment` field in the shipped
`configs/fleet.json`). README/DATA_DESIGN updated from `.yaml` to `.json`.

---

## ADR-016 — Anomaly injection is a declarative registry; labels are one open-vocabulary categorical

**Context.** F3 implements the labeled-injection contract sketched in ADR-006. Two
new defect families join the F2 obvious-outlier slice — **joint/contextual
outliers** (each column in range, the *pair* impossible) and **sensor faults**
(stuck / drift / dropout, a healthy era-capable channel degrading over a segment,
distinct from the structural era-`NULL`s of ADR-008). Two design questions had to
be settled, both with the user, because they shape the **public dataset contract**
the downstream MLOps vitrine (ADR-001) will consume:

1. *How are the new defects wired in?* Hardcoded functions, or a structure?
2. *How are they represented in the schema?* Separate boolean columns per family,
   or one categorical?

The deciding lens for both was the project's stated long-run ambition (same one
behind ADR-012): this engine should generalise into a **broader rich-data
generator**, not stay fleet-specific.

**Decision.**

*Injection is a declarative registry.* Each defect mechanism is a registered,
self-describing `AnomalyInjector` (`anomaly_type` tag + description + a pure,
seeded `inject` function), exactly mirroring `SignalSpec` (ADR-012). An
orchestrator (`apply_anomalies`) runs the registry over one unit's signals,
threading a per-signal **eligibility mask** that starts as "present for this era"
and shrinks as injectors claim cells — so **at most one defect lands per (signal,
timestamp) cell**, and era-`NULL` cells are never targeted. Adding a defect (or a
whole new domain's corruption) is a *local* edit: one injector + one registry
entry.

*Labels are one categorical, not N booleans.* The schema carries a single
`anomaly_type` column (`''` / `obvious_outlier` / `joint_outlier` / `sensor_stuck`
/ `sensor_drift` / `sensor_dropout`) plus `anomaly_signal` (which channel), and
keeps `is_outlier` as a back-compat **value-distortion rollup**. Rationale: the
families are **mutually-exclusive injected mechanisms** (a stuck channel is not
*also* a joint outlier), so booleans would buy a co-occurrence the generator never
produces while scattering one concept across columns. A single categorical is the
natural multiclass target/feature downstream, and — decisively for the
general-engine goal — it is a **closed schema with an open vocabulary**: new
mechanisms are new *values*, never new *columns* (no breaking schema change per
defect, in any domain). A row that carries defects on two different signals is
resolved to one label by **injector priority = registry order**, with the per-cell
truth still exactly recoverable from the signals + labels.

**Consequences.** The anomaly layer generalises the way the signal layer does;
defect types grow on a roadmap (Tier-3 CAN faults in F5) without schema churn.
Rates are per-type config (`anomaly_rates`, with the F2 `obvious_outlier_rate` kept
as a back-compat alias). `sensor_dropout` is the one family that blanks a value to
`NULL` rather than distorting it, so it is labeled in `anomaly_type` but **not** in
the `is_outlier` rollup — documented so the rollup stays meaningful. Sensor faults
are **segment-based** (contiguous episodes), which is how real transducers fail and
gives downstream models temporal structure to learn, unlike per-cell salt.

---

## ADR-017 — Distribution validation: a pluggable reference registry; offline always, VED opt-in (CC-BY 4.0, never committed)

**Context.** F4's job (ROADMAP) is to show the generated distributions are
*plausible* against real-world data **without shipping anyone's data** (ADR-003). Two
questions had to be settled with the user: **(1) against what reference?** and
**(2) how does the external dataset stay reproducible and CI-safe** given that any
real CAN/OBD dataset is license-encumbered and/or auth-gated?

A real-data comparison is the strongest "vs reality" story, but if `forge validate`
*requires* a network fetch it stops being reproducible-by-anyone and can't run in
CI. Conversely, an offline-only check can't claim resemblance to real telemetry. The
chosen public set — the **Vehicle Energy Dataset (VED)**, Kaggle, **CC-BY 4.0** — is
permissive and attributable but is **light-vehicle OBD-II, not heavy J1939**, so only
the engine-core channels (RPM, engine load, fuel rate, coolant temp) overlap.

**Decision.**

*Validation is a declarative registry of reference adapters* (`validation/`,
outside `src/` — the core never imports it), mirroring the signal/anomaly registries
(ADR-012/-016). Each adapter is self-describing (`name`, `description`, a `network`
flag, a `check` fn → per-signal comparisons + pass/fail checks). Three ship:

- **`in_spec`** (offline) — every non-NULL value must sit inside its documented
  J1939 range from the signal registry. Catches out-of-spec generation.
- **`golden`** (offline) — per-signal mean/std must match a **recomputed** pinned
  reference run (fixed seed/profile). The reference is *regenerated*, never stored as
  data (determinism, ADR-005), so nothing is committed; it catches silent drift in
  the generator itself.
- **`ved`** (network, opt-in) — histogram-intersection overlap of the overlapping
  engine channels vs VED, **fetched at run time via the Kaggle API and never
  committed** (the cache dir is git-ignored). Degrades to "reference unavailable"
  (never fakes a result) when offline or unauthenticated.

*The offline adapters always run; `ved` only on `--dataset ved`.* So `forge
validate` works with no network, is reproducible by anyone, and is CI-safe by
construction — CI never has Kaggle creds and never requests `ved`. The deliverable is
a self-contained Markdown report stating its own provenance.

The overlap metric is **histogram intersection** on a shared bin grid (`sum(min(p,
q))`): bounded `[0,1]`, symmetric, assumption-free, and explainable in one line for a
portfolio report — over a KS/EMD statistic whose magnitude needs interpretation.

**Consequences.** The "vs real data" claim is honest and bounded (VED overlap is a
plausibility sanity-check on shared channels, *not* an equivalence claim, since VED
isn't heavy-equipment J1939 — stated in the report). Adding a future reference (a
heavier-duty public set, a synthetic baseline) is a local registry entry, not a
rewrite. `kaggle` is a `validate`-extra dependency only; the core install and CI stay
lean. The clean-room invariant (ADR-003) is preserved end to end: no real data is
shipped, committed, or used as a seed — only fetched transiently to compare.
