<p align="center">
  <img src="assets/logo.png" alt="can-telemetry-forge" width="440">
</p>

<h1 align="center">can-telemetry-forge</h1>

<p align="center"><em>Synthetic heavy-equipment telemetry, grounded in the J1939 standard — realistic predictive-maintenance data you can regenerate from a seed.</em></p>

<p align="center">
  <img src="https://img.shields.io/badge/status-plan--stage-orange" alt="Status: plan stage">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/data-100%25%20synthetic-blueviolet" alt="100% synthetic data">
  <img src="https://img.shields.io/badge/grounded-SAE%20J1939%20%2B%20physics-teal" alt="Grounded in SAE J1939 + physics">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
</p>

A generator of **synthetic heavy-equipment CAN Bus telemetry** for
**predictive-maintenance** datasets. It simulates a fleet of equipment emitting
correlated engine/sensor signals over time, injects **labeled** anomalies and
sensor faults, derives a failure label, and writes tidy tables (Parquet / CSV /
DuckDB) ready for any downstream machine-learning or data-quality work.

**The data is the product.** The model that consumes it can be deliberately
boring — the point is a dataset that is *diverse, statistically credible, and
fully reproducible*, so the pipeline around it (training, monitoring, drift
detection) has something real to work on.

> ⚠️ **Honest status:** this repo is at the **planning stage**. The design,
> architecture and decisions are written ([`PLAN.md`](PLAN.md),
> [`docs/`](docs/)); the generator itself is being built phase by phase (see
> [`docs/ROADMAP.md`](docs/ROADMAP.md)). This README describes the target and
> will gain a real usage section as the MVP lands.

## Why it's credible (and clean-room)

The signal model is grounded in the **publicly documented SAE J1939 standard** —
the heavy-duty CAN application layer — using its published PGN/SPN structure,
value ranges, units and scaling for signals like engine RPM, coolant temperature,
fuel rate, engine load and oil pressure. The relationships *between* signals (fuel
rate tracking load and RPM, coolant temperature responding to ambient and load,
vibration rising with load and wear) come from **documented physics**, not from
any proprietary log.

- **No real telemetry is shipped or used as a seed.** A permissively-licensed
  public CAN/OBD dataset may be used **only to validate** that the generated
  distributions look plausible (license verified first, fetched at validation
  time, never committed) — see [`docs/ROADMAP.md`](docs/ROADMAP.md) F4.
- **Reproducible by construction.** Every dataset regenerates from a config file +
  a fixed seed. Same seed → identical data.
- **Clean room.** Built from the standard and known physics; contains no
  proprietary code or data.

## What it generates (target)

```
config (fleet, regions, climate, season, anomaly rates, seed)
   └─► signal model      J1939-grounded per-signal generators + correlations
        └─► fleet sim     N units (model, age) over time, regional/seasonal modifiers
             └─► faults    labeled outliers + sensor faults (stuck / drift / dropout)
                  └─► label failure_within_h derived from signals + wear + age
                       └─► tidy tables → Parquet / CSV / DuckDB + data dictionary
```

Once the MVP lands, the intended entry point is a single command:

```
forge generate --config configs/fleet.yaml --seed 42 --out out/
```

## Data tiers

Richness is sequenced so the repo ships fast and grows on a roadmap (full spec in
[`docs/DATA_DESIGN.md`](docs/DATA_DESIGN.md)):

- **Tier 1 (MVP):** one fleet, core J1939 signals, an age/wear-driven failure
  label, deliberate bad data and obvious labeled outliers.
- **Tier 2:** multiple regions/contracts with climate baselines, multiple
  equipment models, seasonal effects.
- **Tier 3:** subtle/joint outliers and sensor/CAN-fault patterns.

## Roadmap

| Phase | What |
|------|------|
| **F0** | Foundations & runnable skeleton (package, CLI, CI) |
| **F1** | J1939-grounded signal model + data dictionary |
| **F2** | Fleet simulator + Parquet/CSV/DuckDB writers — **Tier 1 ships (MVP)** |
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
