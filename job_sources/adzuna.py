"""
job_sources/adzuna.py — Backward-compatibility shim.

The AdzunaClient implementation has moved to plugins/sources/adzuna/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class and ensures the mock patch target
``patch("job_sources.adzuna.requests.get")`` resolves correctly.
"""

import requests  # noqa: F401 — kept so patch("job_sources.adzuna.requests.get") resolves
import time  # noqa: F401 — kept so patch("job_sources.adzuna.time.sleep") resolves

from job_sources import SOURCES as _SOURCES

AdzunaClient = _SOURCES["adzuna"]

__all__ = ["AdzunaClient"]
