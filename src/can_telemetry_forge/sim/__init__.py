"""Fleet simulator (F2): compose the F1 signal model across a realistic fleet.

The pieces:

* :mod:`.fleet` — sample the operator's units (vehicle mix, age curve, contract
  sizes) deterministically from the config catalog.
* :mod:`.drivers` — synthesise each unit's :class:`~can_telemetry_forge.signals.DriverSeries`
  (duty cycle, ambient/altitude/terrain from its region, accumulated wear).
* :mod:`.simulate` — run the F1 ``generate_unit`` over every unit × the time
  window, derive the failure label and obvious outliers, and assemble the tidy
  long table plus dimension tables.
"""

from __future__ import annotations

from .fleet import Unit, build_fleet
from .drivers import drivers_for_unit
from .simulate import SimulatedDataset, simulate

__all__ = [
    "Unit",
    "build_fleet",
    "drivers_for_unit",
    "SimulatedDataset",
    "simulate",
]
