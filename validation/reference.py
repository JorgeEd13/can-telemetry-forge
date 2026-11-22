"""Reference adapters + the validation orchestrator (F4).

A **reference adapter** answers "what do we compare the generated data against?".
Each is a self-describing entry in a declarative registry (same shape as the
signal and anomaly registries, ADR-012/-016): a name, a one-line description, a
``network`` flag, and a ``check`` callable that turns a generated ``readings``
frame into a :class:`ReferenceResult` (per-signal comparisons + pass/fail checks).

Adapters
--------
* ``in_spec`` (offline) — assert every signal sits inside its documented J1939
  range from the signal registry. Catches a generator emitting out-of-spec values.
* ``golden`` (offline) — regenerate a fixed seed/profile and assert each signal's
  mean / std / p05 / p95 match **pinned literal values** (``golden_pins.py``) within
  a tolerance of 1e-4 of the signal's J1939 span. Catches silent drift in the
  generator. Only the ~44 summary numbers are committed, never generated data; an
  intentional generator change re-pins them (``python -m validation.reference
  --pin-golden``) in the same commit, so the drift shows up in review.
* ``ved`` (network, opt-in) — histogram overlap against the **Vehicle Energy
  Dataset** (Kaggle, CC-BY 4.0), fetched at run time and **never committed**
  (ADR-017). Maps VED's OBD-II columns onto our overlapping J1939 signals.

``run_validation`` runs the offline adapters always (so the command works with no
network and is reproducible by anyone) and layers ``ved`` on top only when asked.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from can_telemetry_forge.config import ForgeConfig, default_config
from can_telemetry_forge.signals import TIER1_SIGNALS, get_spec, signal_names
from can_telemetry_forge.sim import simulate

from .compare import SignalComparison, compare_distributions, summarise_signal

# Where a fetched external dataset is cached. Mirrors the .gitignore entry — this
# directory holds downloaded public data and is **never committed**.
_CACHE_DIR = Path(__file__).resolve().parent / "_data"

# A small, fast, deterministic profile for the golden self-consistency baseline.
# It must match the seed/profile used to (re)compute the reference, so the check is
# "did the generator drift?" not "is this a different config?". Deliberately tiny —
# a single small contract over a short window — because the golden run is recomputed
# on every ``forge validate`` call (the reference *is* the regeneration, ADR-005), so
# it has to be cheap. A small sample is enough to catch a mean/std shift.
def _golden_profile() -> dict:
    """A minimal fleet config for the golden drift baseline (recomputed each run)."""
    return {
        "days": 2,
        "resolution": "5min",
        "seed": 1234,
        "fleet": {
            "contracts": [
                {
                    "id": "golden",
                    "label": "Golden reference contract",
                    "region_id": "temperate_lowland",
                    "units": 6,
                    "duty_bias": 0.0,
                }
            ]
        },
    }


GOLDEN_PROFILE: dict = _golden_profile()


@dataclass(frozen=True)
class CheckResult:
    """One named pass/fail assertion in a validation run."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ReferenceResult:
    """The outcome of one adapter over a generated ``readings`` frame."""

    adapter: str
    description: str
    available: bool  # False when an opt-in reference could not be obtained (e.g. no network)
    comparisons: list[SignalComparison] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    note: str = ""

    @property
    def passed(self) -> bool:
        """True iff the adapter ran and every check passed."""
        return self.available and all(c.passed for c in self.checks)


# A check takes the generated readings frame + the units map and returns a result.
AdapterFn = Callable[[pd.DataFrame, dict[str, str]], ReferenceResult]


@dataclass(frozen=True)
class ReferenceAdapter:
    """Self-describing reference adapter (registry entry)."""

    name: str
    description: str
    network: bool
    check: AdapterFn


# --- helpers ------------------------------------------------------------------


def _signal_columns(readings: pd.DataFrame) -> dict[str, np.ndarray]:
    """Generated value arrays for every Tier-1 signal present in the frame."""
    return {
        name: readings[name].to_numpy(dtype=float)
        for name in signal_names()
        if name in readings.columns
    }


def _units_map() -> dict[str, str]:
    return {s.name: s.unit for s in TIER1_SIGNALS}


# --- adapter: in_spec (offline) ----------------------------------------------


def _clean_row_mask(readings: pd.DataFrame) -> np.ndarray:
    """Boolean mask of rows carrying **no** value-distorting injected defect.

    The anomaly layer (ADR-006/-016) injects out-of-range spikes and contextual
    distortions **on purpose**; those are recoverable from the labels. The in-spec
    check is about the *generator's* own fidelity to J1939, so it must exclude every
    deliberately-corrupted cell. We key on the row-level ``is_outlier`` rollup rather
    than the per-signal ``anomaly_signal`` label: a single row can carry distorted
    values on more than one signal (only one is *labeled*, by injector priority —
    ADR-016), and ``is_outlier`` flags any value-distorting defect on the row,
    catching the unlabeled partner too. (Era-NULLs are NaN and drop out of the finite
    filter separately; dropout blanks to NULL and likewise drops out.)
    """
    n = len(readings)
    if "is_outlier" not in readings.columns:
        return np.ones(n, dtype=bool)
    return ~readings["is_outlier"].to_numpy().astype(bool)


def _check_in_spec(readings: pd.DataFrame, units: dict[str, str]) -> ReferenceResult:
    """Every clean (non-defect) non-NULL signal value must lie within its J1939 range.

    Injected anomalies are out-of-range *by design* and excluded via the labels;
    this validates that the **generator** stays in spec, not that the deliberate
    defects do.
    """
    cols = _signal_columns(readings)
    comparisons = compare_distributions(cols, None, units)
    clean_rows = _clean_row_mask(readings)
    checks: list[CheckResult] = []
    for name, values in cols.items():
        spec = get_spec(name)
        arr = np.asarray(values, dtype=float)
        clean = arr[clean_rows]
        finite = clean[np.isfinite(clean)]
        if finite.size == 0:
            # Era-gated-away across the whole sample: nothing to range-check.
            continue
        below = int((finite < spec.min_value).sum())
        above = int((finite > spec.max_value).sum())
        ok = below == 0 and above == 0
        checks.append(
            CheckResult(
                name=f"{name} in [{spec.min_value:g}, {spec.max_value:g}] {spec.unit}",
                passed=ok,
                detail=(
                    "all clean values in range"
                    if ok
                    else f"{below} below / {above} above the documented J1939 range"
                ),
            )
        )
    return ReferenceResult(
        adapter="in_spec",
        description="Clean generated values inside their documented SAE J1939 ranges.",
        available=True,
        comparisons=comparisons,
        checks=checks,
    )


# --- adapter: golden (offline) -----------------------------------------------


GOLDEN_STATS: tuple[str, ...] = ("mean", "std", "p05", "p95")

# Allowed |recomputed - pinned| per stat, as a fraction of the signal's J1939 span.
# Far above cross-platform float noise (~1e-13), far below any real change: on
# coolant (span 250 degC) it is 0.025 degC.
GOLDEN_REL_TOL: float = 1e-4


def _golden_signal_stats() -> dict[str, dict[str, float]]:
    """Regenerate the fixed golden profile; return per-signal mean/std/p05/p95."""
    from can_telemetry_forge.config import config_from_dict

    ds = simulate(config_from_dict(GOLDEN_PROFILE))
    stats: dict[str, dict[str, float]] = {}
    for name in signal_names():
        if name not in ds.readings.columns:
            continue
        arr = ds.readings[name].to_numpy(dtype=float)
        finite = arr[np.isfinite(arr)]
        if finite.size:
            stats[name] = {
                "mean": float(finite.mean()),
                "std": float(finite.std()),
                "p05": float(np.percentile(finite, 5)),
                "p95": float(np.percentile(finite, 95)),
            }
    return stats


def compare_to_pins(
    stats: dict[str, dict[str, float]], pins: dict[str, dict[str, float]]
) -> list[CheckResult]:
    """One check per (signal, stat): recomputed vs pinned, within the span tolerance.

    A signal present on one side only fails too — a signal that appears or vanishes
    is drift as much as a moved mean.
    """
    checks: list[CheckResult] = []
    for name in sorted(set(stats) | set(pins)):
        if name not in stats or name not in pins:
            checks.append(
                CheckResult(
                    name=f"{name} golden present",
                    passed=False,
                    detail="in recomputed run" if name in stats else "pinned but not produced",
                )
            )
            continue
        spec = get_spec(name)
        tol = GOLDEN_REL_TOL * (spec.max_value - spec.min_value)
        for stat in GOLDEN_STATS:
            got, want = stats[name][stat], pins[name][stat]
            checks.append(
                CheckResult(
                    name=f"{name} golden {stat}",
                    passed=bool(abs(got - want) <= tol),
                    detail=f"{got:.6g} vs pinned {want:.6g} (tol {tol:.3g} {spec.unit})",
                )
            )
    return checks


@lru_cache(maxsize=1)
def _golden_drift_result() -> tuple[list[CheckResult], list[SignalComparison]]:
    """The golden adapter's checks + summaries, cached per process."""
    from .golden_pins import GOLDEN_PINS

    stats = _golden_signal_stats()
    comparisons = [
        SignalComparison(
            signal=name, unit=get_spec(name).unit, n=0,
            gen_min=float("nan"), gen_max=float("nan"), gen_mean=st["mean"],
            gen_std=st["std"], gen_p05=st["p05"], gen_p50=float("nan"),
            gen_p95=st["p95"],
        )
        for name, st in stats.items()
    ]
    return compare_to_pins(stats, GOLDEN_PINS), comparisons


def pin_golden_source() -> str:
    """Render ``golden_pins.py`` from the current generator (for an intentional re-pin)."""
    lines = [
        '"""Pinned golden summary stats (generated — do not hand-edit).',
        "",
        "Regenerate with ``python -m validation.reference --pin-golden`` ONLY when a",
        "generator change is intentional, and commit it with that change.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "GOLDEN_PINS: dict[str, dict[str, float]] = {",
    ]
    for name, st in _golden_signal_stats().items():
        inner = ", ".join(f'"{k}": {st[k]!r}' for k in GOLDEN_STATS)
        lines.append(f'    "{name}": {{{inner}}},')
    lines.append("}")
    return "\n".join(lines) + "\n"


def _check_golden(readings: pd.DataFrame, units: dict[str, str]) -> ReferenceResult:
    """Drift guard: the fixed-seed golden run still matches its pinned summary stats.

    Config-independent — it always validates the pinned *golden profile* (not the
    user's run), so it answers "is generation still healthy?" regardless of what is
    being validated. ``readings``/``units`` are accepted for a uniform adapter
    signature but unused (the user's own summaries appear under `in_spec`/`ved`).
    """
    del readings, units
    checks, comparisons = _golden_drift_result()
    return ReferenceResult(
        adapter="golden",
        description="Fixed-seed golden run matches pinned mean/std/p05/p95 (drift guard).",
        available=True,
        comparisons=comparisons,
        checks=checks,
        note="" if checks else "golden produced no checks (no signals in the profile)",
    )


# --- adapter: ved (network, opt-in) ------------------------------------------

# Maps our J1939 signal name → the VED (Vehicle Energy Dataset) column carrying the
# comparable OBD-II quantity. VED is light-vehicle OBD-II, so only the engine-core
# channels overlap; the rest of our Tier-1 set has no VED counterpart and is simply
# summarised without an overlap score. Column names follow the published VED
# "segregated/combustion-master" schema. A column missing from the chosen handle is
# skipped (so a different VED mirror with different names just compares fewer channels).
_VED_COLUMN_MAP: dict[str, str] = {
    "engine_speed_rpm": "Engine_RPM_RPM",
    "engine_load_pct": "Absolute_Load_pct",
}

# Only read the columns we actually compare (the VED master CSV is ~500 MB; reading a
# couple of columns keeps the opt-in check light). Mass-air-flow is pulled too as a
# documented load/fuel proxy for the report's context, even though we don't score it.
_VED_USECOLS: tuple[str, ...] = ("Engine_RPM_RPM", "Absolute_Load_pct", "MAF_g_per_sec")

# Read at most this many rows from the VED master for the distribution sample — plenty
# for a stable histogram while keeping the parse fast on the multi-hundred-MB file.
_VED_SAMPLE_ROWS = 200_000

_VED_MIN_OVERLAP = 0.30  # a generous floor — VED is light-vehicle, not heavy J1939


# The Kaggle dataset handle (``owner/slug``) the ved adapter compares against.
# Configurable on purpose (a single hardcoded handle rots — datasets get renamed /
# removed): overridable via ``--ved-handle`` / the ``ved_handle`` config, or the
# ``FORGE_VED_HANDLE`` env var. The default is a **verified** published VED mirror
# whose "combustion master" CSV carries the OBD-II columns in ``_VED_COLUMN_MAP``.
DEFAULT_VED_HANDLE = "yashseth25/ved-segregated"

# The classic Kaggle REST endpoint. We hit it directly with HTTP Basic auth from the
# legacy ``~/.kaggle/kaggle.json`` (username + key): the newer ``kaggle``/``kagglehub``
# SDKs route through ``api.kaggle.com`` and can 403 behind TLS-inspecting proxies,
# whereas this documented endpoint authorizes dataset downloads reliably (ADR-017).
_KAGGLE_REST = "https://www.kaggle.com/api/v1"


def _resolve_ved_handle(handle: str | None) -> str:
    import os

    return handle or os.environ.get("FORGE_VED_HANDLE") or DEFAULT_VED_HANDLE


def _kaggle_basic_auth() -> tuple[str, str]:
    """(username, key) from ``~/.kaggle/kaggle.json``. Raises if absent/malformed."""
    import json

    creds = json.loads((Path.home() / ".kaggle" / "kaggle.json").read_text(encoding="utf-8"))
    return creds["username"], creds["key"]


def _download_ved_zip(handle: str, dest_zip: Path) -> None:
    """Stream the dataset zip from the classic REST endpoint into ``dest_zip``.

    Uses ``requests`` (a ``kagglehub`` transitive dep) with HTTP Basic auth, following
    the 302 to storage. Never committed — ``dest_zip`` lives in the git-ignored cache.
    """
    import requests  # transitive via the [validate] extra; lazy import keeps core lean

    user, key = _kaggle_basic_auth()
    owner, slug = handle.split("/", 1)
    url = f"{_KAGGLE_REST}/datasets/download/{owner}/{slug}"
    with requests.get(url, auth=(user, key), timeout=600, stream=True) as r:
        r.raise_for_status()
        with dest_zip.open("wb") as fh:
            for chunk in r.iter_content(1 << 18):
                fh.write(chunk)


def _read_ved_master(zip_path: Path) -> pd.DataFrame:
    """Read the mapped columns from the largest combustion CSV inside ``zip_path``.

    Only ``_VED_USECOLS`` (those present) and at most ``_VED_SAMPLE_ROWS`` rows are
    read — the master CSV is hundreds of MB, but a couple of columns × a capped sample
    is enough for a stable histogram and keeps the opt-in check fast.
    """
    import zipfile

    with zipfile.ZipFile(zip_path) as z:
        csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
        if not csvs:
            raise FileNotFoundError(f"no CSV inside {zip_path}")
        # Prefer a combustion master if present (it carries the engine OBD columns).
        member = next((n for n in csvs if "combustion" in n.lower()), csvs[0])
        with z.open(member) as fh:
            # Read the header to intersect usecols (a different mirror may differ).
            header = pd.read_csv(fh, nrows=0).columns
        present = [c for c in _VED_USECOLS if c in header]
        with z.open(member) as fh:
            return pd.read_csv(fh, usecols=present or None, nrows=_VED_SAMPLE_ROWS)


def _load_ved_frame(cache_dir: Path, handle: str | None = None) -> pd.DataFrame:
    """Fetch (if needed) and load the chosen VED dataset from the run-time cache.

    Downloads the dataset zip via the classic Kaggle REST endpoint (legacy key) into
    the git-ignored cache, then reads a capped sample of the mapped engine columns.
    The CC-BY-4.0 data is **never committed** (ADR-017). A previously-cached zip
    short-circuits the network. Raises on total failure so the orchestrator can
    degrade to "reference unavailable" instead of pretending.
    """
    resolved = _resolve_ved_handle(handle)
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = resolved.replace("/", "__")
    zip_path = cache_dir / f"{slug}.zip"
    if not zip_path.exists():
        _download_ved_zip(resolved, zip_path)
    return _read_ved_master(zip_path)


def _check_ved(
    readings: pd.DataFrame,
    units: dict[str, str],
    *,
    cache_dir: Path = _CACHE_DIR,
    handle: str | None = None,
) -> ReferenceResult:
    """Histogram overlap of the overlapping engine channels vs real VED OBD-II data."""
    resolved = _resolve_ved_handle(handle)
    description = (
        f"Distribution overlap vs the Vehicle Energy Dataset (Kaggle `{resolved}`, "
        "CC-BY 4.0), fetched at run time, never committed."
    )
    try:
        ved = _load_ved_frame(cache_dir, handle=resolved)
    except BaseException as exc:
        # BaseException (not just Exception) on purpose: the kaggle client can raise
        # SystemExit at import/auth time when unauthenticated. This adapter is opt-in
        # and must never take down the (always-valid) offline validation with it.
        return ReferenceResult(
            adapter="ved",
            description=description,
            available=False,
            note=(
                "VED reference unavailable (opt-in network fetch failed or skipped): "
                f"{type(exc).__name__}: {exc}. Offline checks still validate the run."
            ),
        )

    cols = _signal_columns(readings)
    comparisons: list[SignalComparison] = []
    checks: list[CheckResult] = []
    for name, ved_col in _VED_COLUMN_MAP.items():
        if name not in cols or ved_col not in ved.columns:
            continue
        ref_values = ved[ved_col].to_numpy(dtype=float)
        cmp = summarise_signal(name, units.get(name, ""), cols[name], ref_values)
        comparisons.append(cmp)
        if cmp.overlap is not None:
            checks.append(
                CheckResult(
                    name=f"{name} overlap ≥ {_VED_MIN_OVERLAP:g} vs VED",
                    passed=cmp.overlap >= _VED_MIN_OVERLAP,
                    detail=f"histogram overlap {cmp.overlap:.3f} (VED n={cmp.ref_n})",
                )
            )
    note = (
        "VED is light-vehicle OBD-II, not heavy J1939 — overlap is a plausibility "
        "sanity-check on shared engine channels, not an equivalence claim."
    )
    return ReferenceResult(
        adapter="ved",
        description=description,
        available=True,
        comparisons=comparisons,
        checks=checks,
        note=note,
    )


# --- registry + orchestrator --------------------------------------------------

REFERENCE_ADAPTERS: dict[str, ReferenceAdapter] = {
    a.name: a
    for a in (
        ReferenceAdapter("in_spec", "documented J1939 ranges", network=False, check=_check_in_spec),
        ReferenceAdapter("golden", "fixed-seed run vs pinned summary stats", network=False, check=_check_golden),
        ReferenceAdapter("ved", "Vehicle Energy Dataset (CC-BY 4.0)", network=True, check=_check_ved),
    )
}

# The adapters that always run: no network, reproducible by anyone, CI-safe.
OFFLINE_ADAPTERS: tuple[str, ...] = tuple(
    name for name, a in REFERENCE_ADAPTERS.items() if not a.network
)


def get_adapter(name: str) -> ReferenceAdapter:
    """Return the adapter registered under ``name`` or raise ``KeyError``."""
    return REFERENCE_ADAPTERS[name]


@dataclass(frozen=True)
class ValidationRun:
    """The full result of a validation pass: the config, the adapter results, and
    a roll-up ``passed`` over the checks that actually ran.
    """

    config: ForgeConfig
    results: list[ReferenceResult]

    @property
    def passed(self) -> bool:
        """True iff every *available* adapter that produced checks passed them."""
        ran = [r for r in self.results if r.available and r.checks]
        return bool(ran) and all(r.passed for r in ran)


def run_validation(
    config: ForgeConfig | None = None,
    *,
    datasets: Sequence[str] = (),
    cache_dir: Path = _CACHE_DIR,
    ved_handle: str | None = None,
) -> ValidationRun:
    """Validate a generated run. Offline adapters always run; ``datasets`` opts into
    network adapters (currently ``"ved"``).

    ``config`` defaults to the bundled :func:`default_config`. Generation is the
    same library path the CLI uses, so what is validated is exactly what
    ``forge generate`` produces. ``ved_handle`` overrides the Kaggle dataset handle
    the ``ved`` adapter compares against (else ``FORGE_VED_HANDLE`` /
    :data:`DEFAULT_VED_HANDLE`).
    """
    config = (config or default_config()).validate()
    ds = simulate(config)
    units = _units_map()

    results: list[ReferenceResult] = []
    for name in OFFLINE_ADAPTERS:
        results.append(REFERENCE_ADAPTERS[name].check(ds.readings, units))

    for name in datasets:
        adapter = REFERENCE_ADAPTERS.get(name)
        if adapter is None:
            print(f"forge validate: unknown dataset {name!r}, skipping.", file=sys.stderr)
            continue
        if not adapter.network:
            continue  # offline adapters already ran
        if name == "ved":
            results.append(
                _check_ved(ds.readings, units, cache_dir=cache_dir, handle=ved_handle)
            )
        else:  # pragma: no cover - future network adapters
            results.append(adapter.check(ds.readings, units))

    return ValidationRun(config=config, results=results)


__all__ = [
    "DEFAULT_VED_HANDLE",
    "GOLDEN_PROFILE",
    "OFFLINE_ADAPTERS",
    "REFERENCE_ADAPTERS",
    "CheckResult",
    "ReferenceAdapter",
    "ReferenceResult",
    "ValidationRun",
    "compare_to_pins",
    "get_adapter",
    "pin_golden_source",
    "run_validation",
]


if __name__ == "__main__":  # pragma: no cover - maintainer tool
    if sys.argv[1:] == ["--pin-golden"]:
        target = Path(__file__).resolve().parent / "golden_pins.py"
        target.write_text(pin_golden_source(), encoding="utf-8")
        print(f"wrote {target}")
    else:
        print("usage: python -m validation.reference --pin-golden", file=sys.stderr)
        sys.exit(2)
