# Data Dictionary — can-telemetry-forge (Tier 1)

Every field the generator emits, with its **SAE J1939** identity, engineering
unit, documented operating range, **CAN capability era**, and the signals it is
correlated with. This file is the human-readable face of the machine-readable
registry in [`src/can_telemetry_forge/signals/spec.py`](../src/can_telemetry_forge/signals/spec.py)
— if the two ever disagree, the registry wins and this doc is wrong.

> **Provenance.** SPN numbers, units, scaling, and ranges below are from the
> publicly documented **SAE J1939-71** standard. Magnitudes inside the generators
> (slopes/offsets) are first-pass plausible values, *not* fitted to any real log
> (clean-room — see [DECISIONS.md](DECISIONS.md) ADR-003). Output is synthetic.

## Capability eras (ADR-008)

A unit reports only the SPNs its electronics support. Eras are mapped from a unit's
model year and gate the schema; an unsupported signal is emitted as **NULL
(missing), never zero**.

| Era | Model years | Adds (cumulative) |
|---|---|---|
| **Legacy** | ≤ 2004 | core engine: engine speed, coolant temp, oil pressure (+ always-on runtime/age) |
| **Mid** | 2005–2014 | + engine load, fuel rate, boost pressure |
| **Modern** | ≥ 2015 | + EGT, DEF level, vibration |

`runtime_hours` and `equipment_age_days` are **not** CAN-gated — every unit has them.

## Signals

`Era` = the era that introduces the signal (and every later era reports it).
The **PGN** column is recorded from J1939 but **inert by default** (ADR-013): the
generator emits engineering-unit time-series, not raw CAN frames, so the PGN is
captured for a future frame-level encoder, not used in generation yet.

| Field | SPN | PGN (inert) | Unit | Range | J1939 scaling | Era | Driven by |
|---|---|---|---|---|---|---|---|
| `engine_speed_rpm` | 190 | 61444 | rpm | 0 – 8031.875 | 0.125 rpm/bit | Legacy | duty cycle |
| `coolant_temp_c` | 110 | 65262 | °C | −40 – 210 | 1 °C/bit, offset −40 | Legacy | ambient, load, wear |
| `oil_pressure_kpa` | 100 | 65263 | kPa | 0 – 1000 | 4 kPa/bit | Legacy | RPM, wear |
| `runtime_hours` | — | — | h | 0 – 120000 | (accumulated) | always | time / duty |
| `engine_load_pct` | 92 | 61443 | % | 0 – 125 | 1 %/bit | Mid | duty cycle, terrain |
| `fuel_rate_lph` | 183 | 65266 | L/h | 0 – 3212.75 | 0.05 L/h per bit | Mid | load · RPM |
| `boost_pressure_kpa` | 102 | 65270 | kPa | 0 – 500 | 2 kPa/bit | Mid | load, altitude |
| `egt_c` | 173 | 65270 | °C | −273 – 1734.97 | 0.03125 °C/bit, offset −273 | Modern | load, altitude |
| `def_level_pct` | 1761 | 65110 | % | 0 – 100 | 0.4 %/bit | Modern | runtime |
| `vibration_mms` | — | — | mm/s | 0 – 50 | (telematics add-on) | Modern | load, terrain, wear |
| `equipment_age_days` | — | — | days | 0 – 40000 | (fixed per unit) | always | build date |

> `vibration_mms` has no single standardised broadcast SPN (it is a modern
> telematics add-on, not a core J1939-71 engine parameter); it is included as a
> Modern-era signal because predictive-maintenance fleets commonly add it.

## Documented cross-signal correlations (asserted in tests)

These **signs** are the credibility of the dataset; they are implemented in
[`generators.py`](../src/can_telemetry_forge/signals/generators.py) and asserted in
[`tests/test_signals.py`](../tests/test_signals.py) so they cannot silently drift.

- fuel rate **↑** with load · RPM
- coolant temp **↑** with ambient + load; **↑** with cooling-system wear (bounded by range)
- oil pressure **↓** with wear; **↑** with RPM
- EGT **↑** at altitude (thinner air) and under sustained high load
- boost pressure **↓** at altitude
- vibration **↑** with terrain roughness and accumulated wear
- runtime hours **monotonic non-decreasing**

## Determinism

All signals come from a single seeded `numpy` generator threaded in by the caller
(ADR-005). Same era + drivers + seed → identical arrays. The hour-meter
(`runtime_hours`) and `equipment_age_days` are noise-free by construction.

## Label & anomaly columns (in `readings`)

Beyond the signal columns, each reading row carries ground-truth labels:

- `failure_within_h` (0/1) and `failure_mode` (`overheat` / `oil_starve` /
  `bearing`, else empty) — the multi-mode failure target (ADR-009).
- `anomaly_type` — the labeled defect on the row (else empty): `obvious_outlier` /
  `joint_outlier` / `sensor_stuck` / `sensor_drift` / `sensor_dropout`
  (ADR-006/-016). One per row by injector priority; era-`NULL` cells are never
  targeted.
- `anomaly_signal` — which signal carries that defect (empty if none).
- `is_outlier` (bool) — back-compat rollup: true where the row carries a
  *value-distorting* defect (everything except `sensor_dropout`, which blanks to
  `NULL`).

## Not yet in Tier 1 (later phases)

- Per-model SPN whitelists (finer than coarse eras) — F5.
- Raw CAN frame layout (byte/bit positions per PGN) — would activate the PGN column.
- CAN-frame fault patterns (malformed/implausible frames) — F5, once the frame
  encoder exists; a new `anomaly_type` value, no schema change.
