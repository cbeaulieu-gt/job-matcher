"""
job_sources/jobicy.py — Backward-compatibility shim.

The JobicyClient implementation has moved to plugins/sources/jobicy/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class for backward-compatible imports.
"""

# NOTE: tests now patch the real module directly:
#   patch("job_sources._plugin_jobicy.requests.get")
# The import below is kept only to preserve the attribute chain for any
# external code that may still reference job_sources.jobicy.requests directly.
import requests  # noqa: F401

from job_sources import SOURCES as _SOURCES

JobicyClient = _SOURCES.get("jobicy")
if JobicyClient is None:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "job_sources.jobicy: plugin failed to load — JobicyClient is None; "
        "any code that instantiates it will raise TypeError."
    )

__all__ = ["JobicyClient"]
