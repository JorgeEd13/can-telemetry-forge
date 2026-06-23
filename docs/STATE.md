# State — can-telemetry-forge

Updated: 2026-06-23

## Current focus

**F2 is done — the MVP (Tier 1) ships.** One command (`forge generate`) produces a
complete, reproducible dataset: a realistically composed fleet of units emitting
the 11 J1939 signals over time, gated by CAN capability era, with a multi-mode
failure label, labeled obvious outliers, and tidy Parquet/CSV/DuckDB tables plus a
manifest and generated data dictionary. Next is **F3 — richer labeled anomalies**
(subtle/joint outliers + sensor faults), then F4 (distribution validation) and F5
(Tier-2/3 diversity).

## Done

- **F0 — Foundations & runnable skeleton** (src-layout package, `forge` CLI, CI on
  Linux+Windows × Py 3.11/3.12, offline tests).
- **F1 — Signal model (J1939-grounded core):** `signals/` package — declarative
  `SignalSpec` registry (ADR-012), capability-era gating (`eras.py`, NULL-not-zero,
  ADR-008), deterministic per-signal generators (`generators.py`), PGNs recorded
  but inert (ADR-013). `docs/DATA_DICTIONARY.md` committed.
- **F2 — Fleet simulator + writers (Tier 1 MVP):**
  - `config.py` — declarative config + **public-grounded fleet/region catalog** +
    seed plumbing. JSON config merging onto a runnable `default_config()` (ADR-015).
    Regions pinned to cited public **Köppen climate types + IRI road-roughness
    bands** (ADR-014; `source` travels in the `regions` table).
  - `sim/fleet.py` — operator→contracts→units: 5-class vehicle mix, triangular age
    curve with a legacy tail, per-contract sizes drawn around an expected value;
    build year → era; runtime/age at window start.
  - `sim/drivers.py` — per-unit `DriverSeries` (duty rhythm, region ambient
    sinusoid, altitude/terrain, monotonic accumulated wear) feeding F1.
  - `labels/failure.py` — **multi-mode** `failure_within_h` + `failure_mode`
    (overheat / oil_starve / bearing), hazard from era-gated signals + wear,
    sampled & derived in **one place** (ADR-009).
  - `anomalies/outliers.py` — labeled obvious out-of-range outliers, recoverable
    from an `is_outlier` mask (ADR-006; the F3 slice that ships in the MVP).
  - `sim/simulate.py` — composes it all over the fleet × window into a tidy long
    `readings` table + dimension tables. One spawned `SeedSequence` per unit per
    stage → independent yet reproducible streams (ADR-005).
  - `io/writers.py` — Parquet / CSV / DuckDB + `manifest.json` (provenance) +
    generated `dataset_dictionary.md`.
  - `cli.py` — `forge generate --config --seed --out --format --days --resolution`
    over the library; `forge validate` still a stub (F4).
  - `configs/fleet.json` — shipped sample config.
  - **31 new offline tests (59 total green.)** Verified end-to-end: default fleet →
    106 units, 915,840 readings, all three failure modes present (overheat 34k /
    oil_starve 16k / bearing 12k), EGT NULL for the pre-Modern 57%, era mix
    45 Modern / 44 Mid / 17 Legacy.

## Next step (concrete)

**F3 — Anomaly & fault injection (labeled).** Extend the obvious-outlier slice
(already shipped) with:

1. **Subtle / joint outliers** — each column plausible alone, jointly inconsistent
   (e.g. high fuel rate with low load; coolant hot with engine off). New label.
2. **Sensor faults** — stuck channel, single-channel drift, dropout — **distinct
   from** the structural era-NULLs (a healthy-capable channel going bad). New label
   column/table.
3. Tests: each defect type present at its configured rate and fully recoverable
   from labels; ADR for the labeled-injection contract (extends ADR-006).

## Notes

- No GPU, no paid services, no training tokens — local NumPy/pandas; CI is free.
- Clean-room provenance is load-bearing: SAE J1939 + documented physics + cited
  public climate/road sources; fictional operator; never a real-log seed.
- Determinism is a hard invariant: one master `SeedSequence` spawned into
  per-stage child streams; same config + seed → byte-identical tables.
- Config is JSON (stdlib, no YAML dep). The bundled default is a complete fleet, so
  `--config` is optional.
