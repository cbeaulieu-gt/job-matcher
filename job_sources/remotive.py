"""
job_sources/remotive.py — Backward-compatibility shim.

The RemotiveClient implementation has moved to plugins/sources/remotive/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class for backward-compatible imports.
"""

# NOTE: tests now patch the real module directly:
#   patch("job_sources._plugin_remotive.requests.get")
# The import below is kept only to preserve the attribute chain for any
# external code that may still reference job_sources.remotive.requests directly.
import requests  # noqa: F401

from job_sources import SOURCES as _SOURCES

RemotiveClient = _SOURCES.get("remotive")
if RemotiveClient is None:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "job_sources.remotive: plugin failed to load — RemotiveClient is None; "
        "any code that instantiates it will raise TypeError."
    )

__all__ = ["RemotiveClient"]
