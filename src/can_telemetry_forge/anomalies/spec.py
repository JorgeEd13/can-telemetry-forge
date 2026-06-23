"""Declarative registry of anomaly/fault injectors (F3, ADR-016).

The F2 MVP shipped a single hardcoded obvious-outlier injector. F3 adds two more
defect *families* (joint/contextual outliers and sensor faults), and the project's
long-run ambition is for this engine to become a **general** rich-data generator —
so the anomaly layer follows the same philosophy as the signal model (ADR-012):

**An injector is data + a small behaviour, registered, not wired in by hand.** Each
:class:`AnomalyInjector` carries its metadata (its ``anomaly_type`` tag, a one-line
description) and a pure ``inject`` function with a fixed signature::

    inject(signals, eligible, rate, rng) -> list[InjectionHit]

Adding a new defect mechanism — today another sensor fault, tomorrow a whole
different domain's corruption — is a **local edit**: write one injector and append
it to the registry. The schema downstream stays closed (a single ``anomaly_type``
categorical column, open *vocabulary*); new mechanisms are new *values*, never new
*columns*. That is what keeps "swap the domain, keep the engine" true.

Contract (ADR-006, extended by ADR-016):

* Every injected cell is **labeled** — the engine records ``(signal, t_index,
  anomaly_type)`` so the ground truth is fully recoverable.
* Defects are **mutually exclusive per cell**: the orchestrator masks off cells a
  prior injector already claimed, so at most one ``anomaly_type`` lands on a cell.
  (This matches reality — a stuck channel is not *also* a joint outlier — and keeps
  the single categorical honest.)
* **Era-gated (NULL) cells are never eligible.** A sensor fault is a *healthy,
  era-capable* channel going bad, which is deliberately distinct from the
  structural era-NULL missingness (ADR-008). We never resurrect a gated signal.
* Seeded (ADR-005): same rng + rate → identical injection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

# --- the anomaly_type vocabulary ---------------------------------------------
# Closed schema (one `anomaly_type` column), open vocabulary (these strings). A
# new mechanism is a new value here + a new injector below — never a new column.
NO_ANOMALY = ""  # sentinel for clean cells

OBVIOUS_OUTLIER = "obvious_outlier"
JOINT_OUTLIER = "joint_outlier"
SENSOR_STUCK = "sensor_stuck"
SENSOR_DRIFT = "sensor_drift"
SENSOR_DROPOUT = "sensor_dropout"

# All defect tags, in a fixed order (downstream category order). NO_ANOMALY is the
# absence of a defect, not a member of this tuple.
ANOMALY_TYPES: tuple[str, ...] = (
    OBVIOUS_OUTLIER,
    JOINT_OUTLIER,
    SENSOR_STUCK,
    SENSOR_DRIFT,
    SENSOR_DROPOUT,
)

# The defect families that *distort a value* (as opposed to blanking it). The
# ``is_outlier`` boolean rollup (kept for F2 back-compat) is True for these — a
# value present but wrong. ``sensor_dropout`` blanks the cell (NULL) instead, so it
# is a defect but not an "outlier value"; it is still recoverable via anomaly_type.
VALUE_DISTORTION_TYPES: frozenset[str] = frozenset(
    {OBVIOUS_OUTLIER, JOINT_OUTLIER, SENSOR_STUCK, SENSOR_DRIFT}
)


@dataclass(frozen=True)
class InjectionHit:
    """One labeled defect the engine wrote into a unit's signals.

    Attributes:
        signal: the affected signal/column name.
        mask: boolean array (aligned to the unit's rows) — ``True`` where this
            defect was injected into ``signal``.
        anomaly_type: the ground-truth tag (one of :data:`ANOMALY_TYPES`).
    """

    signal: str
    mask: np.ndarray
    anomaly_type: str


# An injector mutates the per-signal arrays in place and returns its hits. It must
# only touch cells that are ``True`` in ``eligible[signal]`` (not already claimed,
# not era-NULL). ``rate`` is the per-eligible-cell (or per-segment) probability.
InjectFn = Callable[
    [dict[str, np.ndarray | None], dict[str, np.ndarray], float, np.random.Generator],
    list[InjectionHit],
]


@dataclass(frozen=True)
class AnomalyInjector:
    """A registered, self-describing defect mechanism (ADR-016).

    Attributes:
        anomaly_type: the tag this injector writes (member of :data:`ANOMALY_TYPES`).
        description: one-line human description for the data dictionary.
        inject: the pure, seeded injection function (see :data:`InjectFn`).
    """

    anomaly_type: str
    description: str
    inject: InjectFn


__all__ = [
    "NO_ANOMALY",
    "OBVIOUS_OUTLIER",
    "JOINT_OUTLIER",
    "SENSOR_STUCK",
    "SENSOR_DRIFT",
    "SENSOR_DROPOUT",
    "ANOMALY_TYPES",
    "VALUE_DISTORTION_TYPES",
    "InjectionHit",
    "InjectFn",
    "AnomalyInjector",
]
