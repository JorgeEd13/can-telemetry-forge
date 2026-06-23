"""The fleet simulator: compose F1 across the fleet → tidy tables (F2).

This is the orchestration layer. From a validated
:class:`~can_telemetry_forge.config.ForgeConfig` it:

1. builds the fleet (:func:`.fleet.build_fleet`);
2. for each unit, synthesises its driver series (:func:`.drivers.drivers_for_unit`),
   runs the F1 per-signal model (``generate_unit``), derives the multi-mode failure
   label **from the clean signals** (ADR-009), then injects obvious labeled
   outliers (ADR-006) *after* labelling so a glitch is never mistaken for a failure
   signature;
3. assembles a **tidy long** reading table plus **dimension tables** (units,
   vehicle classes, regions, contracts) and a **label table**.

Determinism (ADR-005). One master :class:`numpy.random.SeedSequence` is built from
``config.seed`` and **spawned** into independent child sequences — one for fleet
composition and one per unit per stage (signals / labels / outliers). Independent
streams mean a unit's data never depends on how many units preceded it, yet the
whole dataset is byte-identical for a given config + seed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..anomalies import inject_obvious_outliers
from ..config import ForgeConfig
from ..labels import derive_unit_labels
from ..signals import generate_unit, signal_names
from .drivers import drivers_for_unit
from .fleet import Unit, build_fleet

# Child-stream ordering per unit (kept explicit so the seeding is auditable).
_STREAMS_PER_UNIT = 4  # drivers, signals, labels, outliers
_STREAM_DRIVERS, _STREAM_SIGNALS, _STREAM_LABELS, _STREAM_OUTLIERS = 0, 1, 2, 3


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
    regions: pd.DataFrame
    contracts: pd.DataFrame
    config: ForgeConfig


def _dimension_tables(config: ForgeConfig, units: list[Unit]) -> dict[str, pd.DataFrame]:
    f = config.fleet
    vehicle_classes = pd.DataFrame(
        [
            {"vehicle_class_id": vc.id, "label": vc.label, "duty_base": vc.duty_base, "wear_rate": vc.wear_rate}
            for vc in f.vehicle_classes
        ]
    )
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
        "regions": regions,
        "contracts": contracts,
        "units": units_df,
    }


def simulate(config: ForgeConfig) -> SimulatedDataset:
    """Generate the full Tier-1 dataset for ``config``. Deterministic in the seed."""
    config = config.validate()
    region_by_id = {r.id: r for r in config.fleet.regions}
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

    for i, unit in enumerate(units):
        region = region_by_id[unit.region_id]
        base = i * _STREAMS_PER_UNIT
        rng_drivers = np.random.default_rng(unit_seqs[base + _STREAM_DRIVERS])
        rng_signals = np.random.default_rng(unit_seqs[base + _STREAM_SIGNALS])
        rng_labels = np.random.default_rng(unit_seqs[base + _STREAM_LABELS])
        rng_outliers = np.random.default_rng(unit_seqs[base + _STREAM_OUTLIERS])

        drivers = drivers_for_unit(unit, region, n, step_h, rng_drivers)
        signals = generate_unit(unit.era, drivers, rng_signals)

        # Label from the CLEAN signals (before outliers are injected).
        labels = derive_unit_labels(
            signals, drivers.wear, step_h, config.failure_horizon_h, rng_labels
        )

        # Inject obvious labeled outliers AFTER labelling.
        outlier_masks = inject_obvious_outliers(signals, config.obvious_outlier_rate, rng_outliers)
        is_outlier = np.zeros(n, dtype=bool)
        for mask in outlier_masks.values():
            is_outlier |= mask

        frame = {"unit_id": unit.unit_id, "t_index": np.arange(n, dtype=np.int32)}
        frame["timestamp_h"] = np.arange(n, dtype=float) * step_h
        for name in cols:
            values = signals[name]
            frame[name] = values if values is not None else np.full(n, np.nan)
        frame["failure_within_h"] = labels.failure_within_h
        frame["failure_mode"] = labels.failure_mode
        frame["is_outlier"] = is_outlier
        frames.append(pd.DataFrame(frame))

    readings = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=["unit_id", "t_index", "timestamp_h", *cols])
    )

    dims = _dimension_tables(config, units)
    return SimulatedDataset(
        readings=readings,
        units=dims["units"],
        vehicle_classes=dims["vehicle_classes"],
        regions=dims["regions"],
        contracts=dims["contracts"],
        config=config,
    )


__all__ = ["SimulatedDataset", "simulate"]
