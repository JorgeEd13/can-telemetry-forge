"""Configuration schema, fleet/region catalog, and seed plumbing (F2).

A :class:`ForgeConfig` is the single, declarative description of *what to
generate*: the fictional operator's fleet scale, the contrasting regions it works
in, the vehicle-class mix and age curve, the time resolution and window, the
obvious-outlier rate, and the master ``seed``. Everything downstream is a pure,
deterministic function of this config (ADR-005): the simulator builds one seeded
``numpy`` generator from ``seed`` and threads child generators through every stage,
so the same config + seed yields byte-identical tables.

Provenance (ADR-010, ADR-014). The regions are a **fictional international
operator's** deployments, but each region's climate and terrain constants are
pinned to a **named public source class** and traced in ``docs/DATA_DESIGN.md`` §6
— never to any private data. Values are documented plausibility from public
climate-normals and road-roughness references, not measurements copied from a
proprietary log.

Config files are **JSON** (stdlib only — no YAML dependency, keeping the core
install and CI lean). A config file may override any subset of the defaults; the
bundled default (:func:`default_config`) is a complete, runnable Tier-1 fleet.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from .anomalies import ANOMALY_TYPES, DEFAULT_ANOMALY_RATES

# --- resolution ---------------------------------------------------------------

# Supported time resolutions → step in hours (ADR-011). MVP default is 1 minute,
# the typical telemetry-platform cadence.
RESOLUTION_STEP_HOURS: dict[str, float] = {
    "1s": 1.0 / 3600.0,
    "1min": 1.0 / 60.0,
    "5min": 5.0 / 60.0,
}
DEFAULT_RESOLUTION = "1min"


@dataclass(frozen=True)
class VehicleClass:
    """One machinery class in the fleet (DATA_DESIGN §3).

    ``duty_base`` is the class's typical duty-cycle centre in ``[0, 1]`` (how hard
    it is run on average); the region/contract shifts it. ``wear_rate`` scales how
    fast accumulated wear climbs with runtime for this class (unitless multiplier).
    """

    id: str
    label: str
    duty_base: float
    wear_rate: float


@dataclass(frozen=True)
class Region:
    """A deployment geography with a public-grounded climate + terrain profile.

    All values are documented plausibility from **public** sources (traced in
    DATA_DESIGN §6), for a **fictional** operator — never private data.

    Attributes:
        id / label: identifiers.
        ambient_c_mean: annual mean ambient temperature (°C), from public climate
            normals for the source climate class.
        ambient_c_amplitude: half the seasonal/diurnal swing (°C) applied as a
            slow sinusoid over the window.
        altitude_m: representative deployment altitude (m).
        terrain_roughness: road-quality / off-road roughness in ``[0, 1]``,
            mapped from a public road-roughness (IRI-class) reference.
        wear_modifier: environment hazard multiplier (hot/dusty/humid accelerate
            wear); 1.0 is neutral.
        source: the public source class the constants are grounded in (cited).
    """

    id: str
    label: str
    ambient_c_mean: float
    ambient_c_amplitude: float
    altitude_m: float
    terrain_roughness: float
    wear_modifier: float
    source: str


@dataclass(frozen=True)
class Contract:
    """A job in a region: a duty-cycle bias and an expected fleet size.

    ``units`` is the contract's expected number of units (actual count is drawn
    around it, seeded). ``duty_bias`` shifts the assigned vehicles' duty cycle
    (e.g. a long-haul contract runs engines harder than urban support).
    """

    id: str
    label: str
    region_id: str
    units: int
    duty_bias: float


@dataclass(frozen=True)
class FleetSpec:
    """The catalog the fleet is sampled from (composition backbone, DATA_DESIGN §3).

    ``vehicle_mix`` maps a :class:`VehicleClass` id → relative weight (proportions
    need not sum to 1; they are normalised). ``build_year_min/max`` and
    ``build_year_mode`` parametrise a triangular age curve (a tail of older units
    still in service). ``units_per_contract_sd_frac`` sets how much a contract's
    actual unit count varies around its expected ``units``.
    """

    operator_name: str
    vehicle_classes: tuple[VehicleClass, ...]
    vehicle_mix: dict[str, float]
    regions: tuple[Region, ...]
    contracts: tuple[Contract, ...]
    build_year_min: int
    build_year_max: int
    build_year_mode: int
    units_per_contract_sd_frac: float


@dataclass(frozen=True)
class ForgeConfig:
    """Top-level generation config — the single source of *what to generate*.

    ``days`` × ``resolution`` define each unit's time window; ``failure_horizon_h``
    is the label horizon ``h`` (ADR-009); ``seed`` is the master seed (ADR-005).

    Labeled defects (ADR-006/-016) are driven by ``anomaly_rates``: an
    ``anomaly_type`` → rate map (per-eligible-cell for outliers; per-step
    segment-start for sensor faults). Any subset overrides the bundled defaults
    (:data:`~can_telemetry_forge.anomalies.DEFAULT_ANOMALY_RATES`); unset types
    fall back to those defaults. ``obvious_outlier_rate`` is a back-compat
    convenience that, when set, overrides the ``obvious_outlier`` entry.
    """

    fleet: FleetSpec
    days: int = 90
    resolution: str = DEFAULT_RESOLUTION
    failure_horizon_h: float = 168.0  # one week
    obvious_outlier_rate: float | None = None  # back-compat alias for anomaly_rates["obvious_outlier"]
    anomaly_rates: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ANOMALY_RATES))
    seed: int = 42

    def resolved_anomaly_rates(self) -> dict[str, float]:
        """The effective ``anomaly_type`` → rate map (defaults + overrides).

        Starts from :data:`DEFAULT_ANOMALY_RATES`, applies ``anomaly_rates``, then
        the back-compat ``obvious_outlier_rate`` (if set) wins for that one type.
        """
        rates = dict(DEFAULT_ANOMALY_RATES)
        rates.update(self.anomaly_rates)
        if self.obvious_outlier_rate is not None:
            rates["obvious_outlier"] = self.obvious_outlier_rate
        return rates

    def step_hours(self) -> float:
        """Time between successive readings, in hours (from ``resolution``)."""
        try:
            return RESOLUTION_STEP_HOURS[self.resolution]
        except KeyError as exc:  # pragma: no cover - guarded by validate()
            raise ValueError(f"unknown resolution {self.resolution!r}") from exc

    def n_steps(self) -> int:
        """Number of timestamps per unit over the window."""
        return int(round(self.days * 24.0 / self.step_hours()))

    def rng(self) -> np.random.Generator:
        """The master seeded generator (ADR-005). Child rngs spawn from this."""
        return np.random.default_rng(self.seed)

    def validate(self) -> ForgeConfig:
        """Raise ``ValueError`` on an inconsistent config; return self on success."""
        if self.resolution not in RESOLUTION_STEP_HOURS:
            raise ValueError(
                f"resolution {self.resolution!r} not in {sorted(RESOLUTION_STEP_HOURS)}"
            )
        if self.days <= 0:
            raise ValueError("days must be positive")
        if self.obvious_outlier_rate is not None and not (0.0 <= self.obvious_outlier_rate < 1.0):
            raise ValueError("obvious_outlier_rate must be in [0, 1)")
        known_types = set(ANOMALY_TYPES)
        unknown_rates = set(self.anomaly_rates) - known_types
        if unknown_rates:
            raise ValueError(f"anomaly_rates references unknown types: {unknown_rates}")
        for atype, rate in self.anomaly_rates.items():
            if not (0.0 <= rate < 1.0):
                raise ValueError(f"anomaly_rates[{atype!r}] must be in [0, 1)")
        if self.failure_horizon_h <= 0:
            raise ValueError("failure_horizon_h must be positive")
        f = self.fleet
        class_ids = {vc.id for vc in f.vehicle_classes}
        if not class_ids:
            raise ValueError("fleet has no vehicle classes")
        unknown_mix = set(f.vehicle_mix) - class_ids
        if unknown_mix:
            raise ValueError(f"vehicle_mix references unknown classes: {unknown_mix}")
        if sum(f.vehicle_mix.values()) <= 0:
            raise ValueError("vehicle_mix weights must sum to a positive number")
        region_ids = {r.id for r in f.regions}
        for c in f.contracts:
            if c.region_id not in region_ids:
                raise ValueError(f"contract {c.id!r} references unknown region {c.region_id!r}")
            if c.units <= 0:
                raise ValueError(f"contract {c.id!r} must expect a positive unit count")
        if not (f.build_year_min <= f.build_year_mode <= f.build_year_max):
            raise ValueError("require build_year_min <= mode <= max")
        return self


# ---------------------------------------------------------------------------
# Bundled default catalog — a complete, runnable, public-grounded Tier-1 fleet.
#
# Regions are deployments of a FICTIONAL international operator. Each region's
# constants are documented plausibility pinned to a NAMED PUBLIC SOURCE CLASS
# (traced in docs/DATA_DESIGN.md §6) — never private data. Climate means are read
# from public climate-normals classes (Köppen climate type); terrain roughness is
# mapped from the public International Roughness Index (IRI) road-quality bands.
# ---------------------------------------------------------------------------

_VEHICLE_CLASSES: tuple[VehicleClass, ...] = (
    VehicleClass(id="haul_truck", label="Rigid haul truck", duty_base=0.70, wear_rate=1.20),
    VehicleClass(id="wheel_loader", label="Wheel loader", duty_base=0.60, wear_rate=1.05),
    VehicleClass(id="excavator", label="Hydraulic excavator", duty_base=0.65, wear_rate=1.10),
    VehicleClass(id="compactor", label="Soil compactor", duty_base=0.55, wear_rate=1.15),
    VehicleClass(id="support", label="Light support vehicle", duty_base=0.35, wear_rate=0.80),
)

# Relative class weights (normalised); an earthworks-leaning heavy fleet.
_VEHICLE_MIX: dict[str, float] = {
    "haul_truck": 0.30,
    "wheel_loader": 0.22,
    "excavator": 0.24,
    "compactor": 0.10,
    "support": 0.14,
}

_REGIONS: tuple[Region, ...] = (
    Region(
        id="arid_highland",
        label="Arid highland mine (hot, dusty, high altitude)",
        ambient_c_mean=22.0,
        ambient_c_amplitude=14.0,
        altitude_m=2400.0,
        terrain_roughness=0.75,
        wear_modifier=1.30,  # heat + dust accelerate filter/oil/thermal wear
        source="Köppen BWk arid-highland climate normals; IRI band 'unpaved/poor' (~8-12 m/km)",
    ),
    Region(
        id="temperate_lowland",
        label="Temperate lowland haulage (mild, paved highway)",
        ambient_c_mean=14.0,
        ambient_c_amplitude=10.0,
        altitude_m=120.0,
        terrain_roughness=0.20,
        wear_modifier=0.90,  # mild + smooth = gentlest on the machine
        source="Köppen Cfb temperate-oceanic normals; IRI band 'good paved' (~2-4 m/km)",
    ),
    Region(
        id="tropical_humid",
        label="Tropical humid earthworks (hot, wet, off-road)",
        ambient_c_mean=27.0,
        ambient_c_amplitude=6.0,
        altitude_m=200.0,
        terrain_roughness=0.85,
        wear_modifier=1.25,  # humidity + rough off-road raise wear hazards
        source="Köppen Af tropical-rainforest normals; IRI band 'off-road/very poor' (>12 m/km)",
    ),
    Region(
        id="cold_continental",
        label="Cold continental site (cold winters, mixed roads)",
        ambient_c_mean=4.0,
        ambient_c_amplitude=18.0,
        altitude_m=600.0,
        terrain_roughness=0.45,
        wear_modifier=1.10,  # thermal cycling / cold starts add hazard
        source="Köppen Dfb cold-continental normals; IRI band 'fair paved' (~4-6 m/km)",
    ),
)

_CONTRACTS: tuple[Contract, ...] = (
    Contract(id="ch_andes", label="Highland mine haulage", region_id="arid_highland", units=34, duty_bias=0.12),
    Contract(id="ct_highway", label="Lowland highway logistics", region_id="temperate_lowland", units=28, duty_bias=-0.05),
    Contract(id="cw_delta", label="Tropical delta earthworks", region_id="tropical_humid", units=24, duty_bias=0.08),
    Contract(id="cc_north", label="Northern site construction", region_id="cold_continental", units=18, duty_bias=0.00),
)

_DEFAULT_FLEET = FleetSpec(
    operator_name="Meridian Heavy Fleet Co. (fictional)",
    vehicle_classes=_VEHICLE_CLASSES,
    vehicle_mix=_VEHICLE_MIX,
    regions=_REGIONS,
    contracts=_CONTRACTS,
    build_year_min=1998,
    build_year_max=2024,
    build_year_mode=2016,  # mode skewed recent, with a tail of legacy units
    units_per_contract_sd_frac=0.10,
)


def default_config() -> ForgeConfig:
    """A complete, runnable, public-grounded Tier-1 config (~104 units × 90 days)."""
    return ForgeConfig(fleet=_DEFAULT_FLEET).validate()


# --- JSON (de)serialisation ---------------------------------------------------
# A config file overrides any subset of the defaults; nested fleet keys merge
# onto the default fleet so a small file can tweak just `seed` or `days`.


def _vehicle_class(d: dict) -> VehicleClass:
    return VehicleClass(**d)


def _region(d: dict) -> Region:
    return Region(**d)


def _contract(d: dict) -> Contract:
    return Contract(**d)


def _fleet_from_dict(d: dict, base: FleetSpec) -> FleetSpec:
    """Merge a fleet dict onto ``base`` (only provided keys override)."""
    kwargs: dict = {}
    if "operator_name" in d:
        kwargs["operator_name"] = d["operator_name"]
    if "vehicle_classes" in d:
        kwargs["vehicle_classes"] = tuple(_vehicle_class(x) for x in d["vehicle_classes"])
    if "vehicle_mix" in d:
        kwargs["vehicle_mix"] = dict(d["vehicle_mix"])
    if "regions" in d:
        kwargs["regions"] = tuple(_region(x) for x in d["regions"])
    if "contracts" in d:
        kwargs["contracts"] = tuple(_contract(x) for x in d["contracts"])
    for key in ("build_year_min", "build_year_max", "build_year_mode", "units_per_contract_sd_frac"):
        if key in d:
            kwargs[key] = d[key]
    return replace(base, **kwargs)


def config_from_dict(d: dict) -> ForgeConfig:
    """Build a validated :class:`ForgeConfig` from a dict, merging onto defaults."""
    base = default_config()
    fleet = _fleet_from_dict(d.get("fleet", {}), base.fleet)
    top = {
        k: v
        for k, v in d.items()
        if k in {"days", "resolution", "failure_horizon_h", "obvious_outlier_rate", "seed"}
    }
    # anomaly_rates merges onto the defaults (a small file can tweak one type).
    if "anomaly_rates" in d:
        top["anomaly_rates"] = {**DEFAULT_ANOMALY_RATES, **dict(d["anomaly_rates"])}
    return replace(base, fleet=fleet, **top).validate()


def load_config(path: str | Path | None) -> ForgeConfig:
    """Load a JSON config file, or the bundled default when ``path`` is None."""
    if path is None:
        return default_config()
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return config_from_dict(data)


__all__ = [
    "VehicleClass",
    "Region",
    "Contract",
    "FleetSpec",
    "ForgeConfig",
    "RESOLUTION_STEP_HOURS",
    "DEFAULT_RESOLUTION",
    "default_config",
    "config_from_dict",
    "load_config",
]
