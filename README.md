<p align="center">
  <img src="assets/logo.png" alt="can-telemetry-forge" width="440">
</p>

<h1 align="center">can-telemetry-forge</h1>

<p align="center"><em>Synthetic heavy-equipment telemetry, grounded in the J1939 standard — realistic predictive-maintenance data you can regenerate from a seed.</em></p>

<p align="center">
  <img src="https://img.shields.io/badge/status-F2%20MVP%20%E2%80%94%20Tier%201%20ships-success" alt="Status: F2 MVP — Tier 1 ships">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/data-100%25%20synthetic-blueviolet" alt="100% synthetic data">
  <img src="https://img.shields.io/badge/grounded-SAE%20J1939%20%2B%20physics-teal" alt="Grounded in SAE J1939 + physics">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
</p>

A generator of **synthetic heavy-equipment CAN Bus telemetry** for
**predictive-maintenance** datasets. It models a *realistically composed* fleet —
machinery mix, age curve and regional deployment — emitting correlated
engine/sensor signals over time, injects **labeled** anomalies and sensor faults,
derives a **multi-mode failure label**, and writes tidy tables (Parquet / CSV /
DuckDB) ready for any downstream machine-learning or data-quality work.

**The data is the product.** The model that consumes it can be deliberately
boring — the point is a dataset that is *diverse, statistically credible, and
fully reproducible*, so the pipeline around it (training, monitoring, drift
detection) has something real to work on.

> ✅ **Honest status — the MVP (Tier 1) ships.** One command generates a complete,
> reproducible dataset: a realistically composed fleet (vehicle-class mix, age curve
> with a legacy tail, regional deployment) of units emitting the 11 J1939-grounded
> signals over time — gated by CAN capability era (unsupported signals are `NULL`,
> never zero) — with a **multi-mode failure label**, **labeled obvious outliers**,
> and tidy Parquet / CSV / DuckDB tables plus a manifest and a generated data
> dictionary. Same config + seed → byte-identical output. Still building phase by
> phase (see [`docs/ROADMAP.md`](docs/ROADMAP.md)): subtle/joint outliers and sensor
> faults (F3), distribution validation against a public dataset (F4), and Tier-2/3
> diversity (F5).

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
  public CAN/OBD dataset may be used **only to validate** that the generated
  distributions look plausible (license verified first, fetched at validation
  time, never committed) — see [`docs/ROADMAP.md`](docs/ROADMAP.md) F4.
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

## What it generates (target)

```
config (fleet, regions, climate, terrain, season, anomaly rates, resolution, seed)
   └─► fleet composition  operator → contracts → units (model, build year, duty)
        └─► signal model   J1939-grounded per-signal generators + correlations,
        │                  gated by capability era (unsupported SPN → NULL)
        └─► fleet sim      units over time at configurable resolution; thermal /
             │             wear / terrain modifiers per region
             └─► faults     labeled outliers + sensor faults (stuck / drift / dropout)
                  └─► label  multi-mode failure_within_h (overheat / oil / bearing)
                       └─► tidy tables → Parquet / CSV / DuckDB + data dictionary
```

The entry point is a single command:

```bash
pip install -e .

# Generate the bundled default fleet (~106 units × 90 days) to Parquet:
forge generate --out out/

# Or point at a config, pick a seed, format and a smaller window:
forge generate --config configs/fleet.json --seed 42 --format duckdb \
  --days 30 --resolution 5min --out out/
```

This writes the tidy `readings` table plus `units` / `vehicle_classes` /
`regions` / `contracts` dimension tables, a `manifest.json` (provenance + run
parameters), and a generated `dataset_dictionary.md`. The default config in
[`configs/fleet.json`](configs/fleet.json) is a fictional international operator
whose regions are pinned to **cited public climate-type + road-roughness sources**
(see [`docs/DATA_DESIGN.md`](docs/DATA_DESIGN.md) §6) — never any private data.
Everything the CLI does is callable as a library (`config → sim.simulate →
io.write_dataset`), so the future MLOps repo can import it directly.

## Data tiers

Richness is sequenced so the repo ships fast and grows on a roadmap (full spec in
[`docs/DATA_DESIGN.md`](docs/DATA_DESIGN.md)):

- **Tier 1 (MVP):** one fleet with realistic composition, core J1939 signals gated
  by capability era, a multi-mode failure label, deliberate bad data and obvious
  labeled outliers.
- **Tier 2:** multiple regions/contracts with climate, terrain and seasonal
  effects, multiple equipment models with distinct failure profiles.
- **Tier 3:** subtle/joint outliers and sensor/CAN-fault patterns.

## Roadmap

| Phase | What |
|------|------|
| **F0** | Foundations & runnable skeleton (package, CLI, CI) ✅ |
| **F1** | J1939-grounded signal model + data dictionary ✅ |
| **F2** | Fleet simulator + Parquet/CSV/DuckDB writers — **Tier 1 ships (MVP)** ✅ |
| **F3** | Labeled anomaly & sensor-fault injection |
| **F4** | Distribution validation vs a license-checked public dataset |
| **F5** | Diversity (Tier 2) + richer faults (Tier 3) |

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for objectives and definitions of done,
and [`docs/DECISIONS.md`](docs/DECISIONS.md) for the design rationale (ADRs).

## Project context

This is a public, clean-room portfolio project — part of a pair: a future MLOps
project will consume this generator as its data source (experiment tracking, model
registry, serving, drift monitoring on top of the telemetry produced here).

## License

[MIT](LICENSE) © 2026 Jorge Ribeiro
