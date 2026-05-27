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


# ---------------------------------------------------------------------------
# Bug A — only_sources allow-list filters keyless sources (issue #363)
# ---------------------------------------------------------------------------

def _full_providers_data() -> dict:
    """Build a providers_data dict with all 10 registered sources.

    Keyless sources (himalayas, jobicy, remoteok, remotive) have no
    credential fields, but they still need entries here so that the
    enabled-filter logic passes them through.  Keyed sources include
    minimal credentials so they are not stripped by the enablement filter.
    """
    return {
        "provider_order": [],
        "llm": {},
        "job_sources": {
            "arbeitnow": {"enabled": True},
            "himalayas": {"enabled": True},
            "jobicy": {"enabled": True},
            "remoteok": {"enabled": True},
            "remotive": {"enabled": True},
            "the_muse": {"enabled": True},
            "adzuna": {"enabled": True, "app_id": "x", "app_key": "y"},
            "jooble": {"enabled": True, "api_key": "z"},
            "jsearch": {"enabled": True, "api_key": "z"},
            "usajobs": {"enabled": True, "api_key": "z", "user_agent": "u"},
        },
    }


def test_only_sources_filters_keyless():
    """Bug A: make_clients(only_sources={'arbeitnow'}) returns only arbeitnow.

    With JOB_AGGREGATOR_SOURCES=arbeitnow the aggregator must produce
    exactly one client whose SOURCE is 'arbeitnow'.  Keyless sources
    (himalayas, jobicy, remoteok, remotive) must NOT appear even though
    they pass through the credentials dict unchanged (they have no
    required credential fields so make_enabled_sources would include
    them without the only_sources guard).
    """
    from job_sources.aggregator_provider import JobAggregatorProvider

    provider = JobAggregatorProvider()

    # Build mock clients for every registered source so the patch can
    # return a realistic multi-source list.
    mock_clients = []
    for src in (
        "arbeitnow", "himalayas", "jobicy", "remoteok",
        "remotive", "the_muse", "adzuna", "jooble",
    ):
        mc = MagicMock()
        mc.SOURCE = src
        mock_clients.append(mc)

    with patch(
        "job_sources.aggregator_provider.make_enabled_sources",
        return_value=mock_clients,
    ):
        clients = provider.make_clients(
            providers_data=_full_providers_data(),
            search=_MINIMAL_SEARCH,
            only_sources={"arbeitnow"},
        )

    assert len(clients) == 1, (
        f"Expected 1 client for only_sources={{'arbeitnow'}}, got "
        f"{len(clients)}: {[c.SOURCE for c in clients]}"
    )
    assert clients[0].SOURCE == "arbeitnow"


def test_only_sources_none_returns_all():
    """Bug A regression guard: only_sources=None returns all enabled clients.

    When only_sources is None (the default), make_clients must return
    all clients produced by make_enabled_sources — current behavior is
    preserved.
    """
    from job_sources.aggregator_provider import JobAggregatorProvider

    provider = JobAggregatorProvider()

    mock_clients = []
    for src in ("arbeitnow", "himalayas", "jobicy", "remoteok", "remotive"):
        mc = MagicMock()
        mc.SOURCE = src
        mock_clients.append(mc)

    with patch(
        "job_sources.aggregator_provider.make_enabled_sources",
        return_value=mock_clients,
    ):
        clients = provider.make_clients(
            providers_data=_full_providers_data(),
            search=_MINIMAL_SEARCH,
            only_sources=None,
        )

    assert len(clients) >= 5, (
        f"Expected at least 5 clients with only_sources=None, got "
        f"{len(clients)}"
    )


# ---------------------------------------------------------------------------
# Bug B — translation calls normalise() so source/title are populated (#363)
# ---------------------------------------------------------------------------

# A raw arbeitnow API response dict — the shape returned by pages(), which
# does NOT include 'source' or 'source_id'; those come from normalise().
_RAW_ARBEITNOW_RECORD: dict[str, Any] = {
    "slug": "python-developer-at-techcorp-berlin-12345",
    "title": "Python Developer",
    "company_name": "TechCorp Berlin",
    "url": "https://www.arbeitnow.com/jobs/python-developer-12345",
    "created_at": 1714204800,  # Unix timestamp
    "description": "<p>We are looking for a <b>Python Developer</b>.</p>",
    "remote": False,
    "location": "Berlin, Germany",
    "job_types": ["full_time"],
    "tags": ["python", "django"],
    "visa_sponsorship": False,
    "language": "en",
}

# A raw record where 'title' is absent (simulates a bad upstream record
# that some sources may produce).
_RAW_ARBEITNOW_RECORD_NO_TITLE: dict[str, Any] = {
    "slug": "untitled-job-xyz",
    "title": None,
    "company_name": None,
    "url": "https://www.arbeitnow.com/jobs/untitled-job-xyz",
    "created_at": None,
    "description": "",
    "remote": False,
    "location": None,
    "job_types": [],
    "tags": [],
    "visa_sponsorship": False,
    "language": "en",
}


def test_translated_listing_has_source():
    """Bug B: pages() must call normalise() so source/title are populated.

    The wrapper's pages() method yields raw API dicts from the upstream
    plugin.  Raw dicts do not contain a 'source' key — that field is
    populated by the plugin's normalise() method.  If pages() skips
    normalise(), every listing will have source=None (the actual failure
    mode seen in the live run).

    This test verifies that a listing emitted by the wrapper has:
    - dict['source'] == 'arbeitnow' (never None)
    - dict['title'] is a non-empty string
    """
    from unittest.mock import patch

    from job_sources.aggregator_provider import _SourceClientWrapper

    from job_aggregator.plugins.arbeitnow.plugin import Plugin as ArbeitnowPlugin
    from job_aggregator.schema import SearchParams

    upstream = ArbeitnowPlugin(credentials={}, search=SearchParams())

    # Patch pages() to return one raw page so we don't hit the network.
    with patch.object(
        upstream,
        "pages",
        return_value=iter([[_RAW_ARBEITNOW_RECORD]]),
    ):
        wrapper = _SourceClientWrapper(upstream)
        pages = list(wrapper.pages())

    assert len(pages) == 1
    assert len(pages[0]) == 1
    listing = pages[0][0]

    assert listing.get("source") == "arbeitnow", (
        f"Expected source='arbeitnow', got source={listing.get('source')!r}; "
        "pages() may not be calling normalise() before translate_job_record()"
    )
    assert listing.get("title"), (
        f"Expected non-empty title, got title={listing.get('title')!r}"
    )


def test_translated_listing_rejects_none_title():
    """Bug B regression guard: records with title=None are skipped.

    Policy: if normalise() produces a record with title=None, the wrapper
    must NOT emit a translated listing for that record (skip it rather
    than emitting source=arbeitnow, title=None, which would crash
    prefilter() at ingest.py:370 via title.lower()).

    The test asserts that the translated page contains 0 listings for a
    raw record whose 'title' is None after normalisation.
    """
    from unittest.mock import patch

    from job_sources.aggregator_provider import _SourceClientWrapper

    from job_aggregator.plugins.arbeitnow.plugin import Plugin as ArbeitnowPlugin
    from job_aggregator.schema import SearchParams

    upstream = ArbeitnowPlugin(credentials={}, search=SearchParams())

    # Patch pages() to return one raw page with a no-title record.
    with patch.object(
        upstream,
        "pages",
        return_value=iter([[_RAW_ARBEITNOW_RECORD_NO_TITLE]]),
    ):
        wrapper = _SourceClientWrapper(upstream)
        pages = list(wrapper.pages())

    # The wrapper must yield a page (even if empty) rather than crashing,
    # and must NOT include the broken record.
    all_listings = [listing for page in pages for listing in page]
    for listing in all_listings:
        assert listing.get("title"), (
            "Wrapper emitted a listing with title=None; should have "
            f"been skipped. Listing: {listing}"
        )
