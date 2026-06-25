# State — can-telemetry-forge

Updated: 2026-06-25

## Current focus

**F4 is done — distribution validation ships.** `forge validate` is real (no longer
a stub): a `validation/` package (outside `src/` — the core never imports it) built
as a **declarative registry of reference adapters** (ADR-017, mirroring ADR-012/-016).
Two **offline** adapters always run — `in_spec` (values inside documented J1939
ranges) and `golden` (per-signal mean/std match a *recomputed* pinned reference run,
catching generator drift; nothing committed) — so the command is reproducible by
anyone and CI-safe. A third **opt-in** adapter `ved` overlaps the shared engine
channels against the **Vehicle Energy Dataset** (Kaggle, **CC-BY 4.0**) via
histogram intersection, **fetched at run time through the Kaggle API and never
committed**; it degrades to "unavailable" offline. Output is a self-contained
Markdown report. `kaggle` is a `validate`-extra dep only. Next is **F5** (Tier-2
diversity + Tier-3 CAN-frame faults).

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

## Next step (concrete)

**F5 — Diversity (Tier 2) & richer faults (Tier 3).** Broaden regions/climate/season
and equipment models with distinct failure profiles (Tier 2); add the trickier
fault patterns (the Tier-3 **CAN-frame faults** land once a frame-level encoder
exists — the inert PGNs of ADR-013 are the seam). All config-driven, labeled, seeded;
update DATA_DESIGN to reflect what ships.

## Notes

- No GPU, no paid services, no training tokens — local NumPy/pandas; CI is free.
- Clean-room provenance is load-bearing: SAE J1939 + documented physics + cited
  public climate/road sources; fictional operator; never a real-log seed.
- Determinism is a hard invariant: one master `SeedSequence` spawned into
  per-stage child streams; same config + seed → byte-identical tables.
- Config is JSON (stdlib, no YAML dep). The bundled default is a complete fleet, so
  `--config` is optional.
