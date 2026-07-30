"""Obvious labeled outliers — the F2 slice, now a thin wrapper over the registry.

The obvious out-of-range spike is just one registered injector (F3, ADR-016); this
module keeps the original :func:`inject_obvious_outliers` helper for back-compat
(and as a minimal, single-defect entry point), delegating to the registry's
``obvious_outlier`` injector. The full F3 contract lives in :mod:`.inject`.

Each affected cell gets the spike written into the signal array and a matching
``True`` in a per-signal boolean mask. Only non-NULL (era-supported) cells are
eligible — we never resurrect an era-gated signal. Seeded (ADR-005).
"""

from __future__ import annotations

import numpy as np

from .injectors import INJECTOR_BY_TYPE
from .spec import OBVIOUS_OUTLIER


def inject_obvious_outliers(
    signals: dict[str, np.ndarray | None],
    rate: float,
    rng: np.random.Generator,
) -> dict[str, np.ndarray]:
    """Inject obvious out-of-range spikes in place; return per-signal masks.

    A thin wrapper over the ``obvious_outlier`` registry injector. Eligibility is
    "present for this unit's era" (era-NULL cells are skipped).

    Returns:
        ``{signal_name: bool mask}`` for every signal that received a spike — the
        ground-truth label aligned to the reading rows. ``signals`` is mutated in
        place where an outlier is injected.
    """
    if rate <= 0.0:
        return {}
    # A None array means the signal does not exist for this unit's era. It has no
    # rows to be eligible, so it gets an empty mask — the injector skips it either
    # way. The previous form read `np.zeros(arr.shape[0]) if arr is None`, which
    # dereferenced `arr` on exactly the branch where it is None; it never fired
    # because no caller had yet passed a None signal here.
    eligible = {
        name: np.zeros(0, dtype=np.bool_) if arr is None else ~np.isnan(arr)
        for name, arr in signals.items()
    }
    hits = INJECTOR_BY_TYPE[OBVIOUS_OUTLIER].inject(signals, eligible, rate, rng)
    return {hit.signal: hit.mask for hit in hits}


__all__ = ["inject_obvious_outliers"]
