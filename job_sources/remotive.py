"""
job_sources/remotive.py — Backward-compatibility shim.

The RemotiveClient implementation has moved to plugins/sources/remotive/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class and ensures the mock patch target
``patch("job_sources.remotive.requests.get")`` resolves correctly.
"""

import requests  # noqa: F401 — kept so patch("job_sources.remotive.requests.get") resolves

from job_sources import SOURCES as _SOURCES

RemotiveClient = _SOURCES["remotive"]

__all__ = ["RemotiveClient"]
