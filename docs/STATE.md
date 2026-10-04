# State — can-telemetry-forge

Updated: 2026-06-26

> 🧊 **FROZEN for feature work since 2026-10-03 — study block open.** This repo was cut into
> **12 territories** by the APROFUNDAMENTOS programme (`repo-base-career/sistema/APROFUNDAMENTOS_ROADMAP.md`
> §R4). While the block is open, that programme reads this code line by line and measures its
> guards by mutation, so a moving tree would invalidate the measurements. Findings from the study
> go to this file's backlog rather than being fixed there. The freeze lifts when the R4 block
> closes. It is a *convention*, not a mechanism — nothing enforces it; Jorge can lift it by saying so.

## Current focus

**Post-F6 realism fix — progressive pre-failure degradation (ADR-020), v0.2.0.**
Consuming the generator from `forge-pdm-mlops` surfaced a real defect: the failure
model sampled an *event time* and marked a horizon window but never made the signals
**drift** toward the event, so a failing unit's pre-failure rows were statistically
identical to its healthy rows (within-unit separation ≤ 0.06 SD; vibration +0.007) and
a per-row classifier scored ≈ 0.55 (chance) *by construction*. DATA_DESIGN §7 always
promised a signature the failure "builds toward" — it just wasn't implemented.
**`labels/failure.apply_degradation`** now injects a convex ramp into the winning mode's
signature signals across the pre-event horizon (overheat → coolant/EGT climb;
oil_starve → oil sags; bearing → vibration rises), clamped to J1939 range, run after the
clean-signal label (ADR-009 intact) and before defect injection. **Measured:** base
features ≈ 0.55 → **0.73** ROC-AUC, ≈ **0.82** once the consumer adds `vibration_mms`;
failure rate steady at ≈ 8 %. Two hazard rebalances (scale-wear-down; sustained-stress)
were prototyped, **scored, and rejected** — neither beat the ramp (logged in ADR-020, the
F2.5-style honest negative). **Version bumped 0.1.0 → 0.2.0** (data changed → the pin
moves; the consumer's fixture was rebuilt). **135 tests green** (+3 degradation tests).

**F6 (Tier-3 CAN-frame faults + a frame-level encoder) is done — the roadmap's
last planned phase.** ADR-013 left each signal's PGN inert; F6 activated it
(ADR-019): a frozen `FrameLayout` on `SignalSpec` (byte/bit placement +
scaling/offset) for the 8 bus signals, and a real **frame-level encoder/decoder**
(`signals/frames.py`) — `value → raw → little-endian J1939 frame bytes` and back,
modeling the not-available/error sentinels (both decode to `NULL`). Four CAN-frame
fault families (`anomalies/frame_faults.py`), each a new `anomaly_type` *value* in
the same open vocabulary (**no schema change**, ADR-016): `can_frame_corrupt` (byte
flip → implausible decode), `can_frame_stale` (re-sent frame → frozen value, a
transport fault), `can_frame_error_indicator` (error/NA code → `NULL`),
`can_frame_truncated` (short DLC → `NULL`). Faults corrupt the **bytes** and **decode
back** into the engineering column, so the dataset stays decoded; the byte-level
corrupted frames are optionally written to a `can_frames` side table
(`--emit-raw-frames` / `emit_raw_frames`, off by default). The value generators still
never read the layout (the ADR-013 inert-PGN invariant is re-asserted by a test).
Default fleet unchanged at **134 units**. **The planned roadmap (F0–F6) is complete.**

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
    (only `requests` needed, SDKs dropped from the extra); TLS termination →
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
- **F6 — CAN-frame faults (Tier 3) & a frame-level encoder:**
  - `signals/spec.py` — `FrameLayout` dataclass; the 8 bus signals get a layout
    (start bit / bit length / scale / offset / little-endian / 8-byte frame) from the
    published J1939-71 PGNs (EEC1/ET1/EFL-P1/EEC2/LFE/IC1/AT1T1I). Activates the seam
    ADR-013 left inert (ADR-019).
  - `signals/frames.py` — the **encoder/decoder**: `value_to_raw` / `raw_to_value`,
    `encode_signal_frame` / `decode_signal_frame`, `frame_to_hex`. Reserves the top
    two raw codes per field for the J1939 not-available/error sentinels (both decode
    to `NULL`); a too-short frame decodes to `NULL`.
  - `anomalies/spec.py` — four new `anomaly_type` values + `CAN_FRAME_TYPES`;
    `InjectionHit` gains an optional `frames` payload (row → corrupted-frame hex).
  - `anomalies/frame_faults.py` — the four injectors (corrupt / stale /
    error_indicator / truncated), registered after the value/sensor families; only
    bus signals (those with a layout) are targetable.
  - `anomalies/inject.py` — default rates for the new types; `AnomalyLabels.frame_records()`.
  - `config.py` — `emit_raw_frames` flag (config + JSON merge). `sim/simulate.py`
    collects frame records → a `can_frames` table on `SimulatedDataset`. `io/writers.py`
    writes `can_frames` only when flagged; manifest gains `emit_raw_frames` +
    `n_can_frames`; dictionary documents the new types + table. `cli.py` —
    `--emit-raw-frames` on `forge generate`.
  - ADR-019 recorded; ROADMAP F6 ✅; DATA_DESIGN §8 + DATA_DICTIONARY updated.
  - **30 new offline tests (132 total green).** Verified: codec round-trips every
    signal within one quantum; all four families present/labeled/recoverable; raw
    artifact matches the labeled cells and is opt-in; the generators ignore the layout
    (ADR-013 invariant). E2e (3-day/5-min, seed 7) with `--emit-raw-frames`: 912
    `can_frames` rows across the four types.

## Next step (concrete)

**The planned roadmap (F0–F6) is complete.** The generator is a finished Tier-1→3
synthetic-telemetry product: J1939-grounded signals, era gating, multi-mode failure
labels, Tier-2 diversity (regions/models/seasons), distribution validation, and a
full anomaly contract (value / sensor / CAN-frame faults). Candidate follow-ons, none
committed:
- The **4th vitrine (MLOps)** that consumes this generator — train → MLflow tracking
  → model registry → FastAPI serving → drift monitoring, with `--season` as the drift
  knob. This is the originally-planned downstream narrative.
- A **README refresh** surfacing F4–F6 (validation overlap numbers, the frame codec,
  the `can_frames` artifact) for the portfolio reader.
- Polish: a `forge` example that round-trips a frame in the README; optional Tier-3
  frame-fault tuning if VED-style validation reveals gaps.
Pick a direction with Jorge before starting — F6 closed a clean boundary.

### Study backlog (APROFUNDAMENTOS R4)

Findings from the line-by-line study. Recorded, **not fixed** — they are discharged in one
repo session after the R4 block closes. Measured against the full suite (baseline 135 passed).

- **R4-T1-a — the data dictionary has no guard against the registry.** `signals/spec.py`
  says `DATA_DICTIONARY.md` "is generated to match it" and `signals/eras.py` says the
  dictionary, generators and gate "can never silently disagree"; the dictionary is
  hand-written and no test reads it. Moving `boost_pressure_kpa` from `Era.MID` to
  `Era.LEGACY` → 135 passed, dictionary still says Mid. No test pins the full era × signal
  table either (the Legacy test checks 4 of the 6 signals that should be gated; the
  supported/gated partition test holds for any era assignment). Fix: a parse-and-compare
  test, or generate the table from the registry; correct both docstrings.
- **R4-T1-b — `test_pgn_recorded_but_inert_by_default` checks neither.** It asserts that
  *any* J1939 signal has a PGN. Setting 7 of the 8 PGNs to `None` → 135 passed; making
  `generate_unit` scale a signal by its PGN → 135 passed. ADR-013 ("a test asserts … the
  generator does not depend on them") and the `FrameLayout` docstring overstate it, and
  `DATA_DICTIONARY.md` says F6 "activated" the PGN — F6 activated the `layout`; no code
  outside `spec.py` reads `.pgn`. Fix: assert every SPN-backed signal has a PGN, and test
  generator output is unchanged when PGNs are stripped.
- Unverified leads from the same study: `SignalSpec.drivers` names are not validated
  against the registry/`DRIVER_*` constants; the `Era.MODERN` comment lists
  "after-treatment" as an item beyond DEF; no other after-treatment signal (e.g. DPF) is in
  the registry.
- **R4-T2-a — oil pressure reads 0 kPa on a running engine in ~41 % of readings.**
  `_oil_pressure_kpa` is `100 + 350·rpm_frac − 180·wear`; at idle it goes negative once wear
  exceeds (100 + model offset)/180 — ~0.56 with no offset, 0.46–0.64 across the fleet's model
  offsets — and the J1939 clamp returns 0. Measured on `default_config()` (142 units × 129,600
  one-minute steps, study seeds, not the `simulate()` streams): 41.1 % of oil readings are exactly
  0 — 70.4 % of off-shift minutes vs under 0.1 % on-shift; 58.2 % for units starting at wear 1.0 vs
  30.6 % for the rest. The range test runs after the clamp, and the correlation test's scenario
  stays near 104 kPa, so neither sees it. The "oil falls with wear" relation is flat for the most
  worn units. Fix: a physical idle floor or a saturating wear term; a test on the fraction of
  readings at the range boundary.
- **R4-T2-b — 54 of 142 default-fleet units start the window at wear 1.0, and wear growth is
  untested.** 64 of 142 end at 1.0. Freezing wear at its start value
  (`accumulated_h = unit.runtime_start_h + 0.0 * t_h`) → 135 passed: the monotonic test accepts
  a constant series and the region test compares rates. The `drivers.py` docstring says a harsh
  high-hour unit "approaches" full wear. Fix: rescale `_WEAR_FULL_SCALE_H` against the fleet's
  runtime distribution; assert `wear[-1] > wear[0]` for an unsaturated unit.
- **R4-T2-c — seasonal phase is drawn per unit, not per region.** Within one region the 90-day
  mean ambient differs between units by up to 36.0 °C (`alpine_subarctic`, amplitude 20); 10.2 °C
  in `tropical_humid`, the smallest. Season is a property of the place (ADR-010). The module
  docstring also says duty jitter is the only randomness. Fix: draw the phase once per region.
- **R4-T2-d — correlation tests assert sign, not strength; DATA_DESIGN §5 says both.** Both
  scenarios in `mean_of` share one seed (common random numbers), so any positive difference
  passes: `_EGT_ALT_GAIN_C_PER_KM` 18 → 0.001 → 135 passed. Fix: assert a band on the difference,
  or reword §5.
- Unverified leads from R4-T2: the comment above the per-signal functions says they run "in
  registry order" and that the registry is in dependency order — neither holds (`coolant_temp_c`
  precedes `engine_load_pct` in the registry; `generate_unit` hard-codes its own order); coolant
  is a linear sum with no thermostat regulation; documented dependencies with no implementation
  (rpm ← load, coolant ← runtime, oil ← oil temp); "engine off" exists only where duty jitter is
  clipped to 0, with no contiguous shutdown; no golden test pins values (swapping the rpm/load draw
  order → 135 passed with every noisy value changed); effect of the 0 kPa oil floor on fault
  labels/anomalies not examined.
- **R4-T3-a — misspelled config keys silently fall back to the default.** `config_from_dict`
  keeps only six named top-level keys and `_fleet_from_dict` only reads known fleet keys; anything
  else is dropped. `{"dayz": 7}` → `days == 90`; `{"Seed": 7}` → `seed == 42`;
  `{"fleet": {"build_year_mde": 2000}}` → `build_year_mode == 2016`, no warning. Nested entries do
  the opposite (`"sorce"` in a region → `TypeError` from the dataclass). The `_comment` key in
  `configs/fleet.json` (ADR-015) relies on the lenient top level. Fix: reject unknown keys with a
  `ValueError`, allowing `_`-prefixed keys.
- **R4-T3-b — `validate()` checks references, not values or types; the provenance test checks
  presence, not format.** Accepted by `config_from_dict`: a region with `source ""`,
  `terrain_roughness 7.0` (docstring says `[0, 1]`) and `wear_modifier -2.0`; duplicate region and
  contract ids; `"contracts": []` (0 units); `days: true` (1 day). A negative `vehicle_mix` weight
  passes `validate()` and fails later in `build_fleet` with numpy's "Probabilities are not
  non-negative"; `days: "7"` raises `TypeError`, not `ValueError`; `seed: 4.5` / `seed: -1` pass
  `validate()` and fail in `rng()`. Replacing all six default region citations with `"n/a"` → 135
  passed, and `simulate.py` writes `source` into the `regions` table. Fix: range/type checks on
  region and top-level fields, unique ids, non-empty contracts, non-negative weights; a format check
  on `source`.
- **R4-T3-c — the default `vehicle_mix` dict is shared across `default_config()` calls.**
  `default_config()` returns a new `ForgeConfig` around the same module-level `FleetSpec` and dict.
  `default_config().fleet.vehicle_mix["support"] = 99.0` → the next `default_config()` returns 99.0
  (was 0.14), and `config_from_dict` merges onto it. `anomaly_rates` uses a copying
  `default_factory` and is not affected. Fix: build the default fleet per call, or store the mix as
  an immutable mapping.
- **R4-T3-d — DATA_DESIGN §3 says the class mix varies by contract and region; the schema has one
  global mix.** `Contract` has only `duty_bias`, and `build_fleet` draws every unit with one weight
  vector built from `FleetSpec.vehicle_mix` (`sim/fleet.py`, before the contract loop). ADR-011 says
  "~100 units"; the default expects 140 since F5 (104 at F2). Fix: a per-contract mix override, or
  reword §3; add a dated note to ADR-011.
- Unverified leads from R4-T3: no size guard (`1s` × 90 days = 7,776,000 steps per unit); a
  negative `units_per_contract_sd_frac` is accepted; the comment above the Tier-2 checks in
  `validate()` promises a "fully covered" check the code does not make (no failure observed: `build_fleet` picks among a class's models, so any class with one model is covered); `arid_highland` cites Köppen
  BWk with a 22 °C mean, above the 18 °C bound usually given for the "k" suffix; `altitude_m` and
  `wear_modifier` cite no source; `SEASONS` entries may be shared the same way as the mix.

## Notes

- No GPU, no paid services, no training tokens — local NumPy/pandas; CI is free.
- Clean-room provenance is load-bearing: SAE J1939 + documented physics + cited
  public climate/road sources; fictional operator; never a real-log seed.
- Determinism is a hard invariant: one master `SeedSequence` spawned into
  per-stage child streams; same config + seed → byte-identical tables.
- Config is JSON (stdlib, no YAML dep). The bundled default is a complete fleet, so
  `--config` is optional.
