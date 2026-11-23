"""Docs say what the code does (P1-04: R4-T10-e, R4-T11-e, R4-T4-a, R4-T3-d).

Each test reads a sentence a reader relies on and checks it against the code it
describes, so the sentence going stale turns this file red.
"""

from __future__ import annotations

import re
from pathlib import Path

from validation import reference

from can_telemetry_forge.config import ForgeConfig, default_config

ROOT = Path(__file__).resolve().parents[1]
_NUMBER_WORDS = {2: "two", 3: "three", 4: "four"}


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _section(text: str, heading_re: str) -> str:
    """The text from a heading matching ``heading_re`` up to the next heading of that level."""
    m = re.search(heading_re, text, flags=re.MULTILINE)
    assert m, f"heading {heading_re!r} not found"
    level = re.match(r"#+", m.group(0)).group(0)  # type: ignore[union-attr]
    rest = text[m.end():]
    nxt = re.search(rf"^{level} ", rest, flags=re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def _adr(n: int) -> str:
    return _section(_read("docs/DECISIONS.md"), rf"^## ADR-{n:03d} ")


# --- R4-T10-e: in_spec skips rows with an injected defect ------------------------


def test_readme_in_spec_says_clean_values() -> None:
    readme = _read("README.md")
    start = readme.index("- **`in_spec`**")
    bullet = readme[start : readme.index("\n- ", start + 1)]
    assert "every clean value" in bullet and "is_outlier" in bullet and "excluded" in bullet, bullet
    adr = _adr(17)
    start = adr.index("- **`in_spec`**")
    adr_bullet = adr[start : adr.index("\n- ", start + 1)]
    assert "clean value" in adr_bullet and "is_outlier" in adr_bullet, adr_bullet


# --- R4-T11-e: ADR-017 and the ved adapter describe only what the code has --------


def test_no_ved_handle_config_key_is_claimed() -> None:
    assert not hasattr(ForgeConfig, "ved_handle")
    for name, text in (("ADR-017", _adr(17)), ("validation/reference.py", _read("validation/reference.py"))):
        assert not re.search(r"`ved_handle`\s+config", text), f"{name} claims a ved_handle config key"
    # Every ADR-017 mention of the key must sit in a sentence denying it exists.
    for sentence in re.split(r"(?<=[.;])\s+", _adr(17)):
        if "`ved_handle`" in sentence:
            assert re.search(r"\bno `ved_handle` key\b", sentence), sentence


def test_adr017_names_the_channels_ved_actually_compares() -> None:
    adr = _adr(17)
    n = len(reference._VED_COLUMN_MAP)
    assert re.search(rf"\bcompares\s+(?:only\s+)?{_NUMBER_WORDS[n]}\b", adr), (
        f"ADR-017 must say the adapter compares {_NUMBER_WORDS[n]} channels"
    )
    for ved_col in reference._VED_COLUMN_MAP.values():
        assert ved_col in adr, f"ADR-017 does not name compared column {ved_col}"


def test_ved_reads_only_the_compared_columns(tmp_path: Path) -> None:
    import zipfile

    assert set(reference._VED_USECOLS) == set(reference._VED_COLUMN_MAP.values())
    assert "report's context" not in _read("validation/reference.py")
    # The real reader, on a mirror carrying extra columns, returns only the mapped ones.
    cols = [*reference._VED_COLUMN_MAP.values(), "MAF_g_per_sec", "Vehicle_Speed_km_h"]
    zpath = tmp_path / "mirror.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("combustion_master.csv", ",".join(cols) + "\n" + ",".join("1" * len(cols)) + "\n")
    frame = reference._read_ved_master(zpath)
    assert set(frame.columns) == set(reference._VED_COLUMN_MAP.values())
    assert re.search(r"nothing else is\s+read from the VED file", _adr(17))


# --- R4-T4-a: determinism is a SeedSequence spawn tree, not one shared generator --

_SINGLE_GENERATOR = re.compile(r"(single|one)\s+seeded\s+(`numpy`\s+|random\s+)?generator", re.I)


def test_seed_tree_docs_describe_spawned_children() -> None:
    sections = {
        "DATA_DESIGN §11": _section(_read("docs/DATA_DESIGN.md"), r"^## 11\. "),
        "ARCHITECTURE design rules": _section(_read("docs/ARCHITECTURE.md"), r"^## Design rules"),
        "DATA_DICTIONARY determinism": _section(_read("docs/DATA_DICTIONARY.md"), r"^## Determinism"),
    }
    for name, text in sections.items():
        assert not _SINGLE_GENERATOR.search(text), f"{name} still claims a single shared generator"
        assert "SeedSequence" in text and "spawn" in text, f"{name} does not describe the seed tree"
        assert re.search(r"one\s+(child\s+)?per\s+unit\s+per\s+stage", text), f"{name} does not describe per-unit streams"
        assert not re.search(r"\b(shared|global)\s+(seeded\s+)?(`numpy`\s+)?generator", text, re.I), name
    doc = _read("src/can_telemetry_forge/config.py").split('"""')[1]
    assert not _SINGLE_GENERATOR.search(doc) and "SeedSequence" in doc, "config.py module docstring"


def test_adr005_carries_a_dated_seed_tree_note() -> None:
    adr = _adr(5)
    assert re.search(r"\*\*(Addendum|Note)[^*]*20\d\d-\d\d-\d\d", adr), "ADR-005 has no dated note"
    assert "SeedSequence" in adr and "spawn" in adr


def test_forgeconfig_has_no_unused_master_rng() -> None:
    assert not hasattr(ForgeConfig, "rng"), "ForgeConfig.rng() has no callers (R4-T4-a)"


# --- R4-T3-d: one global class mix; ADR-011's fleet size ------------------------


def test_data_design_does_not_claim_a_per_contract_mix() -> None:
    s3 = _section(_read("docs/DATA_DESIGN.md"), r"^## 3\. ")
    assert not re.search(r"vary\s+\*{0,2}by contract", s3), "§3 still says the mix varies by contract"
    assert "vehicle_mix" in s3 and "duty_bias" in s3
    assert re.search(r"every contract draws\s+its units from the same weights", s3)
    assert not re.search(r"(mix|weights)[^.]{0,40}(varies|differs|own)", s3, re.I), "§3 implies a per-contract mix"


def test_adr011_states_the_default_expected_fleet_size() -> None:
    expected = sum(c.units for c in default_config().fleet.contracts)
    adr = _adr(11)
    assert re.search(r"\*\*(Addendum|Note)[^*]*20\d\d-\d\d-\d\d", adr), "ADR-011 has no dated note"
    stated = re.findall(r"expect\s+\*\*(\d+)\*\*\s+units", adr)
    assert stated == [str(expected)], f"ADR-011 states {stated}, default expects {expected}"


def test_ved_handle_sources_are_flag_then_env_then_default(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    for key in [k for k in __import__("os").environ if "VED" in k.upper() or "KAGGLE" in k.upper()]:
        monkeypatch.delenv(key)
    monkeypatch.setenv("KAGGLE_VED", "other/source")  # not a documented source
    assert reference._resolve_ved_handle(None) == reference.DEFAULT_VED_HANDLE
    monkeypatch.setenv("FORGE_VED_HANDLE", "env/handle")
    assert reference._resolve_ved_handle(None) == "env/handle"
    assert reference._resolve_ved_handle("flag/handle") == "flag/handle"
