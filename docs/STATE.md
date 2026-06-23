# State — can-telemetry-forge

Updated: 2026-06-23

## Current focus

**F1 is done.** The J1939-grounded signal model is built, tested, and documented.
Next is **F2 — the fleet simulator + writers (Tier 1 ships)**: compose the F1
per-unit signal model across N units over a time window, derive the multi-mode
failure label in one place, and write tidy Parquet / CSV / DuckDB tables from one
`forge generate` command.

## Done

- **F0 — Foundations & runnable skeleton** (src-layout package, `forge` CLI with
  honest stub subcommands, CI on Linux+Windows × Py 3.11/3.12, first offline tests).
- **DATA_DESIGN fully co-written** (two-layer realism, CAN era capability,
  multi-mode failure label, environment = thermal+wear+terrain, configurable
  resolution/scale). ADR-007…011.
- **F1 — Signal model (J1939-grounded core):**
  - `src/can_telemetry_forge/signals/` package:
    - `spec.py` — declarative `SignalSpec` **registry** (ADR-012), single source of
      truth: the 11 Tier-1 signals with real **J1939 SPN + PGN + unit + operating
      range + capability era + driver list**. `Era` enum (Legacy/Mid/Modern +
      always-on sentinel).
    - `eras.py` — capability-era gating (ADR-008): model-year → era; a signal a
      unit's era doesn't support is **NULL, never zero**. Structural missingness,
      kept distinct from (future) sensor-fault dropouts.
    - `generators.py` — **deterministic** per-signal functions of (drivers, wear/env
      state, one seeded `np.random.Generator`); documented cross-signal correlations
      (fuel↑load·rpm, coolant↑ambient+load+wear, oil↓wear, EGT↑altitude+load,
      boost↓altitude, vibration↑terrain+wear, runtime monotonic). Values clamped to
      the documented J1939 ranges. Magnitudes are first-pass constants (refine F5).
    - `__init__.py` — public API (registry + gating + `generate_unit`).
  - `docs/DATA_DICTIONARY.md` committed — every field → SPN (+PGN column, **inert**
    per ADR-013) + unit + range + era + drivers; era table; correlation signs.
  - `tests/test_signals.py` — 21 offline tests: registry consistency, ranges,
    era-gating NULL, all 7 correlation signs, era-boundary mapping, determinism
    (same seed → identical; different seed → differs). **28 tests total, green.**
  - ADR-012 (signal registry) + ADR-013 (PGN recorded but inert) recorded.

## Next step (concrete)

**F2 — fleet simulator + writers (the MVP cut).**

1. **Fleet composition** (`sim/`): operator → contracts → units (model, build year →
   era, region/duty). Realistic vehicle mix / age curve / units-per-contract from
   the config catalog (public-grounded plausibility — fill the §"Still open"
   distributions). One seeded rng threaded from config (ADR-005).
2. **Driver series** per unit (duty cycle, ambient, altitude, terrain, wear) at the
   configurable resolution — these feed `DriverSeries` into the F1 `generate_unit`.
3. **Multi-mode failure label** (overheat / oil-starvation / bearing-wear), derived
   in **one place** (ADR-009): horizon `failure_within_h` + mode.
4. **Writers** (`io/`): tidy long table + dimension tables (units/models/regions) +
   label table → Parquet / CSV / DuckDB. Include deliberate obvious labeled outliers.
5. Wire `forge generate --config --seed --out`; same seed → identical output (test).

Open specifics to fill in F2 (DATA_DESIGN §"Still open"): concrete vehicle-mix /
age-curve / units-per-contract distributions; the public regional/climate/
road-quality sources to cite for the environment modifiers.

## Notes

- No GPU, no paid services, no training tokens — generation is local
  NumPy/pandas; CI is free GitHub Actions.
- Clean-room provenance is load-bearing: SAE J1939 standard + documented physics,
  never a real-log seed. PGNs are recorded but the generator emits engineering-unit
  series, not raw frames (a frame encoder is a future seam).
- Determinism is a hard invariant: one seeded generator threaded through; the
  hour-meter and equipment-age are noise-free by construction.
