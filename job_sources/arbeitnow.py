"""
job_sources/arbeitnow.py — Backward-compatibility shim.

The ArbeitnowClient implementation has moved to plugins/sources/arbeitnow/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class and private helpers, and ensures the mock patch
target ``patch("job_sources.arbeitnow.requests.get")`` resolves correctly.
"""

import requests  # noqa: F401 — kept so patch("job_sources.arbeitnow.requests.get") resolves

from job_sources import SOURCES as _SOURCES

ArbeitnowClient = _SOURCES["arbeitnow"]

# Re-export module-level helpers from the plugin for tests that import them directly.
# The loader registers plugin modules in sys.modules as job_sources._plugin_<name>.
from job_sources._plugin_arbeitnow import (  # noqa: F401
    _CONTRACT_TIME_MAP,
    _strip_html,
    _unix_to_iso,
)

__all__ = ["ArbeitnowClient", "_CONTRACT_TIME_MAP", "_strip_html", "_unix_to_iso"]
