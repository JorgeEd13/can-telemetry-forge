"""can-telemetry-forge — synthetic, J1939-grounded heavy-equipment telemetry.

A clean-room generator of synthetic predictive-maintenance datasets. The package
is built phase by phase (see ``docs/ROADMAP.md``); this module only exposes the
version and is intentionally light so importing it stays cheap and side-effect
free.
"""

from __future__ import annotations

from importlib import metadata

# Single source of truth for the version is the installed package metadata
# (which setuptools fills from ``pyproject.toml``). The literal fallback keeps
# ``forge --version`` and ``import can_telemetry_forge`` working when the package
# is run from a source checkout that was never installed.
try:
    __version__ = metadata.version("can-telemetry-forge")
except metadata.PackageNotFoundError:  # pragma: no cover - source-tree fallback
    __version__ = "0.2.0"

__all__ = ["__version__"]
