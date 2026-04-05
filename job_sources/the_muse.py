"""
job_sources/the_muse.py — Backward-compatibility shim.

The TheMuseClient implementation has moved to plugins/sources/the_muse/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class for backward-compatible imports.
"""

# NOTE: tests now patch the real module directly:
#   patch("job_sources._plugin_the_muse.requests.get")
# The import below is kept only to preserve the attribute chain for any
# external code that may still reference job_sources.the_muse.requests directly.
import requests  # noqa: F401

from job_sources import SOURCES as _SOURCES

TheMuseClient = _SOURCES.get("the_muse")
if TheMuseClient is None:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "job_sources.the_muse: plugin failed to load — TheMuseClient is None; "
        "any code that instantiates it will raise TypeError."
    )

__all__ = ["TheMuseClient"]
