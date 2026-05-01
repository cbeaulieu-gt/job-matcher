"""Tests for LegacyInTreeProvider.

Verifies that the legacy shim satisfies the SourceProvider Protocol
by wrapping auto_register and job_sources.make_enabled_sources.
"""

from __future__ import annotations

import sys
import os
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


_PROVIDERS = {
    "provider_order": [],
    "llm": {},
    "job_sources": {
        "arbeitnow": {"enabled": True},
    },
}

_SEARCH = {
    "what": "software engineer",
    "country": "us",
    "max_pages": 1,
    "max_days_old": 7,
    "results_per_page": 10,
}


def test_legacy_provider_satisfies_source_provider_protocol():
    """LegacyInTreeProvider instances satisfy the SourceProvider Protocol."""
    from job_sources.legacy_provider import LegacyInTreeProvider
    from job_sources.provider import SourceProvider

    provider = LegacyInTreeProvider()
    assert isinstance(provider, SourceProvider)


def test_legacy_provider_list_sources_returns_list():
    """list_sources() returns a list (may be empty without DB)."""
    from job_sources.legacy_provider import LegacyInTreeProvider

    provider = LegacyInTreeProvider()
    result = provider.list_sources()
    assert isinstance(result, list)


def test_legacy_provider_make_clients_delegates_to_make_enabled_sources():
    """make_clients() delegates to job_sources.make_enabled_sources."""
    from job_sources.legacy_provider import LegacyInTreeProvider

    provider = LegacyInTreeProvider()
    mock_client = MagicMock()
    mock_client.SOURCE = "arbeitnow"

    with patch(
        "job_sources.legacy_provider.make_enabled_sources_legacy",
        return_value=[mock_client],
    ) as mock_fn:
        clients = provider.make_clients(
            providers_data=_PROVIDERS,
            search=_SEARCH,
        )

    mock_fn.assert_called_once_with(_PROVIDERS, _SEARCH)
    assert len(clients) == 1
    assert clients[0].SOURCE == "arbeitnow"


def test_legacy_provider_make_clients_returns_empty_on_empty_sources():
    """make_clients() returns [] when no sources are enabled."""
    from job_sources.legacy_provider import LegacyInTreeProvider

    provider = LegacyInTreeProvider()

    with patch(
        "job_sources.legacy_provider.make_enabled_sources_legacy",
        return_value=[],
    ):
        clients = provider.make_clients(
            providers_data=_PROVIDERS,
            search=_SEARCH,
        )

    assert clients == []


def test_legacy_provider_scrape_raises_not_implemented():
    """scrape() raises NotImplementedError (scraping stays in ingest.py)."""
    from job_sources.legacy_provider import LegacyInTreeProvider

    provider = LegacyInTreeProvider()
    with pytest.raises(NotImplementedError):
        provider.scrape("https://example.com/job/123")
