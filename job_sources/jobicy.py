"""
job_sources/jobicy.py — Backward-compatibility shim.

The JobicyClient implementation has moved to plugins/sources/jobicy/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class and ensures the mock patch target
``patch("job_sources.jobicy.requests.get")`` resolves correctly.
"""

import requests  # noqa: F401 — kept so patch("job_sources.jobicy.requests.get") resolves

from job_sources import SOURCES as _SOURCES

JobicyClient = _SOURCES["jobicy"]

__all__ = ["JobicyClient"]
