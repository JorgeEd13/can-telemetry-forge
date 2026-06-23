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

from dataclasses import dataclass

import numpy as np

from ..config import FleetSpec
from ..signals import Era, era_for_model_year


@dataclass(frozen=True)
class Unit:
    """One physical machine in the fleet.

    Attributes:
        unit_id: stable identifier (``"u0001"`` …) in creation order.
        vehicle_class_id / contract_id / region_id: catalog assignments.
        build_year: model year → ``era`` (CAN capability, ADR-008).
        era: capability era derived from ``build_year``.
        duty_base: this unit's duty-cycle centre in ``[0, 1]`` (class base +
            contract bias), clamped.
        wear_rate: per-class wear-accumulation multiplier.
        runtime_start_h: hour-meter reading at the window start (older units have
            accrued more).
        age_days: equipment age in days at the window start.
    """

    unit_id: str
    vehicle_class_id: str
    contract_id: str
    region_id: str
    build_year: int
    era: Era
    duty_base: float
    wear_rate: float
    runtime_start_h: float
    age_days: float


# Reference "now" for age computation. Fixed so the dataset is reproducible and
# self-contained (no dependence on wall-clock); the window is a relative span.
_REFERENCE_YEAR = 2025
_HOURS_PER_YEAR = 24.0 * 365.25
# Older machines have, on average, run more hours per year of life (survivorship +
# the fact that a kept-in-service legacy unit tends to be a worked unit).
_ANNUAL_RUNTIME_MEAN_H = 1800.0
_ANNUAL_RUNTIME_SD_H = 300.0


def _draw_build_year(spec: FleetSpec, rng: np.random.Generator) -> int:
    """Triangular age curve: mode skewed recent, tail of legacy units."""
    year = rng.triangular(spec.build_year_min, spec.build_year_mode, spec.build_year_max + 1)
    return int(np.clip(np.floor(year), spec.build_year_min, spec.build_year_max))


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

    contract_by_id = {c.id: c for c in spec.contracts}

    units: list[Unit] = []
    counter = 0
    for contract in spec.contracts:
        n = _contract_unit_count(contract.units, spec.units_per_contract_sd_frac, rng)
        for _ in range(n):
            counter += 1
            cls = class_by_id[class_ids[int(rng.choice(len(class_ids), p=weights))]]
            build_year = _draw_build_year(spec, rng)
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
                    build_year=build_year,
                    era=era,
                    duty_base=duty,
                    wear_rate=cls.wear_rate,
                    runtime_start_h=runtime_start_h,
                    age_days=age_years * 365.25,
                )
            )
    # contract_by_id kept for callers that join dimensions; unused here directly.
    del contract_by_id
    return units


__all__ = ["Unit", "build_fleet"]
