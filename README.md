<p align="center">
  <img src="assets/logo.png" alt="can-telemetry-forge" width="440">
</p>

<h1 align="center">can-telemetry-forge</h1>

<p align="center"><em>Synthetic heavy-equipment telemetry, grounded in the J1939 standard — realistic predictive-maintenance data you can regenerate from a seed.</em></p>

<p align="center">
  <img src="https://img.shields.io/badge/status-F4%20%E2%80%94%20validated%20distributions-success" alt="Status: F4 — validated distributions">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/data-100%25%20synthetic-blueviolet" alt="100% synthetic data">
  <img src="https://img.shields.io/badge/grounded-SAE%20J1939%20%2B%20physics-teal" alt="Grounded in SAE J1939 + physics">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
</p>

A generator of **synthetic heavy-equipment CAN Bus telemetry** for
**predictive-maintenance** datasets. It models a *realistically composed* fleet —
machinery mix, age curve and regional deployment — emitting correlated
engine/sensor signals over time, injects a registry of **labeled** anomalies
(obvious + joint/contextual outliers and stuck/drift/dropout sensor faults), derives
a **multi-mode failure label**, and writes tidy tables (Parquet / CSV / DuckDB)
ready for any downstream machine-learning or data-quality work.

**The data is the product.** The model that consumes it can be deliberately
boring — the point is a dataset that is *diverse, statistically credible, and
fully reproducible*, so the pipeline around it (training, monitoring, drift
detection) has something real to work on.

> ✅ **Honest status — the MVP (Tier 1) ships.** One command generates a complete,
> reproducible dataset: a realistically composed fleet (vehicle-class mix, age curve
> with a legacy tail, regional deployment) of units emitting the 11 J1939-grounded
> signals over time — gated by CAN capability era (unsupported signals are `NULL`,
> never zero) — with a **multi-mode failure label**, a **registry of labeled
> defects** (obvious + joint/contextual outliers and stuck/drift/dropout sensor
> faults, each recoverable from an `anomaly_type` label), and tidy Parquet / CSV /
> DuckDB tables plus a manifest and a generated data dictionary. Same config + seed →
> byte-identical output, and `forge validate` reports the distributions as plausible
> (in-spec + drift-free offline, with an opt-in CC-BY real-data overlap). Still
> building phase by phase (see [`docs/ROADMAP.md`](docs/ROADMAP.md)): Tier-2
> diversity — more regions, equipment models, and seasons — shipped (F5); Tier-3
> CAN-frame faults remain (F6).

## Why it's credible (and clean-room)

The signal model is grounded in the **publicly documented SAE J1939 standard** —
the heavy-duty CAN application layer — using its published PGN/SPN structure,
value ranges, units and scaling. Each generated field carries its real SPN (engine
speed 190, coolant temp 110, oil pressure 100, engine load 92, fuel rate 183, boost
102, EGT 173, DEF 1761, …), unit and operating range in the committed
[data dictionary](docs/DATA_DICTIONARY.md). The relationships *between* signals
(fuel rate tracking load and RPM, coolant temperature responding to ambient and
load, EGT rising at altitude, vibration rising with terrain and wear) come from
**documented physics**, not from any proprietary log — and their **signs are
asserted in tests** so they can't silently drift.

- **No real telemetry is shipped or used as a seed.** A permissively-licensed
  public CAN/OBD dataset is used **only to validate** that the generated
  distributions look plausible — the **Vehicle Energy Dataset** (Kaggle,
  **CC-BY 4.0**), fetched at validation time and **never committed** (`forge
  validate --dataset ved`; see [F4](#validating-the-data-f4) and ADR-017).
- **Reproducible by construction.** Every dataset regenerates from a config file +
  a fixed seed. Same seed → identical data.
- **Clean room.** Built from the standard and known physics; contains no
  proprietary code or data.

## What makes it different

A few realism choices set it apart from a generic random-signal generator (full
rationale in [`docs/DECISIONS.md`](docs/DECISIONS.md)):

- **Two-layer realism.** A *fleet-composition* layer (operator → regions →
  contracts → units, with realistic machinery mix, age curve and units per
  contract) sits under the J1939 *signal* layer. Credibility comes from both, not
  from any single real log.
- **CAN capability gated by model-year era.** Older units only expose the SPNs
  their bus actually supported — unsupported signals are emitted as **`NULL`, never
  zero**. Structural missingness a downstream model has to handle, the way real
  mixed-age fleets behave.
- **Multi-mode failures.** Distinct failure modes (overheating, oil starvation,
  bearing/mechanical wear) each build their own signal signature, so the prediction
  target is genuinely learnable and per-mode evaluable.
- **Environment that wears the machine.** Per-region **thermal + wear + terrain /
  road-quality** modifiers (grounded in public data) shift signal baselines *and*
  accelerate failure hazards — the seam a future drift demo shifts.

## What it generates

The pipeline below is live end to end (CAN-frame fault patterns are the remaining
Tier-3 item, F5):

```
config (fleet, regions, climate, terrain, season, anomaly rates, resolution, seed)
   └─► fleet composition  operator → contracts → units (model, build year, duty)
        └─► signal model   J1939-grounded per-signal generators + correlations,
        │                  gated by capability era (unsupported SPN → NULL)
        └─► fleet sim      units over time at configurable resolution; thermal /
             │             wear / terrain modifiers per region
             └─► faults     registry of labeled defects → anomaly_type: obvious ·
                  │         joint/contextual outliers · sensor stuck / drift / dropout
                  └─► label  multi-mode failure_within_h (overheat / oil / bearing)
                       └─► tidy tables → Parquet / CSV / DuckDB + data dictionary
```

The entry point is a single command:

```bash
pip install -e .

# Generate the bundled default fleet (~134 units × 90 days) to Parquet:
forge generate --out out/

# Or point at a config, pick a seed, format and a smaller window:
forge generate --config configs/fleet.json --seed 42 --format duckdb \
  --days 30 --resolution 5min --out out/

# Tier-2: apply a seasonal anomaly (the knob a future drift demo shifts):
forge generate --season heatwave --out out/
```

This writes the tidy `readings` table — signals plus the labels
`failure_within_h` / `failure_mode` and `anomaly_type` / `anomaly_signal` (with an
`is_outlier` rollup) so every injected defect is recoverable — plus `units` /
`vehicle_classes` / `equipment_models` / `regions` / `contracts` dimension tables, a
`manifest.json` (provenance + run parameters + per-type defect counts + the run's
season), and a generated `dataset_dictionary.md`. The default config in
[`configs/fleet.json`](configs/fleet.json) is a fictional international operator
whose regions are pinned to **cited public climate-type + road-roughness sources**
(see [`docs/DATA_DESIGN.md`](docs/DATA_DESIGN.md) §6) — never any private data.
Everything the CLI does is callable as a library (`config → sim.simulate →
io.write_dataset`), so the future MLOps repo can import it directly.

## Validating the data (F4)

`forge validate` checks that the generated distributions are **plausible** and emits
a self-contained Markdown report. It runs two **offline** reference adapters by
default — so it needs no network and is reproducible by anyone:

- **`in_spec`** — every value sits inside its documented SAE J1939 range.
- **`golden`** — per-signal summary stats match a pinned, *recomputed* reference run
  (catches silent drift in the generator itself — nothing is committed).

```bash
# Offline plausibility report to stdout (or --report report.md):
forge validate --seed 42

# Opt into a real-data comparison (Vehicle Energy Dataset, CC-BY 4.0):
pip install -e '.[validate]'
forge validate --seed 42 --dataset ved --report report.md

# Point at a different Kaggle VED mirror if you like:
forge validate --dataset ved --ved-handle owner/slug
```

The optional `ved` adapter overlaps the shared engine channels (engine RPM, engine
load) against the **[Vehicle Energy Dataset](https://www.kaggle.com/datasets/yashseth25/ved-segregated)**
(Kaggle, **CC-BY 4.0**), **fetched at run time and never committed**. VED is
light-vehicle OBD-II, so the overlap is a *plausibility sanity-check on shared
channels, not an equivalence claim* — stated plainly in the report. A live run gives
a histogram-intersection overlap of **~0.48 (engine RPM) / ~0.51 (engine load)**
against 200k VED rows. CI never requests it and the offline checks always stand on
their own (rationale in [ADR-017](docs/DECISIONS.md)).

**Auth for `--dataset ved`.** The fetch uses the classic Kaggle REST endpoint with
your **legacy** API credentials — put a `kaggle.json` (Kaggle → Settings → API →
*Create Legacy API Key*) at `~/.kaggle/kaggle.json`. The dataset handle is
configurable (`--ved-handle` / `FORGE_VED_HANDLE`), so a moved/renamed mirror is a
flag change, not a code edit. (Behind a TLS-inspecting proxy, e.g. some corporate
antivirus, install `pip-system-certs` so Python trusts the system certificate store.)

## Data tiers

Richness is sequenced so the repo ships fast and grows on a roadmap (full spec in
[`docs/DATA_DESIGN.md`](docs/DATA_DESIGN.md)):

- **Tier 1 (MVP):** one fleet with realistic composition, core J1939 signals gated
  by capability era, a multi-mode failure label, deliberate bad data and obvious
  labeled outliers.
- **Tier 2 (shipped in F5):** six contrasting public-grounded regions/contracts, a
  catalog of **equipment models** with distinct reliability + signature profiles
  (per-mode hazard multipliers, baseline offsets, optional capability floor), and
  configurable **seasons** (`heatwave` / `cold_snap` / `wet_season`) — the knob a
  future drift demo shifts.
- **Tier 3:** joint/contextual outliers and stuck/drift/dropout sensor faults
  (shipped in F3); **CAN-frame** fault patterns remain for F6 (they need the
  frame-level encoder).

## Roadmap

| Phase | What |
|------|------|
| **F0** | Foundations & runnable skeleton (package, CLI, CI) ✅ |
| **F1** | J1939-grounded signal model + data dictionary ✅ |
| **F2** | Fleet simulator + Parquet/CSV/DuckDB writers — **Tier 1 ships (MVP)** ✅ |
| **F3** | Labeled anomaly & sensor-fault injection (declarative injector registry) ✅ |
| **F4** | Distribution validation vs a license-checked public dataset (offline in-spec/golden + opt-in CC-BY VED overlap) ✅ |
| **F5** | Diversity (Tier 2): more regions + equipment models + seasons ✅ |
| **F6** | CAN-frame faults (Tier 3) + the frame-level encoder they need |

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for objectives and definitions of done,
and [`docs/DECISIONS.md`](docs/DECISIONS.md) for the design rationale (ADRs).

## Project context

This is a public, clean-room portfolio project — part of a pair: a future MLOps
project will consume this generator as its data source (experiment tracking, model
registry, serving, drift monitoring on top of the telemetry produced here).

## License

[MIT](LICENSE) © 2026 Jorge Ribeiro
