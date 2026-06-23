"""Labeled anomaly injection (F2 ships the obvious-outlier slice; F3 extends it).

Every injected defect carries a ground-truth label so downstream QA/anomaly work
is *verifiable* — the injection is fully recoverable from the labels (ADR-006).
See :mod:`.outliers`.
"""

from __future__ import annotations

from .outliers import inject_obvious_outliers

__all__ = ["inject_obvious_outliers"]
