"""The J1939-grounded signal model (F1).

Public surface of the signal layer: the declarative signal registry, the
capability-era gating, and the deterministic per-unit generator. The fleet
simulator (F2) composes these across many units; downstream consumers can import
the registry to introspect the schema (SPN/unit/range/era) without generating.
"""

from __future__ import annotations

from .eras import (
    era_for_model_year,
    gated_signal_names,
    supported_signal_names,
    supports,
)
from .frames import (
    decode_signal_frame,
    encode_signal_frame,
    frame_to_hex,
    raw_to_value,
    value_to_raw,
)
from .generators import DriverSeries, generate_unit
from .spec import (
    SIGNALS_BY_NAME,
    TIER1_SIGNALS,
    Era,
    FrameLayout,
    SignalSpec,
    get_spec,
    signal_names,
)

__all__ = [
    "SIGNALS_BY_NAME",
    "TIER1_SIGNALS",
    "DriverSeries",
    "Era",
    "FrameLayout",
    "SignalSpec",
    "decode_signal_frame",
    "encode_signal_frame",
    "era_for_model_year",
    "frame_to_hex",
    "gated_signal_names",
    "generate_unit",
    "get_spec",
    "raw_to_value",
    "signal_names",
    "supported_signal_names",
    "supports",
    "value_to_raw",
]
