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
The **PGN** column was recorded inert in F1 (ADR-013); F6 (ADR-019) activated it with
a `FrameLayout` (byte/bit placement + scaling/offset, see "Frame layout" below), used
by the frame encoder/decoder and the Tier-3 CAN-frame faults. The value *generators*
still emit engineering-unit time-series and don't read the layout.

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

## Frame layout (J1939 byte/bit placement — F6, ADR-019)

The **bus signals** carry a `FrameLayout` describing where the SPN sits in its PGN
frame and how a raw integer maps to the engineering value
(`value = raw × scale + offset`, little-endian). The frame encoder/decoder
(`signals/frames.py`) uses it; the Tier-3 CAN-frame faults corrupt the encoded bytes
and decode back. Non-bus fields (`runtime_hours`, `vibration_mms`,
`equipment_age_days`) have no layout. All Tier-1 fields are byte-aligned; the two
top raw codes per field are reserved for J1939 *not-available* / *error* (both decode
to `NULL`).

| Field | PGN | Frame | Start bit | Bits | Scale | Offset |
|---|---|---|---|---|---|---|
| `engine_speed_rpm` | 61444 (EEC1) | bytes 4–5 | 24 | 16 | 0.125 | 0 |
| `coolant_temp_c` | 65262 (ET1) | byte 1 | 0 | 8 | 1 | −40 |
| `oil_pressure_kpa` | 65263 (EFL/P1) | byte 4 | 24 | 8 | 4 | 0 |
| `engine_load_pct` | 61443 (EEC2) | byte 3 | 16 | 8 | 1 | 0 |
| `fuel_rate_lph` | 65266 (LFE) | bytes 1–2 | 0 | 16 | 0.05 | 0 |
| `boost_pressure_kpa` | 65270 (IC1) | byte 2 | 8 | 8 | 2 | 0 |
| `egt_c` | 65270 (IC1) | bytes 6–7 | 40 | 16 | 0.03125 | −273 |
| `def_level_pct` | 65110 (AT1T1I) | byte 1 | 0 | 8 | 0.4 | 0 |

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
  `joint_outlier` / `sensor_stuck` / `sensor_drift` / `sensor_dropout` (F3) plus the
  Tier-3 CAN-frame faults `can_frame_corrupt` / `can_frame_stale` /
  `can_frame_error_indicator` / `can_frame_truncated` (F6, ADR-019). One per row by
  injector priority; era-`NULL` cells are never targeted.
- `anomaly_signal` — which signal carries that defect (empty if none).
- `is_outlier` (bool) — back-compat rollup: true where the row carries a
  *value-distorting* defect (`obvious_outlier`, `joint_outlier`, `sensor_stuck`,
  `sensor_drift`, `can_frame_corrupt`, `can_frame_stale`). The NULL-blanking defects
  (`sensor_dropout`, `can_frame_error_indicator`, `can_frame_truncated`) are labeled
  in `anomaly_type` but not flagged here. (It is a per-row rollup over *all*
  distorting cells, so a row can be `is_outlier` while a higher-priority
  NULL-blanking defect won its categorical.)

### `can_frames` (opt-in side table — F6)

With `--emit-raw-frames` (`emit_raw_frames` in config), the byte-level corrupted
J1939 frames behind each `can_frame_*` defect are written to a `can_frames` table:
`unit_id`, `t_index`, `timestamp_h`, `signal`, `anomaly_type`, and the frame as
uppercase hex (`frame_hex`). Absent otherwise — the decoded `readings` are the
product; this is a byte-level artifact for QA/teaching.

## Not yet in Tier 1 (later phases)

- Per-model SPN whitelists (finer than coarse eras) — a Tier-2 refinement (F5 took
  the first step with a per-model `build_year_min` capability floor).
- ~~Raw CAN frame layout (byte/bit positions per PGN)~~ → done (F6, ADR-019): see
  "Frame layout" above; the encoder/decoder lives in `signals/frames.py`.
- ~~CAN-frame fault patterns (malformed/implausible frames)~~ → done (F6, ADR-019):
  four `can_frame_*` `anomaly_type` values, no schema change.
