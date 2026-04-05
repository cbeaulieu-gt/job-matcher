"""
job_sources/adzuna.py — Backward-compatibility shim.

The AdzunaClient implementation has moved to plugins/sources/adzuna/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class for backward-compatible imports.
"""

# NOTE: tests now patch the real module directly:
#   patch("job_sources._plugin_adzuna.requests.get")
#   patch("job_sources._plugin_adzuna.time.sleep")
# The imports below are kept only to preserve the attribute chain for any
# external code that may still reference job_sources.adzuna.requests directly.
import requests  # noqa: F401
import time  # noqa: F401

from job_sources import SOURCES as _SOURCES

AdzunaClient = _SOURCES.get("adzuna")
if AdzunaClient is None:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "job_sources.adzuna: plugin failed to load — AdzunaClient is None; "
        "any code that instantiates it will raise TypeError."
    )

__all__ = ["AdzunaClient"]
