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
