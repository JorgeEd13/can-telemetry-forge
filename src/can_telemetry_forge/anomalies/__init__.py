"""Labeled anomaly & fault injection (ADR-006, extended by ADR-016).

Every injected defect carries a ground-truth label so downstream QA/anomaly work
is *verifiable* — the injection is fully recoverable from the labels.

The layer is a **declarative registry of injectors** (ADR-016): three defect
families — obvious outliers, joint/contextual outliers, and sensor faults
(stuck/drift/dropout) — each a self-describing :class:`AnomalyInjector`. The
:func:`apply_anomalies` orchestrator runs them over one unit's signals with
mutual-exclusion eligibility and emits a single ``anomaly_type`` categorical
(closed schema, open vocabulary) plus ``anomaly_signal`` and the back-compatible
``is_outlier`` rollup.

:func:`inject_obvious_outliers` remains as the original F2 single-defect helper.
"""

from __future__ import annotations

from .inject import AnomalyLabels, DEFAULT_ANOMALY_RATES, apply_anomalies
from .injectors import INJECTOR_BY_TYPE, INJECTORS
from .outliers import inject_obvious_outliers
from .spec import (
    ANOMALY_TYPES,
    CAN_FRAME_TYPES,
    NO_ANOMALY,
    VALUE_DISTORTION_TYPES,
    AnomalyInjector,
    InjectionHit,
)

__all__ = [
    "apply_anomalies",
    "AnomalyLabels",
    "DEFAULT_ANOMALY_RATES",
    "INJECTORS",
    "INJECTOR_BY_TYPE",
    "AnomalyInjector",
    "InjectionHit",
    "ANOMALY_TYPES",
    "CAN_FRAME_TYPES",
    "NO_ANOMALY",
    "VALUE_DISTORTION_TYPES",
    "inject_obvious_outliers",
]
