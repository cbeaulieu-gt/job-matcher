"""
job_sources/usajobs.py — Backward-compatibility shim.

The USAJobsClient implementation has moved to plugins/sources/usajobs/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class and module-level helpers, and ensures the mock
patch target ``patch("job_sources.usajobs.requests.get")`` resolves correctly.
"""

import requests  # noqa: F401 — kept so patch("job_sources.usajobs.requests.get") resolves

from job_sources import SOURCES as _SOURCES

USAJobsClient = _SOURCES["usajobs"]

# Re-export module-level helper from the plugin for tests that import it directly.
from job_sources._plugin_usajobs import _parse_float  # noqa: F401

__all__ = ["USAJobsClient", "_parse_float"]
