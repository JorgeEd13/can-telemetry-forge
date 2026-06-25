"""Fleet composition: sample the operator's units from the config catalog (F2).

Turns the declarative catalog (:class:`~can_telemetry_forge.config.FleetSpec`)
into a concrete, **seeded** set of :class:`Unit` records — the "who exists and
where they work" layer of DATA_DESIGN §3. A real operator is not a uniform pool:
this models the vehicle-class **mix**, a realistic **age curve** (a tail of older
units still in service, which also drives CAN capability era), and per-contract
**fleet sizes** that vary around their expected value.

Determinism (ADR-005): every draw flows from the one rng passed in. Same config +
seed → the identical fleet, unit-for-unit.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import EquipmentModel, FleetSpec
from ..signals import Era, era_for_model_year


@dataclass(frozen=True)
class Unit:
    """One physical machine in the fleet.

    Attributes:
        unit_id: stable identifier (``"u0001"`` …) in creation order.
        vehicle_class_id / contract_id / region_id: catalog assignments.
        model_id: the equipment model (Tier-2, F5); empty when the unit's class has
            no models catalogued (class-only profile).
        build_year: model year → ``era`` (CAN capability, ADR-008).
        era: capability era derived from ``build_year``.
        duty_base: this unit's duty-cycle centre in ``[0, 1]`` (class base +
            contract bias), clamped.
        wear_rate: per-class wear-accumulation multiplier.
        runtime_start_h: hour-meter reading at the window start (older units have
            accrued more).
        age_days: equipment age in days at the window start.
        coolant_offset_c / oil_offset_kpa / vibration_offset_mms: the model's
            baseline signature offsets (0.0 for class-only units).
        hazard_mult: the model's per-failure-mode hazard multipliers (empty for
            class-only units; missing modes default to 1.0 downstream).
    """

    unit_id: str
    vehicle_class_id: str
    contract_id: str
    region_id: str
    model_id: str
    build_year: int
    era: Era
    duty_base: float
    wear_rate: float
    runtime_start_h: float
    age_days: float
    coolant_offset_c: float = 0.0
    oil_offset_kpa: float = 0.0
    vibration_offset_mms: float = 0.0
    hazard_mult: dict[str, float] = field(default_factory=dict)


# Reference "now" for age computation. Fixed so the dataset is reproducible and
# self-contained (no dependence on wall-clock); the window is a relative span.
_REFERENCE_YEAR = 2025
_HOURS_PER_YEAR = 24.0 * 365.25
# Older machines have, on average, run more hours per year of life (survivorship +
# the fact that a kept-in-service legacy unit tends to be a worked unit).
_ANNUAL_RUNTIME_MEAN_H = 1800.0
_ANNUAL_RUNTIME_SD_H = 300.0


def _draw_build_year(spec: FleetSpec, rng: np.random.Generator, year_min: int) -> int:
    """Triangular age curve: mode skewed recent, tail of legacy units.

    ``year_min`` is the effective lower bound (a model may raise it above the
    fleet floor — a model that only ever shipped Modern hardware). The triangular
    mode is clamped into ``[year_min, build_year_max]`` so the draw stays valid.
    """
    lo = max(spec.build_year_min, year_min)
    mode = int(np.clip(spec.build_year_mode, lo, spec.build_year_max))
    year = rng.triangular(lo, mode, spec.build_year_max + 1)
    return int(np.clip(np.floor(year), lo, spec.build_year_max))


def _contract_unit_count(expected: int, sd_frac: float, rng: np.random.Generator) -> int:
    """Actual contract size, drawn around the expected value (≥ 1)."""
    drawn = rng.normal(expected, max(expected * sd_frac, 1e-9))
    return int(max(1, round(drawn)))


def build_fleet(spec: FleetSpec, rng: np.random.Generator) -> list[Unit]:
    """Sample the full list of units for the operator, deterministically.

    For each contract: draw an actual unit count around its expected size, then for
    each unit draw a vehicle class (by the normalised mix), a build year (the age
    curve), and derive era / duty / runtime / age. Units are numbered in creation
    order across contracts.
    """
    class_ids = [vc.id for vc in spec.vehicle_classes]
    class_by_id = {vc.id: vc for vc in spec.vehicle_classes}
    weights = np.array([spec.vehicle_mix.get(cid, 0.0) for cid in class_ids], dtype=float)
    weights = weights / weights.sum()

    # Models grouped by class (Tier-2, F5). A class with no catalogued models keeps
    # a single generic (class-only) profile — model_id stays empty.
    models_by_class: dict[str, list[EquipmentModel]] = {}
    for m in spec.equipment_models:
        models_by_class.setdefault(m.vehicle_class_id, []).append(m)

    units: list[Unit] = []
    counter = 0
    for contract in spec.contracts:
        n = _contract_unit_count(contract.units, spec.units_per_contract_sd_frac, rng)
        for _ in range(n):
            counter += 1
            cls = class_by_id[class_ids[int(rng.choice(len(class_ids), p=weights))]]

            # Pick the unit's model (uniform over the class's models), then draw a
            # build year respecting the model's capability floor if it sets one.
            class_models = models_by_class.get(cls.id, [])
            model = class_models[int(rng.integers(len(class_models)))] if class_models else None
            year_min = model.build_year_min if (model and model.build_year_min) else spec.build_year_min
            build_year = _draw_build_year(spec, rng, year_min)
            era = era_for_model_year(build_year)

            duty = float(np.clip(cls.duty_base + contract.duty_bias, 0.05, 1.0))
            age_years = max(0.0, _REFERENCE_YEAR - build_year + rng.uniform(0.0, 1.0))
            annual_h = max(0.0, rng.normal(_ANNUAL_RUNTIME_MEAN_H, _ANNUAL_RUNTIME_SD_H))
            runtime_start_h = age_years * annual_h

            units.append(
                Unit(
                    unit_id=f"u{counter:04d}",
                    vehicle_class_id=cls.id,
                    contract_id=contract.id,
                    region_id=contract.region_id,
                    model_id=model.id if model else "",
                    build_year=build_year,
                    era=era,
                    duty_base=duty,
                    wear_rate=cls.wear_rate,
                    runtime_start_h=runtime_start_h,
                    age_days=age_years * 365.25,
                    coolant_offset_c=model.coolant_offset_c if model else 0.0,
                    oil_offset_kpa=model.oil_offset_kpa if model else 0.0,
                    vibration_offset_mms=model.vibration_offset_mms if model else 0.0,
                    hazard_mult=dict(model.hazard_mult) if model else {},
                )
            )
    return units


__all__ = ["Unit", "build_fleet"]
