"""
tests/test_validate_search_config.py — Unit tests for the search-config
validation layer added in issue #252.

Covered cases
-------------
* _is_search_field_empty: None, empty string, whitespace, zero int/float,
  non-zero numbers, non-empty strings.
* validate_search_config: each Adzuna-required field missing individually,
  empty string value, zero value, all fields present, disabled source is
  not flagged, multiple issues across multiple sources.
* get_required_search_fields: only returns enabled sources with non-empty
  REQUIRED_SEARCH_FIELDS; disabled sources and keyless sources are excluded.
* load_config deep validation: empty string and 0 are now rejected.
* GET /api/ingest/preflight: 200 when config is valid, 422 with structured
  body when fields are missing.
* GET /settings: warning banner present in HTML when issues exist, absent
  when config is complete.

No live database required — DB and credential calls are mocked out.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Iterator
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ingest
from ingest import (
    ValidationIssue,
    _is_search_field_empty,
    validate_search_config,
)
from job_sources import get_required_search_fields
from job_sources.base import JobSource as BaseJobSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _providers_with_adzuna(enabled: bool = True) -> dict:
    """Return a minimal providers_data dict with Adzuna at the given state."""
    return {
        "provider_order": [],
        "llm": {},
        "job_sources": {
            "adzuna": {
                "enabled": enabled,
                "app_id": "test-id",
                "app_key": "test-key",
            }
        },
    }


def _full_search_cfg() -> dict:
    """Return a complete config dict that passes all Adzuna search checks."""
    return {
        "search": {
            "country": "us",
            "what": "software engineer",
            "where": "Miami",
            "results_per_page": 50,
            "max_pages": 5,
        },
        "scoring": {"threshold": 7.0},
    }


# ---------------------------------------------------------------------------
# _is_search_field_empty
# ---------------------------------------------------------------------------

class TestIsSearchFieldEmpty:
    """Unit tests for the internal empty-detection helper."""

    def test_none_is_empty(self):
        assert _is_search_field_empty(None) is True

    def test_empty_string_is_empty(self):
        assert _is_search_field_empty("") is True

    def test_whitespace_string_is_empty(self):
        assert _is_search_field_empty("   ") is True

    def test_zero_int_is_empty(self):
        assert _is_search_field_empty(0) is True

    def test_zero_float_is_empty(self):
        assert _is_search_field_empty(0.0) is True

    def test_nonzero_int_is_not_empty(self):
        assert _is_search_field_empty(1) is False

    def test_nonzero_float_is_not_empty(self):
        assert _is_search_field_empty(0.1) is False

    def test_nonempty_string_is_not_empty(self):
        assert _is_search_field_empty("us") is False

    def test_negative_int_is_not_empty(self):
        """Negative numbers are non-zero and therefore not empty."""
        assert _is_search_field_empty(-1) is False

    def test_whitespace_only_tab_is_empty(self):
        assert _is_search_field_empty("\t") is True


# ---------------------------------------------------------------------------
# validate_search_config — happy path
# ---------------------------------------------------------------------------

class TestValidateSearchConfigHappyPath:
    """validate_search_config returns [] when all fields are present."""

    def test_all_fields_present_no_issues(self):
        config = _full_search_cfg()
        providers = _providers_with_adzuna(enabled=True)
        issues = validate_search_config(config, providers)
        assert issues == []

    def test_disabled_adzuna_not_flagged(self):
        """Disabled sources must never produce validation issues."""
        config = {"search": {}, "scoring": {"threshold": 7.0}}
        providers = _providers_with_adzuna(enabled=False)
        issues = validate_search_config(config, providers)
        assert issues == []

    def test_no_job_sources_section_no_issues(self):
        """providers_data with no job_sources means no enabled sources."""
        config = {"search": {}, "scoring": {"threshold": 7.0}}
        issues = validate_search_config(config, {})
        assert issues == []

    def test_extra_search_fields_ignored(self):
        """Extra keys in config["search"] do not cause issues."""
        config = _full_search_cfg()
        config["search"]["distance"] = 32
        providers = _providers_with_adzuna(enabled=True)
        assert validate_search_config(config, providers) == []


# ---------------------------------------------------------------------------
# validate_search_config — each missing field individually
# ---------------------------------------------------------------------------

class TestValidateSearchConfigMissingFields:
    """Each required field, when absent or empty, produces an issue."""

    @pytest.mark.parametrize("field_name", [
        "country",
        "what",
        "results_per_page",
        "max_pages",
    ])
    def test_missing_field_produces_issue(self, field_name):
        config = _full_search_cfg()
        del config["search"][field_name]
        providers = _providers_with_adzuna(enabled=True)
        issues = validate_search_config(config, providers)
        assert len(issues) == 1
        assert issues[0].source_key == "adzuna"
        assert field_name in issues[0].missing_fields

    @pytest.mark.parametrize("field_name", ["country", "what"])
    def test_empty_string_field_produces_issue(self, field_name):
        config = _full_search_cfg()
        config["search"][field_name] = ""
        providers = _providers_with_adzuna(enabled=True)
        issues = validate_search_config(config, providers)
        assert any(field_name in i.missing_fields for i in issues)

    @pytest.mark.parametrize("field_name", ["results_per_page", "max_pages"])
    def test_zero_numeric_field_produces_issue(self, field_name):
        config = _full_search_cfg()
        config["search"][field_name] = 0
        providers = _providers_with_adzuna(enabled=True)
        issues = validate_search_config(config, providers)
        assert any(field_name in i.missing_fields for i in issues)

    def test_all_fields_missing_single_issue_with_all_fields(self):
        """One issue per source, listing all missing fields together."""
        config = {"search": {}, "scoring": {"threshold": 7.0}}
        providers = _providers_with_adzuna(enabled=True)
        issues = validate_search_config(config, providers)
        assert len(issues) == 1
        assert set(issues[0].missing_fields) >= {
            "country", "what", "results_per_page", "max_pages"
        }

    def test_whitespace_string_treated_as_empty(self):
        config = _full_search_cfg()
        config["search"]["country"] = "   "
        providers = _providers_with_adzuna(enabled=True)
        issues = validate_search_config(config, providers)
        assert any("country" in i.missing_fields for i in issues)

    def test_none_value_treated_as_empty(self):
        config = _full_search_cfg()
        config["search"]["what"] = None
        providers = _providers_with_adzuna(enabled=True)
        issues = validate_search_config(config, providers)
        assert any("what" in i.missing_fields for i in issues)


# ---------------------------------------------------------------------------
# validate_search_config — source-agnostic (custom plugin)
# ---------------------------------------------------------------------------

class _SearchRequiringSource(BaseJobSource):
    """Fake source that requires two custom search fields."""

    SOURCE = "_search_test"
    REQUIRED_SEARCH_FIELDS: tuple[str, ...] = ("alpha", "beta")

    def __init__(self, config=None, credentials=None, **kwargs):
        pass

    def fetch_page(self, page: int) -> list[dict]:
        return []

    def total_pages(self) -> int:
        return 0

    def normalise(self, raw: dict) -> dict:
        return {}

    def pages(self) -> Iterator[list[dict]]:
        return iter([])

    @classmethod
    def settings_schema(cls) -> dict:
        return {
            "display_name": "Search Test",
            "fields": [
                {"name": "api_key", "label": "API Key",
                 "type": "password", "required": True},
            ],
        }


class TestValidateSearchConfigMultipleSources:
    """Validate behaviour with a custom source alongside Adzuna."""

    def test_custom_source_flagged_when_fields_missing(self):
        providers = {
            "job_sources": {
                "_search_test": {"enabled": True, "api_key": "x"},
            }
        }
        config = {"search": {"alpha": "val"}, "scoring": {"threshold": 7.0}}

        fake_registry = {"_search_test": _SearchRequiringSource}
        with patch("job_sources.get_sources", return_value=fake_registry):
            issues = validate_search_config(config, providers)

        assert len(issues) == 1
        assert issues[0].source_key == "_search_test"
        assert "beta" in issues[0].missing_fields
        assert "alpha" not in issues[0].missing_fields

    def test_disabled_custom_source_not_flagged(self):
        providers = {
            "job_sources": {
                "_search_test": {"enabled": False, "api_key": "x"},
            }
        }
        config = {"search": {}, "scoring": {"threshold": 7.0}}
        fake_registry = {"_search_test": _SearchRequiringSource}
        with patch("job_sources.get_sources", return_value=fake_registry):
            issues = validate_search_config(config, providers)
        assert issues == []


# ---------------------------------------------------------------------------
# get_required_search_fields
# ---------------------------------------------------------------------------

class TestGetRequiredSearchFields:
    """Unit tests for the registry helper that powers validate_search_config."""

    def test_adzuna_enabled_returns_its_fields(self):
        providers = _providers_with_adzuna(enabled=True)
        result = get_required_search_fields(providers)
        keys = [r[0] for r in result]
        assert "adzuna" in keys
        adzuna_fields = next(f for k, f in result if k == "adzuna")
        assert "country" in adzuna_fields
        assert "what" in adzuna_fields
        assert "results_per_page" in adzuna_fields
        assert "max_pages" in adzuna_fields

    def test_adzuna_disabled_not_returned(self):
        providers = _providers_with_adzuna(enabled=False)
        result = get_required_search_fields(providers)
        keys = [r[0] for r in result]
        assert "adzuna" not in keys

    def test_keyless_source_not_returned(self):
        """Sources without REQUIRED_SEARCH_FIELDS (e.g. Remotive) are excluded."""
        providers = {
            "job_sources": {
                "remotive": {"enabled": True},
            }
        }
        result = get_required_search_fields(providers)
        keys = [r[0] for r in result]
        assert "remotive" not in keys

    def test_empty_providers_returns_empty_list(self):
        assert get_required_search_fields({}) == []


# ---------------------------------------------------------------------------
# load_config — deep validation (empty string / zero now rejected)
# ---------------------------------------------------------------------------

class TestLoadConfigDeepValidation:
    """load_config() must reject empty-string and zero values for required keys."""

    def _write_config(self, tmp_path, search_overrides: dict) -> str:
        base = {
            "search": {
                "country": "us",
                "what": "software engineer",
                "results_per_page": 50,
                "max_pages": 5,
            },
            "scoring": {"threshold": 7.0},
        }
        base["search"].update(search_overrides)
        p = str(tmp_path / "config.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(base, fh)
        return p

    @pytest.mark.parametrize("field,value", [
        ("country", ""),
        ("what", "   "),
        ("results_per_page", 0),
        ("max_pages", 0),
    ])
    def test_empty_or_zero_value_raises_system_exit(
        self, tmp_path, field, value
    ):
        """Empty strings and zero are now treated as missing by load_config."""
        path = self._write_config(tmp_path, {field: value})
        with pytest.raises(SystemExit) as exc_info:
            ingest.load_config(path)
        assert field in str(exc_info.value)

    def test_valid_config_does_not_raise(self, tmp_path):
        path = self._write_config(tmp_path, {})
        cfg = ingest.load_config(path)
        assert cfg["search"]["country"] == "us"


# ---------------------------------------------------------------------------
# GET /api/ingest/preflight — Flask route
# ---------------------------------------------------------------------------

class TestIngestPreflightRoute:
    """Tests for the /api/ingest/preflight endpoint."""

    @pytest.fixture()
    def client(self):
        import app as app_module
        from app import app as flask_app
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as c:
            yield c, app_module

    def test_preflight_ok_when_no_issues(self, client):
        c, app_module = client
        with patch.object(app_module, "_get_search_validation_issues", return_value=[]):
            resp = c.get("/api/ingest/preflight")
        assert resp.status_code == 200
        body = resp.get_json()
        assert body["ok"] is True

    def test_preflight_422_when_issues_exist(self, client):
        c, app_module = client
        fake_issues = [
            ValidationIssue(
                source_key="adzuna",
                missing_fields=["country", "what"],
            )
        ]
        with patch.object(app_module, "_get_search_validation_issues",
                          return_value=fake_issues):
            resp = c.get("/api/ingest/preflight")
        assert resp.status_code == 422
        body = resp.get_json()
        assert body["ok"] is False
        assert len(body["issues"]) == 1
        assert body["issues"][0]["source"] == "adzuna"
        assert "country" in body["issues"][0]["missing_fields"]
        assert "what" in body["issues"][0]["missing_fields"]

    def test_preflight_multiple_issues(self, client):
        c, app_module = client
        fake_issues = [
            ValidationIssue(source_key="adzuna", missing_fields=["country"]),
            ValidationIssue(source_key="other", missing_fields=["query"]),
        ]
        with patch.object(app_module, "_get_search_validation_issues",
                          return_value=fake_issues):
            resp = c.get("/api/ingest/preflight")
        assert resp.status_code == 422
        body = resp.get_json()
        assert len(body["issues"]) == 2


# ---------------------------------------------------------------------------
# GET /settings — warning banner in HTML
# ---------------------------------------------------------------------------

class TestSettingsSearchWarningBanner:
    """The /settings page shows an amber warning when search issues exist."""

    @pytest.fixture()
    def client(self, tmp_path, monkeypatch):
        import app as app_module
        from app import app as flask_app
        flask_app.config["TESTING"] = True
        # Point providers/config paths at temp files so tests are isolated.
        providers_path = str(tmp_path / "providers.json")
        config_path = str(tmp_path / "config.json")
        with open(providers_path, "w") as fh:
            json.dump({"job_sources": {}}, fh)
        with open(config_path, "w") as fh:
            json.dump({
                "search": {
                    "country": "us",
                    "what": "engineer",
                    "results_per_page": 50,
                    "max_pages": 5,
                },
                "scoring": {"threshold": 7.0},
            }, fh)
        monkeypatch.setattr(app_module, "_PROVIDERS_PATH", providers_path)
        monkeypatch.setattr(app_module, "_CONFIG_PATH", config_path)
        with flask_app.test_client() as c:
            yield c, app_module

    def test_no_banner_when_no_issues(self, client):
        c, app_module = client
        with patch.object(app_module, "_get_search_validation_issues",
                          return_value=[]):
            resp = c.get("/settings")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # The CSS class name appears in the <style> block regardless; check
        # that the actual rendered banner element (identified by its role
        # attribute combined with the class) is not present in the DOM.
        assert '<div class="config-warn-banner"' not in html

    def test_banner_present_when_issues_exist(self, client):
        c, app_module = client
        fake_issues = [
            ValidationIssue(
                source_key="adzuna",
                missing_fields=["country", "what"],
            )
        ]
        with patch.object(app_module, "_get_search_validation_issues",
                          return_value=fake_issues):
            resp = c.get("/settings")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "config-warn-banner" in html
        # Warning names the source and missing fields.
        assert "adzuna" in html.lower()
        assert "country" in html
        assert "what" in html

    def test_tab_badge_present_when_issues_exist(self, client):
        c, app_module = client
        fake_issues = [
            ValidationIssue(source_key="adzuna", missing_fields=["country"])
        ]
        with patch.object(app_module, "_get_search_validation_issues",
                          return_value=fake_issues):
            resp = c.get("/settings")
        html = resp.get_data(as_text=True)
        assert "settings-tab-btn--warn" in html
        assert "tab-warn-badge" in html

    def test_warning_links_to_search_tab(self, client):
        c, app_module = client
        fake_issues = [
            ValidationIssue(source_key="adzuna", missing_fields=["country"])
        ]
        with patch.object(app_module, "_get_search_validation_issues",
                          return_value=fake_issues):
            resp = c.get("/settings")
        html = resp.get_data(as_text=True)
        assert "/settings?tab=search" in html


# ---------------------------------------------------------------------------
# make_enabled_sources — KeyError is now caught
# ---------------------------------------------------------------------------

class TestMakeEnabledSourcesKeyErrorCaught:
    """make_enabled_sources() must catch KeyError during source init."""

    def test_key_error_during_init_logs_warning_and_skips(self, caplog):
        """A source that raises KeyError on init is skipped, not re-raised."""
        import logging
        from job_sources import make_enabled_sources

        class _BadSource(BaseJobSource):
            SOURCE = "_bad_key"
            REQUIRED_SEARCH_FIELDS: tuple[str, ...] = ()

            def __init__(self, config=None, credentials=None, **kwargs):
                raise KeyError("missing_search_key")

            def fetch_page(self, page):
                return []

            def total_pages(self):
                return 0

            def normalise(self, raw):
                return {}

            def pages(self) -> Iterator[list[dict]]:
                return iter([])

            @classmethod
            def settings_schema(cls) -> dict:
                return {"display_name": "Bad", "fields": []}

        providers = {"job_sources": {"_bad_key": {"enabled": True}}}
        config = {"search": {}, "scoring": {"threshold": 7.0}}

        fake_registry = {"_bad_key": _BadSource}
        with patch("job_sources.get_sources", return_value=fake_registry):
            with caplog.at_level(logging.WARNING, logger="ingest.sources"):
                result = make_enabled_sources(providers, config)

        assert result == []
        assert any("_bad_key" in r.message for r in caplog.records)
