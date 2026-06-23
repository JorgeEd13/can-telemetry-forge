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
