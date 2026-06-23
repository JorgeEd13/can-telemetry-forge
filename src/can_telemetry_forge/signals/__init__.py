"""The J1939-grounded signal model (F1).

Public surface of the signal layer: the declarative signal registry, the
capability-era gating, and the deterministic per-unit generator. The fleet
simulator (F2) composes these across many units; downstream consumers can import
the registry to introspect the schema (SPN/unit/range/era) without generating.
"""

from __future__ import annotations

from .spec import (
    Era,
    SignalSpec,
    TIER1_SIGNALS,
    SIGNALS_BY_NAME,
    signal_names,
    get_spec,
)
from .eras import (
    era_for_model_year,
    supports,
    supported_signal_names,
    gated_signal_names,
)
from .generators import DriverSeries, generate_unit

__all__ = [
    "Era",
    "SignalSpec",
    "TIER1_SIGNALS",
    "SIGNALS_BY_NAME",
    "signal_names",
    "get_spec",
    "era_for_model_year",
    "supports",
    "supported_signal_names",
    "gated_signal_names",
    "DriverSeries",
    "generate_unit",
]
