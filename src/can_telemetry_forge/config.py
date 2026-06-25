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
from .labels import FAILURE_MODES

# Failure-mode ids a hazard_mult map may key on (validated against the label model).
_FAILURE_MODE_IDS: frozenset[str] = frozenset(FAILURE_MODES)

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
class EquipmentModel:
    """A concrete make/model within a vehicle class (Tier-2 diversity, F5).

    A real fleet is not just classes of identical machines: two haul trucks of
    different makes run hotter or cooler and fail differently. A model carries a
    **per-mode hazard multiplier** (so the same class can host a robust model and a
    failure-prone one) and small **signal baseline offsets** that shift its thermal
    and mechanical signature without breaking the documented J1939 ranges. Modeled
    as **documented plausibility** for a fictional operator — never a real spec
    sheet (the ADR-011 private-boundary note holds).

    The optional ``build_year_min`` lets a model gate its own CAN capability era
    floor (a model that only ever shipped Modern hardware), refining the coarse
    per-era whitelist of §4 toward a per-model one — but defaults to ``None`` so the
    class-level age curve is unchanged unless a model opts in.

    Attributes:
        id / label: identifiers.
        vehicle_class_id: the :class:`VehicleClass` this model belongs to.
        hazard_mult: per-failure-mode hazard multipliers (``overheat`` /
            ``oil_starve`` / ``bearing``); missing modes default to ``1.0``.
        coolant_offset_c / oil_offset_kpa / vibration_offset_mms: small additive
            shifts to the model's baseline signature (engineering units).
        build_year_min: optional per-model earliest build year (capability floor).
    """

    id: str
    label: str
    vehicle_class_id: str
    hazard_mult: dict[str, float] = field(default_factory=dict)
    coolant_offset_c: float = 0.0
    oil_offset_kpa: float = 0.0
    vibration_offset_mms: float = 0.0
    build_year_min: int | None = None


@dataclass(frozen=True)
class Season:
    """A named, configurable seasonal modifier (Tier-2 diversity, F5).

    Seasonality is the knob a future **drift demo** (the 4th vitrine) shifts: a
    heatwave / cold-snap / wet-season episode that moves the whole fleet's ambient
    baseline and tilts its failure hazards, without touching the generator. A
    season is **documented plausibility** (a public-climate-class anomaly), applied
    on top of each region's own ambient curve.

    Attributes:
        id / label: identifiers (``"baseline"`` is the neutral default).
        ambient_delta_c: additive shift to every unit's ambient temperature (°C).
        wear_mult: multiplier on accumulated-wear hazard gain (a wet/hot season
            accelerates degradation); ``1.0`` is neutral.
        hazard_mult: per-failure-mode hazard multipliers (e.g. a heatwave raises
            ``overheat``); missing modes default to ``1.0``.
        source: the public climate-anomaly class the constants are grounded in.
    """

    id: str
    label: str
    ambient_delta_c: float = 0.0
    wear_mult: float = 1.0
    hazard_mult: dict[str, float] = field(default_factory=dict)
    source: str = ""


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
    equipment_models: tuple[EquipmentModel, ...] = ()


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
    season: Season = field(default_factory=lambda: SEASONS["baseline"])  # Tier-2 (F5)
    # Emit the byte-level corrupted CAN frames as a `can_frames` side table (F6,
    # ADR-019). Off by default — the decoded readings are the product; the raw frames
    # are an opt-in artifact for byte-level QA/teaching. Only frame-fault cells appear.
    emit_raw_frames: bool = False
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
        # Tier-2 (F5): equipment models must reference known classes; every class in
        # the mix that has any models must be fully covered (so every sampled unit of
        # that class can be assigned a model), and hazard keys must be real modes.
        model_class_ids = {m.vehicle_class_id for m in f.equipment_models}
        unknown_model_classes = model_class_ids - class_ids
        if unknown_model_classes:
            raise ValueError(f"equipment_models reference unknown classes: {unknown_model_classes}")
        for m in f.equipment_models:
            bad_modes = set(m.hazard_mult) - _FAILURE_MODE_IDS
            if bad_modes:
                raise ValueError(f"equipment_model {m.id!r} hazard_mult has unknown modes: {bad_modes}")
            if any(v < 0 for v in m.hazard_mult.values()):
                raise ValueError(f"equipment_model {m.id!r} hazard_mult must be non-negative")
            if m.build_year_min is not None and not (
                f.build_year_min <= m.build_year_min <= f.build_year_max
            ):
                raise ValueError(
                    f"equipment_model {m.id!r} build_year_min out of fleet range"
                )
        bad_season_modes = set(self.season.hazard_mult) - _FAILURE_MODE_IDS
        if bad_season_modes:
            raise ValueError(f"season {self.season.id!r} hazard_mult has unknown modes: {bad_season_modes}")
        if self.season.wear_mult < 0 or any(v < 0 for v in self.season.hazard_mult.values()):
            raise ValueError(f"season {self.season.id!r} multipliers must be non-negative")
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
    # --- Tier-2 (F5) broadens the international footprint with two more contrasting
    # public-grounded deployments (see DATA_DESIGN §6/§9). ---
    Region(
        id="hot_desert_lowland",
        label="Hot desert logistics (extreme heat, low altitude, graded tracks)",
        ambient_c_mean=29.0,
        ambient_c_amplitude=16.0,
        altitude_m=80.0,
        terrain_roughness=0.55,
        wear_modifier=1.35,  # extreme heat + dust = harshest thermal/filter load
        source="Köppen BWh hot-desert normals; IRI band 'poor unsealed' (~6-9 m/km)",
    ),
    Region(
        id="alpine_subarctic",
        label="Alpine subarctic works (severe cold, very high altitude, rough)",
        ambient_c_mean=-3.0,
        ambient_c_amplitude=20.0,
        altitude_m=3000.0,
        terrain_roughness=0.70,
        wear_modifier=1.20,  # deep-cold starts + thin air + rough terrain
        source="Köppen Dfc subarctic normals; IRI band 'rough mountain track' (~8-11 m/km)",
    ),
)

_CONTRACTS: tuple[Contract, ...] = (
    Contract(id="ch_andes", label="Highland mine haulage", region_id="arid_highland", units=34, duty_bias=0.12),
    Contract(id="ct_highway", label="Lowland highway logistics", region_id="temperate_lowland", units=28, duty_bias=-0.05),
    Contract(id="cw_delta", label="Tropical delta earthworks", region_id="tropical_humid", units=24, duty_bias=0.08),
    Contract(id="cc_north", label="Northern site construction", region_id="cold_continental", units=18, duty_bias=0.00),
    # Tier-2 (F5): two more contracts on the broadened regions.
    Contract(id="cd_dunes", label="Desert pipeline logistics", region_id="hot_desert_lowland", units=22, duty_bias=0.06),
    Contract(id="ca_pass", label="Alpine pass roadworks", region_id="alpine_subarctic", units=14, duty_bias=0.03),
)

# --- Equipment models (Tier-2, F5) -------------------------------------------
# Concrete makes/models within the vehicle classes: a robust and a failure-prone
# variant per heavy class, so the same class hosts genuinely different reliability
# and signatures. Documented plausibility for the FICTIONAL operator — never a real
# spec sheet (ADR-011 boundary holds). Light support vehicles are left class-only
# (a single generic profile) to keep the catalog readable.
_EQUIPMENT_MODELS: tuple[EquipmentModel, ...] = (
    # Haul trucks: an old-school robust hauler vs a hotter-running high-output one.
    EquipmentModel(
        id="ht_atlas",
        label="Atlas RT-90 rigid hauler (robust, runs cool)",
        vehicle_class_id="haul_truck",
        hazard_mult={"overheat": 0.85, "oil_starve": 0.90, "bearing": 1.00},
        coolant_offset_c=-3.0,
        oil_offset_kpa=15.0,
    ),
    EquipmentModel(
        id="ht_vulcan",
        label="Vulcan HX high-output hauler (runs hot, modern only)",
        vehicle_class_id="haul_truck",
        hazard_mult={"overheat": 1.30, "oil_starve": 1.05, "bearing": 1.10},
        coolant_offset_c=4.0,
        vibration_offset_mms=0.4,
        build_year_min=2015,  # only ever shipped Modern-era hardware
    ),
    # Wheel loaders: a reliable workhorse vs a vibration-prone budget model.
    EquipmentModel(
        id="wl_terra",
        label="Terra L5 wheel loader (balanced)",
        vehicle_class_id="wheel_loader",
        hazard_mult={"bearing": 0.95},
    ),
    EquipmentModel(
        id="wl_drako",
        label="Drako WL budget loader (bearing-prone)",
        vehicle_class_id="wheel_loader",
        hazard_mult={"bearing": 1.35, "oil_starve": 1.10},
        vibration_offset_mms=0.8,
        oil_offset_kpa=-12.0,
    ),
    # Excavators: a clean modern model vs an oil-starvation-prone legacy line.
    EquipmentModel(
        id="ex_orion",
        label="Orion 360 excavator (clean modern)",
        vehicle_class_id="excavator",
        hazard_mult={"overheat": 0.95, "oil_starve": 0.90},
    ),
    EquipmentModel(
        id="ex_kratoken",
        label="Kratoken EX legacy excavator (oil-starve-prone)",
        vehicle_class_id="excavator",
        hazard_mult={"oil_starve": 1.40},
        oil_offset_kpa=-18.0,
        coolant_offset_c=2.0,
    ),
)

# --- Seasons (Tier-2, F5) ----------------------------------------------------
# Named seasonal modifiers applied on top of every region's own ambient curve. The
# neutral "baseline" is the default; the others are the knob a future drift demo
# (the 4th vitrine) shifts. Documented plausibility from public climate-anomaly
# classes — never private data.
SEASONS: dict[str, Season] = {
    "baseline": Season(
        id="baseline",
        label="Baseline (no seasonal anomaly)",
        source="Region climate normals only (no anomaly applied)",
    ),
    "heatwave": Season(
        id="heatwave",
        label="Heatwave episode (hot anomaly)",
        ambient_delta_c=8.0,
        wear_mult=1.20,
        hazard_mult={"overheat": 1.60, "oil_starve": 1.20},
        source="Public heatwave anomaly class (sustained +6-10 °C over normals)",
    ),
    "cold_snap": Season(
        id="cold_snap",
        label="Cold snap episode (cold anomaly)",
        ambient_delta_c=-12.0,
        wear_mult=1.15,
        hazard_mult={"oil_starve": 1.25, "bearing": 1.15},
        source="Public cold-snap anomaly class (sustained -8-14 °C below normals)",
    ),
    "wet_season": Season(
        id="wet_season",
        label="Wet season (humid anomaly)",
        ambient_delta_c=2.0,
        wear_mult=1.25,
        hazard_mult={"bearing": 1.20, "oil_starve": 1.10},
        source="Public wet-season anomaly class (elevated humidity, accelerated wear)",
    ),
}

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
    equipment_models=_EQUIPMENT_MODELS,
)


def default_config() -> ForgeConfig:
    """A complete, runnable, public-grounded config (~140 units × 90 days).

    Ships the Tier-2 (F5) diversity: six contrasting public-grounded regions, a
    catalog of equipment models with distinct reliability/signature profiles, and a
    neutral ``baseline`` season (the drift knob other seasons shift)."""
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


def _equipment_model(d: dict) -> EquipmentModel:
    return EquipmentModel(**d)


def _season(d: dict) -> Season:
    return Season(**d)


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
    if "equipment_models" in d:
        kwargs["equipment_models"] = tuple(_equipment_model(x) for x in d["equipment_models"])
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
        if k in {"days", "resolution", "failure_horizon_h", "obvious_outlier_rate",
                 "emit_raw_frames", "seed"}
    }
    # anomaly_rates merges onto the defaults (a small file can tweak one type).
    if "anomaly_rates" in d:
        top["anomaly_rates"] = {**DEFAULT_ANOMALY_RATES, **dict(d["anomaly_rates"])}
    # season is either a named preset ("heatwave") or an inline Season dict.
    if "season" in d:
        top["season"] = resolve_season(d["season"])
    return replace(base, fleet=fleet, **top).validate()


def resolve_season(spec: str | dict) -> Season:
    """Turn a config ``season`` value into a :class:`Season`.

    A string selects a named preset from :data:`SEASONS` (``"heatwave"``,
    ``"cold_snap"``, ``"wet_season"``, ``"baseline"``); a dict defines one inline.
    """
    if isinstance(spec, str):
        try:
            return SEASONS[spec]
        except KeyError as exc:
            raise ValueError(
                f"unknown season {spec!r}; known: {sorted(SEASONS)}"
            ) from exc
    return _season(spec)


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
    "EquipmentModel",
    "Season",
    "FleetSpec",
    "ForgeConfig",
    "RESOLUTION_STEP_HOURS",
    "DEFAULT_RESOLUTION",
    "SEASONS",
    "default_config",
    "config_from_dict",
    "load_config",
    "resolve_season",
]
