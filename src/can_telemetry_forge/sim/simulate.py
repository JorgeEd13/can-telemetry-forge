"""The fleet simulator: compose F1 across the fleet → tidy tables (F2).

This is the orchestration layer. From a validated
:class:`~can_telemetry_forge.config.ForgeConfig` it:

1. builds the fleet (:func:`.fleet.build_fleet`);
2. for each unit, synthesises its driver series (:func:`.drivers.drivers_for_unit`),
   runs the F1 per-signal model (``generate_unit``), derives the multi-mode failure
   label **from the clean signals** (ADR-009), then injects the registry of labeled
   defects (ADR-006/-016 — outliers + sensor faults) *after* labelling so a glitch
   is never mistaken for a failure signature;
3. assembles a **tidy long** reading table plus **dimension tables** (units,
   vehicle classes, regions, contracts) and a **label table**.

Determinism (ADR-005). One master :class:`numpy.random.SeedSequence` is built from
``config.seed`` and **spawned** into independent child sequences — one for fleet
composition and one per unit per stage (drivers / signals / labels / one per
anomaly injector). Independent
streams mean a unit's data never depends on how many units preceded it, yet the
whole dataset is byte-identical for a given config + seed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..anomalies import ANOMALY_TYPES, apply_anomalies
from ..config import ForgeConfig
from ..labels import FAILURE_MODES, apply_degradation, derive_unit_labels
from ..signals import generate_unit, signal_names
from .drivers import drivers_for_unit
from .fleet import Unit, build_fleet


def _merge_hazard_mults(*mults: dict[str, float]) -> dict[str, float]:
    """Combine per-mode hazard multipliers multiplicatively (model × season).

    Each input maps a failure mode → multiplier; absent modes are ``1.0``. The
    result carries every known :data:`FAILURE_MODES` mode (so callers can index it
    safely) as the product across inputs.
    """
    merged = {mode: 1.0 for mode in FAILURE_MODES}
    for m in mults:
        for mode, value in m.items():
            if mode in merged:
                merged[mode] *= value
    return merged

# Child-stream ordering per unit (kept explicit so the seeding is auditable). The
# first three are the F2 stages; each anomaly injector then gets its own stream so
# adding/removing a defect type never shifts another stage's seed.
_STREAM_DRIVERS, _STREAM_SIGNALS, _STREAM_LABELS = 0, 1, 2
_N_BASE_STREAMS = 3
_STREAMS_PER_UNIT = _N_BASE_STREAMS + len(ANOMALY_TYPES)


@dataclass(frozen=True)
class SimulatedDataset:
    """The in-memory result of a generation run (writers turn it into files).

    Attributes:
        readings: tidy long table — one row per (unit, timestamp) with every
            signal column (era-gated signals are NaN/NULL) plus its labels.
        units / vehicle_classes / regions / contracts: dimension tables.
        config: the config that produced it (for provenance in the writers).
    """

    readings: pd.DataFrame
    units: pd.DataFrame
    vehicle_classes: pd.DataFrame
    equipment_models: pd.DataFrame
    regions: pd.DataFrame
    contracts: pd.DataFrame
    # The byte-level corrupted CAN frames (F6, ADR-019). Always built; empty unless a
    # frame fault fired. Written as a side table only when ``config.emit_raw_frames``.
    can_frames: pd.DataFrame
    config: ForgeConfig


def _dimension_tables(config: ForgeConfig, units: list[Unit]) -> dict[str, pd.DataFrame]:
    f = config.fleet
    vehicle_classes = pd.DataFrame(
        [
            {"vehicle_class_id": vc.id, "label": vc.label, "duty_base": vc.duty_base, "wear_rate": vc.wear_rate}
            for vc in f.vehicle_classes
        ]
    )
    equipment_models = pd.DataFrame(
        [
            {
                "model_id": m.id,
                "label": m.label,
                "vehicle_class_id": m.vehicle_class_id,
                "hazard_overheat": m.hazard_mult.get("overheat", 1.0),
                "hazard_oil_starve": m.hazard_mult.get("oil_starve", 1.0),
                "hazard_bearing": m.hazard_mult.get("bearing", 1.0),
                "coolant_offset_c": m.coolant_offset_c,
                "oil_offset_kpa": m.oil_offset_kpa,
                "vibration_offset_mms": m.vibration_offset_mms,
                # Nullable int: a model that doesn't pin a capability floor is NULL,
                # not 0 — and stays a clean integer column across all writers.
                "build_year_min": (
                    pd.NA if m.build_year_min is None else m.build_year_min
                ),
            }
            for m in f.equipment_models
        ],
        columns=[
            "model_id", "label", "vehicle_class_id", "hazard_overheat",
            "hazard_oil_starve", "hazard_bearing", "coolant_offset_c",
            "oil_offset_kpa", "vibration_offset_mms", "build_year_min",
        ],
    ).astype({"build_year_min": "Int64"})
    regions = pd.DataFrame(
        [
            {
                "region_id": r.id,
                "label": r.label,
                "ambient_c_mean": r.ambient_c_mean,
                "altitude_m": r.altitude_m,
                "terrain_roughness": r.terrain_roughness,
                "wear_modifier": r.wear_modifier,
                "source": r.source,
            }
            for r in f.regions
        ]
    )
    contracts = pd.DataFrame(
        [
            {"contract_id": c.id, "label": c.label, "region_id": c.region_id, "expected_units": c.units}
            for c in f.contracts
        ]
    )
    units_df = pd.DataFrame(
        [
            {
                "unit_id": u.unit_id,
                "vehicle_class_id": u.vehicle_class_id,
                "model_id": u.model_id,
                "contract_id": u.contract_id,
                "region_id": u.region_id,
                "build_year": u.build_year,
                "era": u.era.name,
                "duty_base": u.duty_base,
                "runtime_start_h": u.runtime_start_h,
                "age_days": u.age_days,
            }
            for u in units
        ]
    )
    return {
        "vehicle_classes": vehicle_classes,
        "equipment_models": equipment_models,
        "regions": regions,
        "contracts": contracts,
        "units": units_df,
    }


def simulate(config: ForgeConfig) -> SimulatedDataset:
    """Generate the full Tier-1 dataset for ``config``. Deterministic in the seed."""
    config = config.validate()
    region_by_id = {r.id: r for r in config.fleet.regions}
    anomaly_rates = config.resolved_anomaly_rates()
    n = config.n_steps()
    step_h = config.step_hours()

    master = np.random.SeedSequence(config.seed)
    (fleet_seq,) = master.spawn(1)  # one child sequence for fleet composition
    units = build_fleet(config.fleet, np.random.default_rng(fleet_seq))

    # One spawned child sequence per unit per stage, deterministically derived from
    # the master regardless of fleet size (units don't perturb each other's
    # streams). Spawning again advances the master's counter past the fleet child,
    # so these never collide with ``fleet_seq``.
    unit_seqs = master.spawn(len(units) * _STREAMS_PER_UNIT)

    cols = signal_names()
    frames: list[pd.DataFrame] = []
    # (unit_id, t_index, timestamp_h, signal, anomaly_type, frame_hex) for the F6
    # raw-frame side artifact; populated only by CAN-frame faults (ADR-019).
    frame_rows: list[dict] = []

    for i, unit in enumerate(units):
        region = region_by_id[unit.region_id]
        base = i * _STREAMS_PER_UNIT
        rng_drivers = np.random.default_rng(unit_seqs[base + _STREAM_DRIVERS])
        rng_signals = np.random.default_rng(unit_seqs[base + _STREAM_SIGNALS])
        rng_labels = np.random.default_rng(unit_seqs[base + _STREAM_LABELS])
        # One seeded stream per anomaly injector (ADR-016), in registry order.
        rng_anomalies = {
            atype: np.random.default_rng(unit_seqs[base + _N_BASE_STREAMS + k])
            for k, atype in enumerate(ANOMALY_TYPES)
        }

        drivers = drivers_for_unit(unit, region, config.season, n, step_h, rng_drivers)
        signals = generate_unit(unit.era, drivers, rng_signals)

        # Per-mode hazard multiplier = the unit's equipment-model reliability × the
        # run's season (Tier-2, F5). Missing modes default to 1.0 downstream.
        hazard_mult = _merge_hazard_mults(unit.hazard_mult, config.season.hazard_mult)

        # Label failures from the CLEAN signals (before any defect is injected) so a
        # glitch is never mistaken for a failure signature (ADR-009).
        labels = derive_unit_labels(
            signals, drivers.wear, step_h, config.failure_horizon_h, rng_labels, hazard_mult
        )

        # Inject the progressive pre-failure degradation into the winning mode's
        # signature signals across the horizon window (ADR-020) — AFTER the clean-signal
        # label (so the label stays ADR-009-clean) and BEFORE unrelated defects, since
        # the drift IS the failure physics, not a glitch.
        signals = apply_degradation(signals, labels)

        # Inject all labeled defects AFTER labelling (ADR-006/-016).
        anomalies = apply_anomalies(signals, anomaly_rates, rng_anomalies, n)

        frame = {"unit_id": unit.unit_id, "t_index": np.arange(n, dtype=np.int32)}
        frame["timestamp_h"] = np.arange(n, dtype=float) * step_h
        for name in cols:
            values = signals[name]
            frame[name] = values if values is not None else np.full(n, np.nan)
        frame["failure_within_h"] = labels.failure_within_h
        frame["failure_mode"] = labels.failure_mode
        frame["is_outlier"] = anomalies.is_outlier
        frame["anomaly_type"] = anomalies.anomaly_type
        frame["anomaly_signal"] = anomalies.anomaly_signal
        frames.append(pd.DataFrame(frame))

        # Collect the byte-level corrupted frames (F6). Built regardless of the
        # ``emit_raw_frames`` flag (cheap when no frame fault fired); the writer
        # decides whether to persist it.
        for t_index, signal, atype, frame_hex in anomalies.frame_records():
            frame_rows.append(
                {
                    "unit_id": unit.unit_id,
                    "t_index": t_index,
                    "timestamp_h": t_index * step_h,
                    "signal": signal,
                    "anomaly_type": atype,
                    "frame_hex": frame_hex,
                }
            )

    readings = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(
            columns=[
                "unit_id", "t_index", "timestamp_h", *cols,
                "failure_within_h", "failure_mode", "is_outlier",
                "anomaly_type", "anomaly_signal",
            ]
        )
    )

    can_frames = pd.DataFrame(
        frame_rows,
        columns=["unit_id", "t_index", "timestamp_h", "signal", "anomaly_type", "frame_hex"],
    )

    dims = _dimension_tables(config, units)
    return SimulatedDataset(
        readings=readings,
        units=dims["units"],
        vehicle_classes=dims["vehicle_classes"],
        equipment_models=dims["equipment_models"],
        regions=dims["regions"],
        contracts=dims["contracts"],
        can_frames=can_frames,
        config=config,
    )


__all__ = ["SimulatedDataset", "simulate"]
