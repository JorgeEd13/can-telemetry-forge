"""Render a :class:`ValidationRun` into a self-contained Markdown report (F4).

The report is the deliverable: a single file a reader can open to see whether the
generated distributions are plausible — what was compared, against what reference,
and where each check passed or failed. It is **reproducible from a documented
command** (``forge validate``) and states its own provenance (synthetic data,
clean-room, opt-in external reference, never committed).
"""

from __future__ import annotations

import datetime as _dt

from .compare import SignalComparison
from .reference import ReferenceResult, ValidationRun

_PASS = "✅"
_FAIL = "❌"
_NA = "—"


def _fmt(x: float | None) -> str:
    if x is None:
        return _NA
    if x != x:  # NaN
        return _NA
    return f"{x:.4g}"


def _overlap_cell(c: SignalComparison) -> str:
    return _NA if c.overlap is None else f"{c.overlap:.3f}"


def _comparison_table(comparisons: list[SignalComparison]) -> list[str]:
    lines = [
        "| Signal | Unit | n | min | p05 | p50 | mean | p95 | max | overlap |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for c in comparisons:
        lines.append(
            f"| `{c.signal}` | {c.unit} | {c.n:,} | {_fmt(c.gen_min)} | {_fmt(c.gen_p05)} | "
            f"{_fmt(c.gen_p50)} | {_fmt(c.gen_mean)} | {_fmt(c.gen_p95)} | "
            f"{_fmt(c.gen_max)} | {_overlap_cell(c)} |"
        )
    return lines


def _adapter_section(result: ReferenceResult) -> list[str]:
    status = _PASS if result.passed else (_NA if not result.available else _FAIL)
    lines = [
        f"### {status} `{result.adapter}` — {result.description}",
        "",
    ]
    if result.note:
        lines += [f"> {result.note}", ""]
    if not result.available:
        lines += ["_Reference unavailable — offline checks still validated the run._", ""]
        return lines
    if result.checks:
        lines += ["**Checks**", "", "| Check | Result | Detail |", "|---|---|---|"]
        for chk in result.checks:
            lines.append(
                f"| {chk.name} | {_PASS if chk.passed else _FAIL} | {chk.detail} |"
            )
        lines.append("")
    if result.comparisons:
        lines += ["**Distributions**", ""]
        lines += _comparison_table(result.comparisons)
        lines.append("")
    return lines


def render_report(run: ValidationRun, *, datasets: tuple[str, ...] = ()) -> str:
    """Render ``run`` to a Markdown string."""
    cfg = run.config
    overall = _PASS if run.passed else _FAIL
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    ran = [r.adapter for r in run.results if r.available and r.checks]
    failed = [r.adapter for r in run.results if r.available and r.checks and not r.passed]

    lines = [
        "# Distribution validation report",
        "",
        f"_Generated {now} by `can-telemetry-forge` `forge validate`._",
        "",
        "Synthetic, J1939-grounded telemetry validated for **plausibility** against "
        "the documented standard, a pinned reference run, and (opt-in) a public "
        "dataset. The data is synthetic and clean-room; any external reference is "
        "**fetched at run time and never committed**.",
        "",
        "## Summary",
        "",
        f"- **Overall:** {overall} {'all checks passed' if run.passed else 'one or more checks failed'}",
        f"- **Config:** seed `{cfg.seed}`, {cfg.days} day(s) @ `{cfg.resolution}`, "
        f"failure horizon {cfg.failure_horizon_h:g} h",
        f"- **Adapters with checks:** {', '.join(f'`{a}`' for a in ran) or 'none'}",
    ]
    if datasets:
        lines.append(f"- **External datasets requested:** {', '.join(f'`{d}`' for d in datasets)}")
    if failed:
        lines.append(f"- **Failing adapters:** {', '.join(f'`{a}`' for a in failed)}")
    lines += ["", "## Adapters", ""]
    for result in run.results:
        lines += _adapter_section(result)

    lines += [
        "## Provenance",
        "",
        "- Data is **synthetic**, modeled on the public **SAE J1939** standard + "
        "documented physics for a fictional operator. **Not real telemetry.**",
        "- The `ved` adapter compares against the **Vehicle Energy Dataset** "
        "(Kaggle, **CC-BY 4.0**), used only to sanity-check distributions, fetched "
        "at run time, **never committed or used as a seed**.",
        "- Reproducible: `forge validate` regenerates the data from config + seed; "
        "same seed → same report (timestamp aside).",
        "",
    ]
    return "\n".join(lines)


__all__ = ["render_report"]
