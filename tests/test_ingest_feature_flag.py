"""Tests for the JOB_AGGREGATOR_SOURCES feature flag routing in ingest.py.

Verifies:
- When unset, all sources use the legacy path
- When set to "arbeitnow", arbeitnow uses JobAggregatorProvider
- The remaining sources use LegacyInTreeProvider
- An enabled=false source in the aggregator set is skipped correctly
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_PROVIDERS = {
    "provider_order": [],
    "llm": {},
    "job_sources": {
        "arbeitnow": {"enabled": True},
        "adzuna": {"enabled": True, "app_id": "abc", "app_key": "def"},
        "jooble": {"enabled": False, "api_key": ""},
    },
}

_CONFIG = {
    "search": {
        "what": "software engineer",
        "country": "us",
        "max_pages": 1,
        "max_days_old": 7,
        "results_per_page": 10,
    }
}


def _make_mock_client(source: str):
    client = MagicMock()
    client.SOURCE = source
    return client


@pytest.fixture(autouse=True)
def _no_ensure_plugins(monkeypatch):
    """Prevent ensure_plugins_registered from touching the filesystem."""
    monkeypatch.setattr(
        "ingest.ensure_plugins_registered" if hasattr(__import__("ingest"), "ensure_plugins_registered") else "job_sources.auto_register.ensure_plugins_registered",
        lambda *a, **kw: None,
    )


def test_build_source_clients_no_flag_uses_legacy(monkeypatch):
    """When JOB_AGGREGATOR_SOURCES is unset, all sources use the legacy path."""
    monkeypatch.delenv("JOB_AGGREGATOR_SOURCES", raising=False)

    mock_client = _make_mock_client("arbeitnow")

    with patch("ingest.make_enabled_sources", return_value=[mock_client]) as mock_legacy:
        with patch("job_sources.auto_register.ensure_plugins_registered"):
            from ingest import _build_source_clients
            clients = _build_source_clients(_PROVIDERS, _CONFIG, "/tmp/providers.json")

    mock_legacy.assert_called_once()
    assert clients == [mock_client]


def test_build_source_clients_flag_routes_arbeitnow_to_aggregator(monkeypatch):
    """With JOB_AGGREGATOR_SOURCES=arbeitnow, arbeitnow uses JobAggregatorProvider."""
    monkeypatch.setenv("JOB_AGGREGATOR_SOURCES", "arbeitnow")

    agg_client = _make_mock_client("arbeitnow")
    legacy_client = _make_mock_client("adzuna")

    with patch("job_sources.auto_register.ensure_plugins_registered"):
        with patch(
            "job_sources.aggregator_provider.JobAggregatorProvider.make_clients",
            return_value=[agg_client],
        ):
            with patch(
                "job_sources.legacy_provider.LegacyInTreeProvider.make_clients",
                return_value=[legacy_client],
            ):
                from ingest import _build_source_clients
                clients = _build_source_clients(
                    _PROVIDERS, _CONFIG, "/tmp/providers.json"
                )

    # Aggregator called first, legacy second
    assert clients[0].SOURCE == "arbeitnow"
    assert clients[1].SOURCE == "adzuna"


def test_build_source_clients_flag_disables_named_source_for_legacy(monkeypatch):
    """Named sources have enabled=False in the providers dict passed to legacy."""
    monkeypatch.setenv("JOB_AGGREGATOR_SOURCES", "arbeitnow")

    captured_legacy_providers = []

    def capture_legacy(self, *, providers_data, search):
        captured_legacy_providers.append(dict(providers_data))
        return []

    with patch("job_sources.auto_register.ensure_plugins_registered"):
        with patch(
            "job_sources.aggregator_provider.JobAggregatorProvider.make_clients",
            return_value=[],
        ):
            with patch(
                "job_sources.legacy_provider.LegacyInTreeProvider.make_clients",
                new=capture_legacy,
            ):
                from ingest import _build_source_clients
                _build_source_clients(_PROVIDERS, _CONFIG, "/tmp/providers.json")

    assert captured_legacy_providers, "Legacy provider should have been called"
    legacy_sources = captured_legacy_providers[0].get("job_sources", {})
    # arbeitnow should be disabled in the dict passed to legacy
    assert legacy_sources.get("arbeitnow", {}).get("enabled") is False
