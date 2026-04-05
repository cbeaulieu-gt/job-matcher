"""
job_sources/remoteok.py — Backward-compatibility shim.

The RemoteOKClient implementation has moved to plugins/sources/remoteok/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class for backward-compatible imports.
"""

# NOTE: tests now patch the real module directly:
#   patch("job_sources._plugin_remoteok.requests.get")
# The import below is kept only to preserve the attribute chain for any
# external code that may still reference job_sources.remoteok.requests directly.
import requests  # noqa: F401

from job_sources import SOURCES as _SOURCES

RemoteOKClient = _SOURCES.get("remoteok")
if RemoteOKClient is None:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "job_sources.remoteok: plugin failed to load — RemoteOKClient is None; "
        "any code that instantiates it will raise TypeError."
    )

__all__ = ["RemoteOKClient"]
