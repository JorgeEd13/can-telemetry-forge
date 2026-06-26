"""Failure-label derivation (F2).

A single module so the generator and any downstream consumer agree on the ground
truth (ADR-009). See :mod:`.failure`.
"""

from __future__ import annotations

from .failure import FAILURE_MODES, UnitLabels, apply_degradation, derive_unit_labels

__all__ = ["FAILURE_MODES", "UnitLabels", "apply_degradation", "derive_unit_labels"]
