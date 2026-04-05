"""
job_sources/remoteok.py — Backward-compatibility shim.

The RemoteOKClient implementation has moved to plugins/sources/remoteok/plugin.py
and is loaded into the SOURCES registry via the plugin loader.
This module re-exports the class and ensures the mock patch target
``patch("job_sources.remoteok.requests.get")`` resolves correctly.
"""

# NOTE: keep `import requests` at the top of this file.
# Test mocks use patch("job_sources.remoteok.requests.get") — if this import is removed,
# those mock targets will stop resolving silently.
import requests  # noqa: F401 — kept so patch("job_sources.remoteok.requests.get") resolves

from job_sources import SOURCES as _SOURCES

RemoteOKClient = _SOURCES.get("remoteok")

__all__ = ["RemoteOKClient"]
