"""CAN capability gating by model-year era (ADR-008).

A real machine only reports the SPNs its electronics support; an older unit's bus
simply does not expose newer signals. We model this with coarse **capability eras**
(``Era`` in ``spec.py``). The rule, applied in exactly one place here:

    a signal a unit's era does not support is **NULL (missing), never zero**.

This is *structural* missingness — distinct from a sensor-fault dropout (a healthy
channel going bad), which is injected and labelled separately in F3. Keeping the
era→signal map derived from the single ``SignalSpec`` registry means the data
dictionary, the generators, and this gate can never silently disagree.

Mapping model year → era is also done here so the fleet layer (F2) and the data
dictionary share one definition of the era boundaries.
"""

from __future__ import annotations

from .spec import Era, SignalSpec, signal_names, get_spec

# Model-year boundaries for the coarse eras (DATA_DESIGN §4). Inclusive lower
# bounds: [.., 2004] Legacy, [2005, 2014] Mid, [2015, ..] Modern.
_MID_FROM_YEAR = 2005
_MODERN_FROM_YEAR = 2015


def era_for_model_year(year: int) -> Era:
    """Map a unit's model year to its CAN capability era."""
    if year >= _MODERN_FROM_YEAR:
        return Era.MODERN
    if year >= _MID_FROM_YEAR:
        return Era.MID
    return Era.LEGACY


def supports(unit_era: Era, signal: SignalSpec) -> bool:
    """Whether a unit of ``unit_era`` reports ``signal``.

    Non-gated fields (``Era.RUNTIME_ALWAYS``: runtime hours, equipment age) are
    always supported. A CAN signal is supported when it was introduced in the
    unit's era or any earlier era (``signal.era <= unit_era`` by era ordinal).
    """
    if signal.era == Era.RUNTIME_ALWAYS:
        return True
    if not unit_era.is_can_era:  # pragma: no cover - units never carry the sentinel
        raise ValueError(f"{unit_era!r} is not a valid unit capability era")
    return signal.era.value <= unit_era.value


def supported_signal_names(unit_era: Era) -> tuple[str, ...]:
    """Names of the signals a unit of ``unit_era`` reports, in canonical order."""
    return tuple(name for name in signal_names() if supports(unit_era, get_spec(name)))


def gated_signal_names(unit_era: Era) -> tuple[str, ...]:
    """Names of the signals a unit of ``unit_era`` does **not** report (→ NULL)."""
    supported = set(supported_signal_names(unit_era))
    return tuple(name for name in signal_names() if name not in supported)


__all__ = [
    "era_for_model_year",
    "supports",
    "supported_signal_names",
    "gated_signal_names",
]
