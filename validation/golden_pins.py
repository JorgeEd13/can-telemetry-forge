"""Pinned golden summary stats (generated — do not hand-edit).

Regenerate with ``python -m validation.reference --pin-golden`` ONLY when a
generator change is intentional, and commit it with that change.
"""

from __future__ import annotations

GOLDEN_PINS: dict[str, dict[str, float]] = {
    "engine_speed_rpm": {"mean": 1111.0767539560393, "std": 568.27375210448, "p05": 702.3133314670514, "p95": 1720.1801196846313},
    "coolant_temp_c": {"mean": 101.04684885648129, "std": 11.504598851864902, "p05": 89.66665033506949, "p95": 115.20271603636647},
    "oil_pressure_kpa": {"mean": 108.18066100001654, "std": 115.04765727522773, "p05": 0.0, "p95": 313.6713699109379},
    "runtime_hours": {"mean": 19382.56617064642, "std": 13162.352244753982, "p05": 3005.3776969751407, "p95": 41929.32565030728},
    "engine_load_pct": {"mean": 26.105993106355804, "std": 26.625800139204568, "p05": 0.0, "p95": 66.54804269991774},
    "fuel_rate_lph": {"mean": 65.1932827284334, "std": 266.8832086859819, "p05": 0.0, "p95": 121.9582456111368},
    "boost_pressure_kpa": {"mean": 64.86793238963504, "std": 72.52675576188552, "p05": 0.0, "p95": 165.04193141909107},
    "egt_c": {"mean": 368.27124923803365, "std": 105.07991160779568, "p05": 299.9134226359031, "p95": 471.95162128515915},
    "def_level_pct": {"mean": 86.53145896656535, "std": 7.731569018427047, "p05": 74.8, "p95": 98.5},
    "vibration_mms": {"mean": 6.599505179632683, "std": 2.4349591650080935, "p05": 4.165416463289024, "p95": 8.630575071830695},
    "equipment_age_days": {"mean": 3803.0204329998046, "std": 2664.1268984827625, "p05": 591.6118054778638, "p95": 8623.782974053855},
}
