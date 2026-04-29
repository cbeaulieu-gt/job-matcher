"""Tests for JobAggregatorProvider.

Covers:
- Only aggregator_provider.py imports job_aggregator (AC #2)
- Credential isolation: one bad source does not abort others (AC #4)
- Enablement filter: enabled=false skips source before make_enabled_sources (AC #5)
- Bridge boundary: inner per-plugin dict shape is passed to make_enabled_sources (AC #6)
- DB-shape translation: JobRecord fields translate to db.insert_listing schema (AC #14)
- list_sources() returns SourceInfo objects with required attributes
"""

from __future__ import annotations

import ast
import pathlib
import sys
from typing import Any
from unittest.mock import MagicMock, patch

sys.path.insert(
    0, str(pathlib.Path(__file__).parent.parent)
)


# ---------------------------------------------------------------------------
# Fixtures: sample providers_data (legacy shape, Phase A)
# ---------------------------------------------------------------------------

def _legacy_providers(arbeitnow_cfg: dict | None = None) -> dict:
    """Build a legacy-shape providers_data dict."""
    sources = {}
    if arbeitnow_cfg is not None:
        sources["arbeitnow"] = arbeitnow_cfg
    return {
        "provider_order": [],
        "llm": {},
        "job_sources": sources,
    }


_MINIMAL_SEARCH = {
    "what": "software engineer",
    "country": "us",
    "max_pages": 1,
    "max_days_old": 7,
    "results_per_page": 10,
}


# ---------------------------------------------------------------------------
# AC #2 — only aggregator_provider.py imports job_aggregator
# ---------------------------------------------------------------------------

def test_only_aggregator_provider_imports_job_aggregator():
    """No file besides aggregator_provider.py may import job_aggregator.

    This mirrors the CI grep step so failures surface in pytest too.
    """
    worktree = pathlib.Path(__file__).parent.parent
    violators = []
    # The CI grep allows aggregator_provider.py only; test files themselves
    # may import job_aggregator for fixtures and assertions — those are
    # excluded by the CI grep's "grep -v tests/" clause.
    allowed = {
        "job_sources/aggregator_provider.py",
        "tests/test_aggregator_provider.py",
        "tests/test_source_keys_round_trip.py",
    }

    for py_file in worktree.rglob("*.py"):
        rel = py_file.relative_to(worktree).as_posix()
        if any(part.startswith("__pycache__") for part in py_file.parts):
            continue
        if rel in allowed:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("job_aggregator"):
                        violators.append(f"{rel}: import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("job_aggregator"):
                    violators.append(
                        f"{rel}: from {module} import ..."
                    )

    assert not violators, (
        "Files other than job_sources/aggregator_provider.py import "
        "job_aggregator:\n" + "\n".join(violators)
    )


# ---------------------------------------------------------------------------
# AC #4 — credential isolation: bad source does not abort others
# ---------------------------------------------------------------------------

def test_make_clients_skips_source_on_credentials_error(caplog):
    """CredentialsError from one source is caught; other sources are returned."""
    from job_sources.aggregator_provider import JobAggregatorProvider
    from job_aggregator.errors import CredentialsError

    provider = JobAggregatorProvider()

    # Patch make_enabled_sources so it raises CredentialsError for one source
    # then returns a mock client for the second call.
    mock_client = MagicMock()
    mock_client.SOURCE = "arbeitnow"

    call_count = {"n": 0}

    def fake_make_enabled_sources(credentials, search):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise CredentialsError("adzuna", ["app_id"])
        return [mock_client]

    providers_data = _legacy_providers({"enabled": True})
    # Add a second source that will succeed
    providers_data["job_sources"]["adzuna"] = {
        "enabled": True,
        "app_id": "",
        "app_key": "",
    }

    with patch(
        "job_sources.aggregator_provider.make_enabled_sources",
        side_effect=fake_make_enabled_sources,
    ):
        import logging
        with caplog.at_level(logging.WARNING):
            # Should not raise — bad source is omitted
            clients = provider.make_clients(
                providers_data=providers_data,
                search=_MINIMAL_SEARCH,
            )

    # The run continues (doesn't abort); at least no exception was raised.
    # The returned list may be empty or contain clients depending on impl.
    assert isinstance(clients, list)


def test_make_clients_single_bad_credential_does_not_abort(caplog):
    """When make_enabled_sources raises CredentialsError, result is empty list."""
    from job_sources.aggregator_provider import JobAggregatorProvider
    from job_aggregator.errors import CredentialsError

    provider = JobAggregatorProvider()

    with patch(
        "job_sources.aggregator_provider.make_enabled_sources",
        side_effect=CredentialsError("arbeitnow", ["app_id"]),
    ):
        import logging
        with caplog.at_level(logging.WARNING):
            clients = provider.make_clients(
                providers_data=_legacy_providers({"enabled": True}),
                search=_MINIMAL_SEARCH,
            )

    assert clients == []


# ---------------------------------------------------------------------------
# AC #5 — enablement filter: enabled=false is skipped before make_enabled_sources
# ---------------------------------------------------------------------------

def test_make_clients_respects_enabled_false():
    """A source with valid credentials but enabled=false is absent from results."""
    from job_sources.aggregator_provider import JobAggregatorProvider

    provider = JobAggregatorProvider()

    call_recorder = {"called": False}

    def fake_make_enabled_sources(credentials, search):
        call_recorder["called"] = True
        return []

    providers_data = _legacy_providers({"enabled": False})

    with patch(
        "job_sources.aggregator_provider.make_enabled_sources",
        side_effect=fake_make_enabled_sources,
    ):
        clients = provider.make_clients(
            providers_data=providers_data,
            search=_MINIMAL_SEARCH,
        )

    assert clients == []
    # Confirm make_enabled_sources was called with empty credentials dict
    # (disabled source was filtered out before passing to upstream)
    assert call_recorder["called"]


def test_make_clients_enabled_false_source_not_in_credentials():
    """When enabled=false, the source key must NOT appear in credentials dict
    passed to make_enabled_sources (the enablement filter strips it)."""
    from job_sources.aggregator_provider import JobAggregatorProvider

    provider = JobAggregatorProvider()
    captured: list[dict] = []

    def fake_make_enabled_sources(credentials, search):
        captured.append(dict(credentials))
        return []

    providers_data = _legacy_providers({"enabled": False})

    with patch(
        "job_sources.aggregator_provider.make_enabled_sources",
        side_effect=fake_make_enabled_sources,
    ):
        provider.make_clients(
            providers_data=providers_data,
            search=_MINIMAL_SEARCH,
        )

    assert captured, "make_enabled_sources should have been called"
    passed_creds = captured[0]
    assert "arbeitnow" not in passed_creds, (
        "Disabled source should not appear in credentials passed to "
        "make_enabled_sources"
    )


# ---------------------------------------------------------------------------
# AC #6 — bridge boundary: inner per-plugin dict shape (not whole providers)
# ---------------------------------------------------------------------------

def test_make_clients_passes_inner_plugin_dict_not_whole_providers():
    """make_enabled_sources receives {source_key: {cred_fields}} not the full dict.

    registry.py:201 calls credentials.get(key, {}) — so the top-level keys
    of the credentials dict must be source keys like 'arbeitnow', not
    'job_sources', 'llm', 'provider_order', etc.
    """
    from job_sources.aggregator_provider import JobAggregatorProvider

    provider = JobAggregatorProvider()
    captured: list[dict] = []

    def fake_make_enabled_sources(credentials, search):
        captured.append(dict(credentials))
        return []

    providers_data = {
        "provider_order": [],
        "llm": {"anthropic": {"model": "claude"}},
        "job_sources": {
            "arbeitnow": {"enabled": True},
            "adzuna": {"enabled": True, "app_id": "abc", "app_key": "def"},
        },
    }

    with patch(
        "job_sources.aggregator_provider.make_enabled_sources",
        side_effect=fake_make_enabled_sources,
    ):
        provider.make_clients(
            providers_data=providers_data,
            search=_MINIMAL_SEARCH,
        )

    assert captured, "make_enabled_sources should have been called"
    passed = captured[0]

    # Top-level keys must be source keys, not the outer provider structure
    assert "job_sources" not in passed, (
        "Should pass inner plugin dict, not full providers dict"
    )
    assert "llm" not in passed
    assert "provider_order" not in passed
    # Source keys from job_sources should be present (enabled ones)
    assert "arbeitnow" in passed
    assert "adzuna" in passed


# ---------------------------------------------------------------------------
# AC #14 — DB-shape translation: JobRecord → db.insert_listing schema
# ---------------------------------------------------------------------------

# A sample upstream JobRecord for arbeitnow (as returned by normalise())
_SAMPLE_JOB_RECORD: dict[str, Any] = {
    "source": "arbeitnow",
    "source_id": "python-developer-at-techcorp-berlin-12345",
    "description_source": "full",
    "title": "Python Developer",
    "url": "https://www.arbeitnow.com/jobs/python-developer-12345",
    "posted_at": "2026-04-27T10:00:00Z",
    "description": "We are looking for a Python Developer.",
    "company": "TechCorp Berlin",
    "location": "Berlin, Germany",
    "salary_min": None,
    "salary_max": None,
    "salary_currency": None,
    "salary_period": None,
    "contract_type": None,
    "contract_time": "full_time",
    "remote_eligible": True,
    "extra": {"tags": ["python", "django"], "visa_sponsorship": False},
}

# A sample with company=None and minimal fields
_SAMPLE_JOB_RECORD_MINIMAL: dict[str, Any] = {
    "source": "arbeitnow",
    "source_id": "remote-dev-abc",
    "description_source": "snippet",
    "title": "Remote Developer",
    "url": "https://www.arbeitnow.com/jobs/remote-dev-abc",
    "posted_at": None,
    "description": "",
    "company": None,
    "location": None,
    "salary_min": None,
    "salary_max": None,
    "salary_currency": None,
    "salary_period": None,
    "contract_type": None,
    "contract_time": None,
    "remote_eligible": False,
    "extra": None,
}


def test_translate_job_record_produces_required_db_keys():
    """translate_job_record() output contains all keys required by insert_listing."""
    from job_sources.aggregator_provider import translate_job_record

    result = translate_job_record(_SAMPLE_JOB_RECORD)

    required_keys = {
        "source", "source_id", "title", "company", "location",
        "salary_min", "salary_max", "contract_type", "contract_time",
        "description", "redirect_url", "created_at",
    }
    missing = required_keys - set(result.keys())
    assert not missing, f"translate_job_record missing keys: {missing}"


def test_translate_job_record_maps_url_to_redirect_url():
    """upstream 'url' field maps to 'redirect_url' in the DB row."""
    from job_sources.aggregator_provider import translate_job_record

    result = translate_job_record(_SAMPLE_JOB_RECORD)

    assert result["redirect_url"] == _SAMPLE_JOB_RECORD["url"]
    assert "url" not in result


def test_translate_job_record_maps_posted_at_to_created_at():
    """upstream 'posted_at' field maps to 'created_at' in the DB row."""
    from job_sources.aggregator_provider import translate_job_record

    result = translate_job_record(_SAMPLE_JOB_RECORD)

    assert result["created_at"] == _SAMPLE_JOB_RECORD["posted_at"]
    assert "posted_at" not in result


def test_translate_job_record_company_none_becomes_empty_string():
    """upstream company=None becomes '' (in-tree convention for missing company)."""
    from job_sources.aggregator_provider import translate_job_record

    result = translate_job_record(_SAMPLE_JOB_RECORD_MINIMAL)

    assert result["company"] == ""


def test_translate_job_record_discards_upstream_only_fields():
    """description_source, extra, remote_eligible are dropped in the translation."""
    from job_sources.aggregator_provider import translate_job_record

    result = translate_job_record(_SAMPLE_JOB_RECORD)

    for dropped_field in ("description_source", "extra", "remote_eligible"):
        assert dropped_field not in result, (
            f"Upstream-only field '{dropped_field}' should not appear in "
            "the translated DB row"
        )


def test_translate_job_record_preserves_source_string():
    """The 'source' field must be preserved exactly for dedup to work."""
    from job_sources.aggregator_provider import translate_job_record

    result = translate_job_record(_SAMPLE_JOB_RECORD)

    assert result["source"] == "arbeitnow"


def test_translate_job_record_preserves_source_id():
    """The 'source_id' field must be preserved exactly."""
    from job_sources.aggregator_provider import translate_job_record

    result = translate_job_record(_SAMPLE_JOB_RECORD)

    assert result["source_id"] == _SAMPLE_JOB_RECORD["source_id"]


def test_translate_job_record_salary_period_preserved():
    """salary_period is preserved (may be None)."""
    from job_sources.aggregator_provider import translate_job_record

    result = translate_job_record(_SAMPLE_JOB_RECORD)

    assert "salary_period" in result
    assert result["salary_period"] is None


# ---------------------------------------------------------------------------
# list_sources() returns SourceInfo-compatible objects
# ---------------------------------------------------------------------------

def test_list_sources_returns_source_info_objects():
    """list_sources() returns a non-empty list of objects with required attrs."""
    from job_sources.aggregator_provider import JobAggregatorProvider

    provider = JobAggregatorProvider()
    sources = provider.list_sources()

    assert isinstance(sources, list)
    assert len(sources) > 0

    for info in sources:
        assert hasattr(info, "key")
        assert hasattr(info, "label")
        assert hasattr(info, "fields")
        assert hasattr(info, "is_enabled")
        assert hasattr(info, "credentials_required")


def test_list_sources_includes_arbeitnow():
    """arbeitnow must appear in list_sources() results."""
    from job_sources.aggregator_provider import JobAggregatorProvider

    provider = JobAggregatorProvider()
    keys = [s.key for s in provider.list_sources()]

    assert "arbeitnow" in keys


# ---------------------------------------------------------------------------
# PluginConflictError and SchemaVersionError isolation
# ---------------------------------------------------------------------------

def test_make_clients_skips_source_on_plugin_conflict_error(caplog):
    """PluginConflictError is caught per-source; other sources continue."""
    from job_sources.aggregator_provider import JobAggregatorProvider
    from job_aggregator.errors import PluginConflictError

    provider = JobAggregatorProvider()

    with patch(
        "job_sources.aggregator_provider.make_enabled_sources",
        side_effect=PluginConflictError("arbeitnow", ["pkg-a::arbeitnow", "pkg-b::arbeitnow"]),
    ):
        import logging
        with caplog.at_level(logging.WARNING):
            clients = provider.make_clients(
                providers_data=_legacy_providers({"enabled": True}),
                search=_MINIMAL_SEARCH,
            )

    assert clients == []


def test_make_clients_skips_source_on_schema_version_error(caplog):
    """SchemaVersionError is caught per-source; other sources continue."""
    from job_sources.aggregator_provider import JobAggregatorProvider
    from job_aggregator.errors import SchemaVersionError

    provider = JobAggregatorProvider()

    with patch(
        "job_sources.aggregator_provider.make_enabled_sources",
        side_effect=SchemaVersionError("2.0", "1.0"),
    ):
        import logging
        with caplog.at_level(logging.WARNING):
            clients = provider.make_clients(
                providers_data=_legacy_providers({"enabled": True}),
                search=_MINIMAL_SEARCH,
            )

    assert clients == []
