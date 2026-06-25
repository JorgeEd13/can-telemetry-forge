"""Distribution validation (F4) — is the generated data *plausible*?

This package answers a question the rest of the library can't answer about itself:
do the generated signal distributions look like real-world telemetry, and do they
stay inside the J1939 spec they claim to model? It is **opt-in** and lives outside
``src/`` deliberately — the core generator never imports it, CI never requires it,
and it is the *only* place a real public dataset may appear (ADR-003).

Three reference adapters, behind one declarative registry (mirroring the signal
and anomaly registries, ADR-012/-016):

* ``in_spec`` — every signal's values must sit inside its documented J1939 range
  (``SignalSpec.min_value``..``max_value``). Pure, offline, no external data.
* ``golden`` — the run's per-signal summary stats must match a pinned reference
  run regenerated from a fixed seed. Pure, offline; catches silent drift in the
  generator itself.
* ``ved`` — histogram/summary overlap against the **Vehicle Energy Dataset**
  (Kaggle, CC-BY 4.0), **fetched at run time, never committed** (ADR-017). The one
  adapter that touches the network, and only when explicitly requested.

The base (offline) adapters always run so ``forge validate`` works with no network
and is reproducible by anyone; ``ved`` layers a real-data comparison on top when
``--dataset ved`` is passed.
"""

from __future__ import annotations

from .compare import SignalComparison, compare_distributions
from .reference import (
    REFERENCE_ADAPTERS,
    OFFLINE_ADAPTERS,
    ReferenceAdapter,
    ReferenceResult,
    get_adapter,
    run_validation,
)
from .report import render_report

__all__ = [
    "SignalComparison",
    "compare_distributions",
    "REFERENCE_ADAPTERS",
    "OFFLINE_ADAPTERS",
    "ReferenceAdapter",
    "ReferenceResult",
    "get_adapter",
    "run_validation",
    "render_report",
]
