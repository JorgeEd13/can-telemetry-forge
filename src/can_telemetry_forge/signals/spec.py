"""Declarative registry of the Tier-1 CAN signals.

This module is the **single source of truth** for *what* signals exist and *how*
they are described — their SAE J1939 identity (SPN, optionally PGN), engineering
unit, valid operating range, capability era, and which other signals they depend
on. It is deliberately data, not behaviour: the per-signal *generators*
(``generators.py``) and the era *gating* (``eras.py``) read this registry, and the
``DATA_DICTIONARY.md`` is generated to match it.

Why a registry of small self-describing objects rather than hard-coded constants
scattered through the generators (ADR-012): each signal carries its own metadata
and dependency list, so adding/removing a signal — or, in the long run, describing
a *different* domain's signal set — is a local edit to one ``SignalSpec`` plus its
generator, not a cross-cutting change. The dependency graph (``drivers``) also lets
the simulator compute signals in a valid order.

Grounding: SPN numbers, units, scaling and ranges are from the publicly documented
SAE J1939-71 standard (see ``docs/DATA_DICTIONARY.md`` for the cited values). No
proprietary source is used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Era(Enum):
    """CAN capability era of a unit's electronics (ADR-008).

    Ordered oldest → newest. A unit of a given era reports the SPNs introduced in
    its era *and every earlier era*; newer SPNs are structurally absent (emitted
    as NULL, never zero — see ``eras.py``). ``RUNTIME_ALWAYS`` is a sentinel for
    fields that are not era-gated at all (e.g. equipment age, runtime hours): they
    are available to every unit regardless of CAN capability.
    """

    LEGACY = 0  # pre-2005: core engine only
    MID = 1  # 2005–2014: + load, fuel rate, boost
    MODERN = 2  # 2015+: + EGT, DEF, vibration, after-treatment
    RUNTIME_ALWAYS = -1  # not gated by CAN capability at all

    @property
    def is_can_era(self) -> bool:
        """True for the real capability tiers, False for the always-on sentinel."""
        return self.value >= 0


@dataclass(frozen=True)
class FrameLayout:
    """Byte/bit placement of one SPN within its J1939 PGN frame (F6, ADR-019).

    This is the seam ADR-013 left open: the PGN was recorded inert; this completes
    its J1939 identity with the *physical* layout — where in the (≤8-byte) frame the
    parameter sits and how a raw integer maps to the engineering value. It is **data,
    not behaviour** (mirroring ADR-012): the frame encoder/decoder reads it, the
    value *generators* still ignore it (the ADR-013 inert-PGN test keeps holding).

    The encoder/decoder relation is the standard J1939 linear one::

        raw  = round((value - offset) / scale)          # value → raw integer
        value = raw * scale + offset                      # raw integer → value

    Attributes:
        start_bit: 0-based bit position of the field's least-significant bit within
            the frame (bit 0 = LSB of byte 0). J1939 fields are byte-aligned in the
            Tier-1 set, so this is always a multiple of 8.
        bit_len: field width in bits (8 or 16 for the Tier-1 signals).
        scale: engineering units per raw bit (the J1939 resolution).
        offset: engineering-unit offset added after scaling (e.g. −40 °C, −273 °C).
        byte_order: ``"little"`` (J1939's intel/LSB-first convention) for every
            multi-byte Tier-1 field; kept explicit so the decoder is unambiguous.
        frame_bytes: the PGN's transmitted length in bytes (8 for the Tier-1 PGNs).
    """

    start_bit: int
    bit_len: int
    scale: float
    offset: float
    byte_order: str = "little"
    frame_bytes: int = 8


@dataclass(frozen=True)
class SignalSpec:
    """Self-describing definition of one telemetry signal.

    Attributes:
        name: tidy-table column name (snake_case).
        spn: SAE J1939 Suspect Parameter Number, or ``None`` for non-J1939 derived
            fields (runtime hours, equipment age) that have no bus parameter.
        unit: engineering unit the generator emits in.
        min_value / max_value: documented valid operating range (engineering units),
            used both to clamp generated values and to assert ranges in tests.
        era: the capability era that introduces this signal. ``Era.RUNTIME_ALWAYS``
            marks a non-gated field.
        drivers: names of the signals/inputs this one is correlated with. Documents
            the dependency graph and is asserted (by sign) in the tests.
        pgn: SAE J1939 Parameter Group Number that carries this SPN. Recorded since
            F1 (ADR-013); from F6 a J1939 ``layout`` completes its frame identity.
        layout: byte/bit placement of this SPN within its PGN frame (ADR-019), or
            ``None`` for non-bus derived fields (runtime, age, vibration add-on).
            The frame encoder/decoder reads it; the value generators still don't.
        description: one-line human description for the data dictionary.
    """

    name: str
    spn: int | None
    unit: str
    min_value: float
    max_value: float
    era: Era
    drivers: tuple[str, ...] = ()
    pgn: int | None = None
    layout: FrameLayout | None = None
    description: str = ""


# ---------------------------------------------------------------------------
# The Tier-1 signal set (DATA_DESIGN §5).
#
# SPN / PGN / unit / scaling / range are the standard, widely published
# SAE J1939-71 definitions. The ``drivers`` encode the documented cross-signal
# correlations from DATA_DESIGN §5 (their signs are asserted in tests).
# ---------------------------------------------------------------------------

# Ambient temperature is an environment input, not a CAN signal; it is listed as a
# driver name so correlations can reference it. The simulator supplies it (F2);
# the F1 generators accept it as an input.
DRIVER_AMBIENT_C = "ambient_c"
DRIVER_ALTITUDE_M = "altitude_m"
DRIVER_TERRAIN_ROUGHNESS = "terrain_roughness"
DRIVER_DUTY = "duty_cycle"
DRIVER_WEAR = "wear"  # accumulated wear state in [0, 1]

TIER1_SIGNALS: tuple[SignalSpec, ...] = (
    SignalSpec(
        name="engine_speed_rpm",
        spn=190,
        pgn=61444,  # EEC1
        unit="rpm",
        min_value=0.0,
        max_value=8031.875,  # J1939 max raw 64255 × 0.125 rpm/bit
        era=Era.LEGACY,
        drivers=(DRIVER_DUTY,),
        # EEC1 bytes 4–5 (start bit 24), 16-bit, 0.125 rpm/bit.
        layout=FrameLayout(start_bit=24, bit_len=16, scale=0.125, offset=0.0),
        description="Engine speed. J1939 0.125 rpm/bit.",
    ),
    SignalSpec(
        name="coolant_temp_c",
        spn=110,
        pgn=65262,  # ET1
        unit="degC",
        min_value=-40.0,
        max_value=210.0,  # J1939 1 °C/bit, offset -40 °C
        era=Era.LEGACY,
        drivers=(DRIVER_AMBIENT_C, "engine_load_pct", DRIVER_WEAR),
        # ET1 byte 1 (start bit 0), 8-bit, 1 degC/bit, offset -40.
        layout=FrameLayout(start_bit=0, bit_len=8, scale=1.0, offset=-40.0),
        description="Engine coolant temperature. J1939 1 degC/bit, offset -40.",
    ),
    SignalSpec(
        name="oil_pressure_kpa",
        spn=100,
        pgn=65263,  # EFL/P1
        unit="kPa",
        min_value=0.0,
        max_value=1000.0,  # J1939 4 kPa/bit
        era=Era.LEGACY,
        drivers=("engine_speed_rpm", DRIVER_WEAR),
        # EFL/P1 byte 4 (start bit 24), 8-bit, 4 kPa/bit.
        layout=FrameLayout(start_bit=24, bit_len=8, scale=4.0, offset=0.0),
        description="Engine oil pressure. J1939 4 kPa/bit.",
    ),
    SignalSpec(
        name="runtime_hours",
        spn=None,  # accumulated; not a single broadcast SPN we model in Tier 1
        pgn=None,
        unit="h",
        min_value=0.0,
        max_value=120_000.0,  # plausible heavy-equipment lifetime ceiling
        era=Era.RUNTIME_ALWAYS,
        drivers=(),
        description="Accumulated engine runtime hours. Monotonic, not era-gated.",
    ),
    SignalSpec(
        name="engine_load_pct",
        spn=92,
        pgn=61443,  # EEC2
        unit="pct",
        min_value=0.0,
        max_value=125.0,  # J1939 1 %/bit, valid to 125 %
        era=Era.MID,
        drivers=(DRIVER_DUTY, DRIVER_TERRAIN_ROUGHNESS),
        # EEC2 byte 3 (start bit 16), 8-bit, 1 %/bit.
        layout=FrameLayout(start_bit=16, bit_len=8, scale=1.0, offset=0.0),
        description="Engine percent load at current speed. J1939 1 %/bit.",
    ),
    SignalSpec(
        name="fuel_rate_lph",
        spn=183,
        pgn=65266,  # LFE
        unit="L/h",
        min_value=0.0,
        max_value=3212.75,  # J1939 0.05 L/h per bit
        era=Era.MID,
        drivers=("engine_load_pct", "engine_speed_rpm"),
        # LFE bytes 1–2 (start bit 0), 16-bit, 0.05 L/h per bit.
        layout=FrameLayout(start_bit=0, bit_len=16, scale=0.05, offset=0.0),
        description="Engine fuel rate. J1939 0.05 L/h per bit.",
    ),
    SignalSpec(
        name="boost_pressure_kpa",
        spn=102,
        pgn=65270,  # IC1
        unit="kPa",
        min_value=0.0,
        max_value=500.0,  # J1939 2 kPa/bit
        era=Era.MID,
        drivers=("engine_load_pct", DRIVER_ALTITUDE_M),
        # IC1 byte 2 (start bit 8), 8-bit, 2 kPa/bit.
        layout=FrameLayout(start_bit=8, bit_len=8, scale=2.0, offset=0.0),
        description="Intake manifold (boost) pressure. J1939 2 kPa/bit.",
    ),
    SignalSpec(
        name="egt_c",
        spn=173,
        pgn=65270,  # IC1 (exhaust gas temperature field)
        unit="degC",
        min_value=-273.0,
        max_value=1734.96875,  # J1939 0.03125 degC/bit, offset -273
        era=Era.MODERN,
        drivers=("engine_load_pct", DRIVER_ALTITUDE_M),
        # IC1 bytes 6–7 (start bit 40), 16-bit, 0.03125 degC/bit, offset -273.
        layout=FrameLayout(start_bit=40, bit_len=16, scale=0.03125, offset=-273.0),
        description="Exhaust gas temperature. J1939 0.03125 degC/bit, offset -273.",
    ),
    SignalSpec(
        name="def_level_pct",
        spn=1761,
        pgn=65110,  # AT1T1I (DEF/catalyst tank information)
        unit="pct",
        min_value=0.0,
        max_value=100.0,  # J1939 0.4 %/bit
        era=Era.MODERN,
        drivers=("runtime_hours",),
        # AT1T1I byte 1 (start bit 0), 8-bit, 0.4 %/bit.
        layout=FrameLayout(start_bit=0, bit_len=8, scale=0.4, offset=0.0),
        description="Diesel exhaust fluid (DEF) tank level. J1939 0.4 %/bit.",
    ),
    SignalSpec(
        name="vibration_mms",
        spn=None,  # no single standardised broadcast SPN; modern add-on telematics
        pgn=None,
        unit="mm/s",
        min_value=0.0,
        max_value=50.0,  # ISO 10816-class velocity range for heavy machinery
        era=Era.MODERN,
        drivers=("engine_load_pct", DRIVER_TERRAIN_ROUGHNESS, DRIVER_WEAR),
        description="RMS vibration velocity (modern telematics add-on).",
    ),
    SignalSpec(
        name="equipment_age_days",
        spn=None,
        pgn=None,
        unit="days",
        min_value=0.0,
        max_value=40_000.0,  # ~110 years; generous ceiling, fixed per unit
        era=Era.RUNTIME_ALWAYS,
        drivers=(),
        description="Equipment age in days from build date. Fixed per unit.",
    ),
)


# Name → spec lookup, validated for uniqueness at import time.
SIGNALS_BY_NAME: dict[str, SignalSpec] = {}
for _spec in TIER1_SIGNALS:
    if _spec.name in SIGNALS_BY_NAME:  # pragma: no cover - guard against dup edits
        raise ValueError(f"duplicate signal name in registry: {_spec.name!r}")
    SIGNALS_BY_NAME[_spec.name] = _spec
del _spec


def signal_names() -> tuple[str, ...]:
    """All Tier-1 signal names, in registry (canonical) order."""
    return tuple(s.name for s in TIER1_SIGNALS)


def get_spec(name: str) -> SignalSpec:
    """Return the :class:`SignalSpec` for ``name`` or raise ``KeyError``."""
    return SIGNALS_BY_NAME[name]


__all__ = [
    "Era",
    "FrameLayout",
    "SignalSpec",
    "TIER1_SIGNALS",
    "SIGNALS_BY_NAME",
    "signal_names",
    "get_spec",
    "DRIVER_AMBIENT_C",
    "DRIVER_ALTITUDE_M",
    "DRIVER_TERRAIN_ROUGHNESS",
    "DRIVER_DUTY",
    "DRIVER_WEAR",
]
