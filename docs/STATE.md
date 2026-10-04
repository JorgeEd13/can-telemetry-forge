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
- **R4-T4-a — ADR-005, DATA_DESIGN §11, ARCHITECTURE and DATA_DICTIONARY describe a single
  generator; the code spawns a seed tree.** All four say one seeded generator is threaded through
  every stage; `simulate()` builds a `SeedSequence` and spawns one child for the fleet plus one per
  unit per stage (described correctly only in `docs/ROADMAP.md`, this file, and partly in the
  ADR-019 note on per-injector streams). `ForgeConfig.rng()` ("Child rngs spawn from this")
  has no callers in `src/` or `tests/`. Replacing the spawn tree with one shared
  `default_rng(config.seed)` → 135 passed, and append stability (below) drops from 126/126 units unchanged
  to 0 (the replacement also changes the fleet itself: 137 units instead of 126). Byte-identical output itself holds: two processes with different `PYTHONHASHSEED`, same
  config → identical sha256 for all 8 output files, CSV and Parquet (DuckDB not checked). Fix:
  amend ADR-005 with a dated note, fix §11 and ARCHITECTURE, delete or wire `rng()`.
- **R4-T4-b — per-unit streams are keyed by position, so growing the anomaly registry reseeds the
  dataset.** A unit's block starts at `i * _STREAMS_PER_UNIT`, and `_STREAMS_PER_UNIT = 3 +
  len(ANOMALY_TYPES)`. Probe config (`days 2`, `5min`, seed 7, 126 units): one extra stream slot
  (what a 6th injector does, even at rate 0) → 125/126 units get different signals and anomalies,
  135 passed. An extra contract appended at the end → 126/126 units unchanged; the same contract
  prepended → 2/126 unchanged. No pinned golden exists (the `golden` validator recomputes its
  reference). The simulate docstring's "a unit's data never depends on how many units preceded it"
  holds only for appends. Fix: key child sequences by a stable name (unit, stage), or pin a small
  dataset hash.
- **R4-T4-c — the stream layout is untested.** Setting `_STREAM_LABELS` equal to `_STREAM_SIGNALS`
  (labels draw from the signal stream) → 135 passed, 4/126 units change; `base = i` instead of
  `i * _STREAMS_PER_UNIT` (neighbouring units share streams across stages) → 135 passed.
  `test_simulate_is_reproducible` only checks same seed → same output, which both mutations still
  satisfy. Fix: a test that the (unit, stage) stream indices are disjoint, plus the append-stability
  check from R4-T4-b.
- **R4-T4-d — a negative `units_per_contract_sd_frac` silently disables contract-size variation.**
  `_contract_unit_count` uses `max(expected * sd_frac, 1e-9)` as the spread, so a negative fraction
  becomes ~0 and every contract gets exactly its expected size (read, not run; this explains the
  "exactly 140 units" lead from R4-T3). Fix: reject negative values in `validate()`.
- Unverified leads from R4-T4: a model `build_year_min` above `build_year_max` hands
  `rng.triangular` a left bound above the right; the conditional model draw in `build_fleet` shifts
  the fleet stream when a class gets its first model; `_HOURS_PER_YEAR` in `sim/fleet.py` is unused;
  the comment on `_ANNUAL_RUNTIME_MEAN_H` describes hours rising with age, which the code does not
  do; the ARCHITECTURE pipeline diagram places anomaly injection before label derivation (code and
  ADR-009 do the reverse); `test_era_gated_signals_are_null_not_zero` asserts nothing when the seed
  draws no Legacy unit.
- **R4-T5-a — no test proves the model or season hazard multipliers reach the failure label.**
  Tests cover `_merge_hazard_mults` and `derive_unit_labels` called with a hand-made multiplier;
  nothing runs `simulate()` with a multiplier that changes an assertion. Dropping
  `unit.hazard_mult` from the merge in `simulate()` → 135 passed; dropping
  `config.season.hazard_mult` → 135 passed. Probe config (`days 4`, `5min`, seed 7, 126 units):
  neutralising every catalog model multiplier moves failure-labelled rows from 3071 to 3680 (9
  failing units either way). Fix: an end-to-end test that runs the simulator with an extreme model
  and season and asserts the failing-unit count moves.
- **R4-T5-b — the heatwave end-to-end test uses a non-monotone oracle.**
  `test_heatwave_raises_overheat_hazard_end_to_end` compares the sum of `failure_within_h` rows,
  which counts the hours before a failure, so earlier failures mean fewer positive rows. Probe
  config: a season with `overheat: 1e6` makes 126/126 units fail and positive rows drop to 187
  (baseline: 3071 rows, 9 units). The ambient shift alone already satisfies the assertion
  (heatwave without its hazard multiplier: 4270 rows, 12 units; full heatwave: 4993 rows, 15
  units). Fix: assert on failing-unit count, and isolate the multiplier from the ambient effect.
- **R4-T5-c — `SEASONS` presets are shared mutable state.** `resolve_season("heatwave")` returns the
  module-level object, and `Season.hazard_mult` is a plain dict inside a frozen dataclass. Setting
  `config.season.hazard_mult["overheat"] = 99.0` on one config makes the next
  `config_from_dict({"season": "heatwave"})` in the same process carry `overheat: 99.0`.
  `test_resolve_season_named_and_inline` asserts the identity. Equipment models do not have this
  problem (`build_fleet` copies the dict). Confirms the R4-T3 lead on shared `SEASONS` entries.
  Fix: return a copy, or store multipliers in a read-only mapping.
- **R4-T5-d — the catalog's value guards are untested, and the wear check is non-strict.**
  Removing both non-negativity checks in `validate()` → 135 passed (the checks themselves work: a
  season with `overheat: -1.0` raises `ValueError`). Ignoring `season.wear_mult` in
  `sim/drivers.py` → 135 passed, because `test_season_shifts_ambient_and_wear` asserts `>=`.
  Validation checks names and sign only: `overheat: 1e6` is accepted. Fix: tests for the negative
  cases, a strict or banded wear assertion, and range bounds on multipliers.
- **R4-T5-e — the `cold_snap` preset leaves every label unchanged on the probe config.** Baseline
  vs `cold_snap` (`days 4`, `5min`, seed 7): `failure_within_h` and `failure_mode` columns are
  identical, while mean `coolant_temp_c` drops from 105.05 to 103.87. Cause not investigated
  (hypothesis: identical per-step draws plus modest multipliers rarely move the first crossing).
  Matters for the planned drift demo: this preset shifts features without shifting labels at this
  horizon. Fix: measure label shift per preset over a longer window before relying on it.
- Unverified leads from R4-T5: the `Season.wear_mult` docstring says it scales the wear hazard
  gain, while `sim/drivers.py` multiplies the wear accumulation rate; `wear_mult` has no effect on a
  unit already clipped at wear 1.0; a NaN multiplier passes the `v < 0` check;
  `_merge_hazard_mults` drops unknown modes silently when called without `validate()`.
- **R4-T6-a — the ADR-020 degradation ramp has no effective test.** Making `apply_degradation`
  return the unmodified copy (no ramp at all) → 135 passed. The ramp test accepts zero drift
  (`abs(delta[event]) >= abs(delta[start])` and `... or delta[event] == 0.0`), and its
  `delta[:start]` check is vacuous because every test window starts at row 0. Turning the ramp into
  a step (`_DEGRADATION_SHAPE = 0.0`) fails only through float rounding
  (`27.999999999999986 >= 28.0`). Fix: assert the drift at the event is close to the configured
  peak (unless clamped) and grows across the window.
- **R4-T6-b — the ramp test inspects one failure mode.** It returns after the first failing seed
  (seed 17, `overheat`) and reads the expected sign from the `_DEGRADATION` map it is testing.
  Flipping `oil_starve` to `+180.0` → 135 passed. Fix: hard-code the physical direction per mode in
  the test and build one labelled case per mode.
- **R4-T6-c — "pure function (no mutation)" (ADR-020) is untested.** Replacing the copy with an
  in-place add (`series += ramp * peak`) → 135 passed; the ramp test then compares the array with
  itself. `simulate()` reassigns `signals`, so output data is unaffected today. Fix: assert the
  input arrays are unchanged after degrading a failing unit.
- **R4-T6-d — post-event behaviour is undefined and undocumented.** After the sampled event the unit
  keeps running, labelled 0, and the ramp drops to 0 on the next step. Probe config (`days 4`,
  `5min`, seed 7): the 9 failing units run 316–1086 rows past the event; coolant on u0017 goes
  149.2 → 120.7 °C in one step. Neither README.md nor the design docs (DATA_DESIGN, DECISIONS) say what happens after a failure. Fix: decide and document
  a policy (truncate at the event, or explicit repair with a post-event column).
- **R4-T6-e — label tests skip or pass vacuously when no unit fails.** With `_WEAR_GAIN = 0.0` the
  run is 2 failed, 131 passed, 2 skipped: both degradation tests skip instead of failing.
  `test_failure_mode_is_valid_and_horizon_marked` (`if ... is not None`) and the Legacy test would
  also pass without asserting anything if their seeds stopped failing (read, not measured). Fix: pin
  a seed that fails and assert that it does.
- DATA_DESIGN §7 lists oil temperature ("climbing oil temp", "rising oil temp") as part of the
  overheat and oil-starvation signatures, but the generator has no oil-temperature signal at all.
- Unverified leads from R4-T6: the module docstring says hazards use "signals + wear + age", while age enters only as
  the starting wear; the "first-pass, refined in F5" comment on the hazard constants is stale per
  ADR-020; the `span <= 0` guard in `apply_degradation` is unreachable for labels built by `derive_unit_labels` (reachable only with hand-built `UnitLabels`); the tests' `small_config`s (24–48 h)
  are shorter than the 168 h horizon, so every test window starts at row 0 and the ramp is compressed (not measured on the
  90-day default).
- **R4-T7-a — 🔴 URGENT — "every injected defect is recoverable" is false in the emitted dataset.**
  README L155, ADR-006 and the `anomalies/inject.py` docstring promise full recoverability; the
  dataset carries one `anomaly_type`/`anomaly_signal` per row and the per-cell `hits` are dropped
  inside `simulate()` (only CAN-frame hits survive, and only with `--emit-raw-frames`). Probe
  (`days 10`, `5min`, seed 7, default rates, 126 units): 18,022 defect cells, 384 rows with defects
  on two or more signals (380 on two, 4 on three), 388 cells named by no label column; 281 of them
  hold in-range values (joint 108, stuck 38, drift 47, corrupt 47, stale 41), so a range check
  can't recover them either. The manifest's per-type counts are
  winning-row counts (they sum to 17,634 = rows with at least one defect). Fix: a long-format per-cell labels table
  (`unit_id, t_index, signal, anomaly_type`), or reword the claim.
- **R4-T7-b — the row-collision rule ("injector priority = registry order") is untested.**
  Making the last injector win (`unclaimed = hit.mask`) → 135 passed; the readings change
  (sha256 differs) and rows with `is_outlier` true under a non-distorting label go 3 → 75. The
  docstring's "dropout last" is stale: the CAN-frame injectors come after it. Fix: one hand-built
  row with two defects, assert the winner.
- **R4-T7-c — the orchestrator's era-gate is dead code.** Starting `eligible` as all-true for every
  signal → 135 passed and byte-identical readings; the live guard is each injector's
  `values is None` skip. Fix: test each guard in isolation, or keep one.
- **R4-T7-d — the "rollup over all distorting cells" semantics of `is_outlier` is untested.**
  Rolling up only the winning cells (`is_outlier |= unclaimed`) → 135 passed (3 rows differ in the
  probe). The test comment at `test_anomalies.py` L218–222 describes the semantics; its asserts
  hold under both versions.
- **R4-T7-e — `test_at_most_one_defect_per_row` doesn't test exclusion.** Per row it is
  tautological; per cell it doesn't look. Removing the eligibility shrink fails only
  `test_obvious_outliers_are_out_of_range` (a later fault overwrites a spike); the probe shows
  45 doubly-defective cells. Its comment promises "no outlier flag" for clean rows and doesn't
  assert it. Fix: assert per-signal hit masks are pairwise disjoint.
- Unverified leads from R4-T7: ADR-006 says tests assert each type "at its configured rate" (presence, zero-rate,
  config-validation and one type's monotonicity tests exist; no configured-rate assertion); the package docstring says "three defect families"
  (four since F6); `DEFAULT_ANOMALY_RATES` keys are string literals, not the constants;
  `test_injection_is_reproducible` doesn't compare `anomaly_signal`.

## Notes

- No GPU, no paid services, no training tokens — local NumPy/pandas; CI is free.
- Clean-room provenance is load-bearing: SAE J1939 + documented physics + cited
  public climate/road sources; fictional operator; never a real-log seed.
- Determinism is a hard invariant: one master `SeedSequence` spawned into
  per-stage child streams; same config + seed → byte-identical tables.
- Config is JSON (stdlib, no YAML dep). The bundled default is a complete fleet, so
  `--config` is optional.
