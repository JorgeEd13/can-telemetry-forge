"""Pure distribution-comparison primitives — no I/O, no external data here.

The math the adapters share: per-signal summary statistics and a bounded
**histogram-overlap** score between two value samples. Kept dependency-light
(NumPy only) and deterministic so the offline adapters stay CI-safe and the report
is reproducible.

The overlap score is the classic **histogram intersection** on a shared bin grid:
``sum(min(p_i, q_i))`` over density-normalised histograms ``p`` (generated) and
``q`` (reference). It is 1.0 for identical distributions and 0.0 for disjoint
ones, symmetric, and needs no distributional assumptions — a robust, explainable
"do these look alike?" number for a portfolio report.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Default shared-grid resolution for histogram intersection. Enough to see shape
# differences without over-fitting to sample noise on the small test profile.
_DEFAULT_BINS = 40


@dataclass(frozen=True)
class SignalComparison:
    """One signal's distribution summary, optionally vs a reference sample.

    ``overlap`` is the histogram-intersection score in ``[0, 1]`` against the
    reference, or ``None`` when no reference sample was supplied (the summary still
    carries the generated stats). ``n`` is the count of non-NULL generated values
    (era-gated NULLs are excluded — they are structural missingness, not readings).
    """

    signal: str
    unit: str
    n: int
    gen_min: float
    gen_max: float
    gen_mean: float
    gen_std: float
    gen_p05: float
    gen_p50: float
    gen_p95: float
    overlap: float | None = None
    ref_n: int | None = None


def _finite(values: np.ndarray) -> np.ndarray:
    """Non-NULL, finite values only (era-gated NULLs / NaNs dropped)."""
    arr = np.asarray(values, dtype=float)
    return arr[np.isfinite(arr)]


def histogram_overlap(
    generated: np.ndarray, reference: np.ndarray, *, bins: int = _DEFAULT_BINS
) -> float:
    """Histogram-intersection overlap of two samples on a shared grid → ``[0, 1]``.

    Both samples are reduced to density-normalised histograms over the *combined*
    value range, then scored as ``sum(min(p_i, q_i)) × bin_width``. Returns 0.0 if
    either sample is empty or the shared range is degenerate (cannot compare).
    """
    g = _finite(generated)
    r = _finite(reference)
    if g.size == 0 or r.size == 0:
        return 0.0
    lo = float(min(g.min(), r.min()))
    hi = float(max(g.max(), r.max()))
    if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
        return 0.0
    edges = np.linspace(lo, hi, bins + 1)
    gh, _ = np.histogram(g, bins=edges, density=True)
    rh, _ = np.histogram(r, bins=edges, density=True)
    width = (hi - lo) / bins
    return float(np.minimum(gh, rh).sum() * width)


def summarise_signal(
    signal: str,
    unit: str,
    generated: np.ndarray,
    reference: np.ndarray | None = None,
    *,
    bins: int = _DEFAULT_BINS,
) -> SignalComparison:
    """Summary stats for one signal, plus overlap vs ``reference`` if given."""
    g = _finite(generated)
    if g.size == 0:
        # No non-NULL values (e.g. an era-gated signal absent across the sample).
        return SignalComparison(
            signal=signal, unit=unit, n=0,
            gen_min=float("nan"), gen_max=float("nan"), gen_mean=float("nan"),
            gen_std=float("nan"), gen_p05=float("nan"), gen_p50=float("nan"),
            gen_p95=float("nan"), overlap=None, ref_n=None,
        )
    p05, p50, p95 = (float(x) for x in np.percentile(g, [5, 50, 95]))
    overlap: float | None = None
    ref_n: int | None = None
    if reference is not None:
        r = _finite(reference)
        ref_n = int(r.size)
        overlap = histogram_overlap(g, r, bins=bins) if r.size else None
    return SignalComparison(
        signal=signal, unit=unit, n=int(g.size),
        gen_min=float(g.min()), gen_max=float(g.max()), gen_mean=float(g.mean()),
        gen_std=float(g.std()), gen_p05=p05, gen_p50=p50, gen_p95=p95,
        overlap=overlap, ref_n=ref_n,
    )


def compare_distributions(
    gen_columns: dict[str, np.ndarray],
    ref_columns: dict[str, np.ndarray] | None,
    units: dict[str, str],
    *,
    bins: int = _DEFAULT_BINS,
) -> list[SignalComparison]:
    """Summarise every generated signal, overlapping with the reference where both
    sides expose the column. Signals absent from ``ref_columns`` get summary stats
    with no overlap (the reference simply doesn't cover that channel).
    """
    out: list[SignalComparison] = []
    for name, values in gen_columns.items():
        ref = None if ref_columns is None else ref_columns.get(name)
        out.append(summarise_signal(name, units.get(name, ""), values, ref, bins=bins))
    return out


__all__ = [
    "SignalComparison",
    "histogram_overlap",
    "summarise_signal",
    "compare_distributions",
]
