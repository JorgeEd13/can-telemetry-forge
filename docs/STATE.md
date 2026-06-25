# State — can-telemetry-forge

Updated: 2026-06-25

## Current focus

**F5 (Tier-2 diversity) is done.** Three axes of realism land as **declarative
catalog entries that resolve to multipliers/offsets** — no new readings-schema
columns (ADR-018, mirroring ADR-012/-016): (1) two more public-grounded
regions/contracts (6 each now); (2) **equipment models** — each `EquipmentModel`
carries per-failure-mode hazard multipliers + small baseline signature offsets +
an optional `build_year_min` capability floor, assigned per unit (class-only
fallback), surfaced as an `equipment_models` dimension table + `units.model_id`;
(3) named **seasons** (`heatwave` / `cold_snap` / `wet_season` over `baseline`)
shifting ambient + wear + per-mode hazards — the knob a future drift demo shifts,
selectable via `--season` / config and echoed in `manifest.json`. The model ×
season hazard multipliers compose multiplicatively into the single per-mode factor
`derive_unit_labels` applies, so the failure label stays derived in one place
(ADR-009). Default fleet → **134 units**. Next is **F6** (Tier-3 **CAN-frame
faults** + the frame-level encoder they need — the inert PGNs of ADR-013 are the
seam; deferred from F5 as a substantial standalone build).

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
- **F3 — Labeled anomaly & fault injection (declarative registry):**
  - `anomalies/spec.py` — the `AnomalyInjector` type + the closed-schema /
    open-vocabulary `anomaly_type` set + the `VALUE_DISTORTION_TYPES` rollup set.
  - `anomalies/injectors.py` — the registry: `obvious_outlier` (out-of-range spike),
    `joint_outlier` (in-range but contextually impossible pairs), and segment-based
    `sensor_stuck` / `sensor_drift` / `sensor_dropout`.
  - `anomalies/inject.py` — `apply_anomalies` orchestrator: per-signal eligibility
    (non-NULL, unclaimed) → ≤1 defect/cell; per-row label resolution by injector
    priority; one seeded stream per injector.
  - `config.py` — `anomaly_rates` per-type map (merges onto `DEFAULT_ANOMALY_RATES`);
    `obvious_outlier_rate` retained as a back-compat alias; validated.
  - `sim/simulate.py` — emits `anomaly_type` + `anomaly_signal` + the `is_outlier`
    rollup; one child rng per injector per unit.
  - `io/writers.py` — per-type counts in `manifest.json`; generated dictionary
    documents the new columns. ADR-016 recorded; DATA_DESIGN §8 / DATA_DICTIONARY
    updated.
  - **14 new offline tests (73 total green.)** Verified e2e (20-day/5-min, seed 5):
    all five families present; `n_outlier_rows` == obvious+joint+stuck+drift
    (dropout excluded, as documented).
- **F4 — Distribution validation (reference-adapter registry):**
  - `validation/` package (outside `src/`): `reference.py` (the `ReferenceAdapter`
    registry + `run_validation` orchestrator + `ValidationRun`), `compare.py` (pure
    NumPy summary stats + **histogram-intersection** overlap), `report.py`
    (self-contained Markdown report).
  - Adapters: `in_spec` (offline, J1939 range check), `golden` (offline, mean/std vs
    a *recomputed* pinned reference run — drift guard, nothing committed), `ved`
    (opt-in, Kaggle CC-BY-4.0 Vehicle Energy Dataset overlap, fetched at run time,
    never committed, degrades gracefully offline).
  - `cli.py`: real `forge validate --config --seed --report --dataset` over the
    library; offline adapters always run (CI-safe), `--dataset ved` opts into the
    network fetch. `pyproject` `validate` extra adds `kaggle`; `pytest` pythonpath
    gains `"."` so `import validation` resolves in tests.
  - ADR-017 recorded; ROADMAP F4 ✅; README "Validating the data (F4)" + CC-BY note.
  - **16 new offline tests (89 total green).** VED tested via a fake-local-CSV (the
    overlap math) + its graceful-unavailable branch — never hits the network in CI.
  - Hardening from building it: `in_spec` masks injected defects via the row-level
    `is_outlier` rollup (a row can distort >1 signal but label only one — ADR-016);
    `golden` is a config-independent drift guard (recomputed golden run in-spec; the
    fleet-derived runtime/age fields excluded since their aggregate moves with the
    seed); the opt-in VED fetch catches **BaseException** (recent `kaggle` raises
    `SystemExit` at import when unauthenticated) so it degrades, never crashes the
    run; report printed as UTF-8 (cp1252-console safe). Tests use tiny fleet configs
    so each `run_validation` simulates sub-second.
  - **VED fetch verified LIVE (2026-06-25).** Real overlap ran end-to-end: synthetic
    vs VED histogram intersection **0.48 (engine RPM) / 0.51 (engine load)** over 200k
    VED rows → all ved checks pass. Three run-time realities (ADR-017 addendum):
    Kaggle's new SDKs 403 on dataset downloads → fetch the **classic REST endpoint**
    (`www.kaggle.com/api/v1`) with **HTTP Basic auth** from `~/.kaggle/kaggle.json`
    (only `requests` needed, SDKs dropped from the extra); Norton TLS interception →
    `pip-system-certs` (Windows trust store, not verify=False); the **VED handle is
    configurable** (`--ved-handle`/`FORGE_VED_HANDLE`/config, default verified
    `yashseth25/ved-segregated`) because the originally-assumed handle didn't exist.
    The 510 MB zip lands in the git-ignored cache, read capped (200k rows × mapped
    cols), never committed.
- **F5 — Diversity (Tier 2):**
  - `config.py` — `EquipmentModel` + `Season` dataclasses; catalog grown to 6
    regions / 6 contracts / 6 equipment models / 4 seasons; validation (model
    classes, hazard-mode keys, capability floor in range, season multipliers);
    JSON merge for models + `resolve_season` (named preset or inline). `season`
    field on `ForgeConfig` (default `baseline`).
  - `sim/fleet.py` — `Unit` gains `model_id` + offset/hazard fields; `build_fleet`
    assigns a model per unit (uniform over the class's models, class-only fallback)
    and draws the build year respecting a per-model `build_year_min` floor.
  - `sim/drivers.py` — season `ambient_delta_c` added to the ambient curve and
    `wear_mult` into wear; per-model signature offsets threaded into `DriverSeries`.
  - `signals/generators.py` — `DriverSeries` carries coolant/oil/vibration offsets,
    applied inside the J1939-range clamp (default 0.0 → F1 callers unchanged).
  - `labels/failure.py` — `derive_unit_labels` takes an optional per-mode
    `hazard_mult` (defaults to neutral → F2 behaviour exact).
  - `sim/simulate.py` — `_merge_hazard_mults` composes model × season; emits the
    `equipment_models` dimension table + `units.model_id`; passes season to drivers.
  - `io/writers.py` — writes `equipment_models`; echoes `season` in the manifest;
    dictionary documents the new table + season.
  - `cli.py` — `--season` on `forge generate`.
  - ADR-018 recorded; ROADMAP F5 ✅ + new F6; DATA_DESIGN §4/§6/§7/§9 updated.
  - **12 new offline tests (102 total green).** Verified e2e: default fleet → 134
    units; `equipment_models.csv` written; heatwave run produces more failures than
    baseline; reproducible under a non-baseline season.

## Next step (concrete)

**F6 — CAN-frame faults (Tier 3) & a frame-level encoder.** Build a frame-level
J1939 encoder (per-PGN byte/bit layout, scaling/offset) over the inert PGNs recorded
since ADR-013 — that is the seam. Then add CAN-frame fault injectors as new registry
entries: each is a new `anomaly_type` *value* (ADR-016 — no schema change), labeled
and recoverable. All config-driven, labeled, seeded; update DATA_DESIGN §8.

## Notes

- No GPU, no paid services, no training tokens — local NumPy/pandas; CI is free.
- Clean-room provenance is load-bearing: SAE J1939 + documented physics + cited
  public climate/road sources; fictional operator; never a real-log seed.
- Determinism is a hard invariant: one master `SeedSequence` spawned into
  per-stage child streams; same config + seed → byte-identical tables.
- Config is JSON (stdlib, no YAML dep). The bundled default is a complete fleet, so
  `--config` is optional.
