"""
job_sources/the_muse.py — Backward-compatibility shim.

The TheMuseClient implementation has moved to plugins/sources/the_muse/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class and ensures the mock patch target
``patch("job_sources.the_muse.requests.get")`` resolves correctly.
"""

import requests  # noqa: F401 — kept so patch("job_sources.the_muse.requests.get") resolves

from job_sources import SOURCES as _SOURCES

TheMuseClient = _SOURCES["the_muse"]

__all__ = ["TheMuseClient"]
