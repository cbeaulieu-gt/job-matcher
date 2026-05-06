"""
tests/test_credentials_native_shape.py — TDD tests for in-memory providers.json
shape auto-migration in credentials.load_providers() (Phase B Stream 0, refs #366).

Edge cases covered (plan §3 Stream 0 spec table):

  | Input shape                                          | Test name                            |
  |------------------------------------------------------|--------------------------------------|
  | {"job_sources": {...}} only (legacy)                 | test_legacy_only_migrates_to_native  |
  | {"plugins": {...}} only (native)                     | test_native_only_unchanged           |
  | {"job_sources": {...}, "plugins": {...}} (both keys) | test_both_keys_prefers_plugins_with_warning |
  | {"job_sources": {}, "plugins": {...}} (empty legacy) | test_empty_legacy_dropped_silently   |
  | {"schema_version": "1.0", "job_sources": {...}}      | test_versioned_legacy_migrates       |
  | llm + job_sources fixture                            | test_llm_section_passthrough         |

Cross-reference: scripts/migrate_providers_json.py is the on-disk migrator.
These tests target only the in-memory migration path in load_providers().
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from credentials import load_providers  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(path: Path, data: dict) -> None:
    """Write *data* as JSON to *path*."""
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Edge case 1 — legacy-only input migrates in-memory
# ---------------------------------------------------------------------------

class TestLegacyOnlyMigratesToNative:
    """{"job_sources": {...}} → {"plugins": {...}} in memory; file untouched."""

    def test_legacy_only_migrates_to_native(self, tmp_path):
        """A file containing only job_sources is returned with plugins key, not job_sources."""
        legacy_shape = {
            "provider_order": ["anthropic"],
            "llm": {"anthropic": {"api_key": "sk-ant", "model": "claude-haiku-4-5-20251001"}},
            "job_sources": {
                "adzuna": {"app_id": "my-id", "app_key": "my-key"},
            },
        }
        _write(tmp_path / "providers.json", legacy_shape)

        result = load_providers(providers_path=str(tmp_path / "providers.json"))

        assert "plugins" in result, "in-memory result must have 'plugins' key"
        assert "job_sources" not in result, "in-memory result must NOT have 'job_sources' key"
        assert result["plugins"]["adzuna"]["app_id"] == "my-id"
        assert result["plugins"]["adzuna"]["app_key"] == "my-key"

    def test_legacy_only_does_not_write_to_disk(self, tmp_path):
        """The in-memory migration must NOT write back to providers.json."""
        legacy_shape = {
            "provider_order": [],
            "llm": {"anthropic": {"api_key": "sk-ant", "model": "claude-haiku-4-5-20251001"}},
            "job_sources": {"adzuna": {"app_id": "x", "app_key": "y"}},
        }
        providers_path = tmp_path / "providers.json"
        _write(providers_path, legacy_shape)
        mtime_before = providers_path.stat().st_mtime

        load_providers(providers_path=str(providers_path))

        assert providers_path.stat().st_mtime == mtime_before, (
            "load_providers() must not modify providers.json during in-memory migration"
        )
        # File on disk must still have the legacy shape
        on_disk = json.loads(providers_path.read_text())
        assert "job_sources" in on_disk, "On-disk file must retain legacy shape — no write-back"
        assert "plugins" not in on_disk


# ---------------------------------------------------------------------------
# Edge case 2 — native-only input is passed through unchanged
# ---------------------------------------------------------------------------

class TestNativeOnlyUnchanged:
    """{"plugins": {...}} only → returned as-is; idempotent."""

    def test_native_only_unchanged(self, tmp_path):
        """A file already in native shape is returned exactly as loaded."""
        native_shape = {
            "schema_version": "1.0",
            "provider_order": ["anthropic"],
            "llm": {"anthropic": {"api_key": "sk-ant", "model": "claude-haiku-4-5-20251001"}},
            "plugins": {
                "adzuna": {"app_id": "pid", "app_key": "pkey"},
            },
        }
        _write(tmp_path / "providers.json", native_shape)

        result = load_providers(providers_path=str(tmp_path / "providers.json"))

        assert "plugins" in result
        assert "job_sources" not in result
        assert result["plugins"]["adzuna"]["app_id"] == "pid"
        assert result.get("schema_version") == "1.0"


# ---------------------------------------------------------------------------
# Edge case 3 — both keys present: prefer plugins, log a warning
# ---------------------------------------------------------------------------

class TestBothKeysPreferPluginsWithWarning:
    """{"job_sources": {...}, "plugins": {...}} → prefer plugins; log a warning."""

    def test_both_keys_prefers_plugins(self, tmp_path):
        """When both keys are present, the returned dict uses plugins, not job_sources."""
        both_shape = {
            "provider_order": [],
            "llm": {},
            "job_sources": {
                "adzuna": {"app_id": "legacy-id", "app_key": "legacy-key"},
            },
            "plugins": {
                "adzuna": {"app_id": "native-id", "app_key": "native-key"},
            },
        }
        _write(tmp_path / "providers.json", both_shape)

        result = load_providers(providers_path=str(tmp_path / "providers.json"))

        assert result["plugins"]["adzuna"]["app_id"] == "native-id", (
            "plugins values must win over job_sources when both are present"
        )
        assert "job_sources" not in result

    def test_both_keys_emits_warning(self, tmp_path, caplog):
        """A WARNING is logged when both job_sources and plugins are present."""
        both_shape = {
            "provider_order": [],
            "llm": {},
            "job_sources": {"adzuna": {"app_id": "l-id", "app_key": "l-key"}},
            "plugins":     {"adzuna": {"app_id": "n-id", "app_key": "n-key"}},
        }
        _write(tmp_path / "providers.json", both_shape)

        with caplog.at_level(logging.WARNING, logger="credentials"):
            load_providers(providers_path=str(tmp_path / "providers.json"))

        assert any(
            "job_sources" in record.message and record.levelno >= logging.WARNING
            for record in caplog.records
        ), "A WARNING mentioning 'job_sources' must be logged when both keys are present"


# ---------------------------------------------------------------------------
# Edge case 4 — empty legacy + native: drop job_sources silently
# ---------------------------------------------------------------------------

class TestEmptyLegacyDroppedSilently:
    """{"job_sources": {}, "plugins": {...}} → drop empty job_sources; no warning."""

    def test_empty_legacy_dropped_silently(self, tmp_path, caplog):
        """Empty job_sources alongside plugins is dropped without a warning."""
        empty_legacy_shape = {
            "provider_order": [],
            "llm": {},
            "job_sources": {},   # empty
            "plugins": {"adzuna": {"app_id": "n-id", "app_key": "n-key"}},
        }
        _write(tmp_path / "providers.json", empty_legacy_shape)

        with caplog.at_level(logging.WARNING, logger="credentials"):
            result = load_providers(providers_path=str(tmp_path / "providers.json"))

        assert "plugins" in result
        assert "job_sources" not in result
        assert result["plugins"]["adzuna"]["app_id"] == "n-id"
        # No warning should be emitted for an empty legacy leftover
        warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert not any("job_sources" in m for m in warning_msgs), (
            "No WARNING should be emitted for an empty job_sources leftover"
        )


# ---------------------------------------------------------------------------
# Edge case 5 — schema_version: "1.0" + job_sources (no plugins): force-migrate
# ---------------------------------------------------------------------------

class TestVersionedLegacyMigrates:
    """{"schema_version": "1.0", "job_sources": {...}} → force-migrate; preserve schema_version."""

    def test_versioned_legacy_migrates(self, tmp_path):
        """A file marked schema_version 1.0 but still using job_sources shape is migrated."""
        versioned_legacy = {
            "schema_version": "1.0",
            "provider_order": ["anthropic"],
            "llm": {"anthropic": {"api_key": "sk-ant", "model": "claude-haiku-4-5-20251001"}},
            "job_sources": {
                "adzuna": {"app_id": "v-id", "app_key": "v-key"},
            },
        }
        _write(tmp_path / "providers.json", versioned_legacy)

        result = load_providers(providers_path=str(tmp_path / "providers.json"))

        assert "plugins" in result, (
            "A versioned file with job_sources (no plugins) must still be migrated in-memory"
        )
        assert "job_sources" not in result
        assert result["plugins"]["adzuna"]["app_id"] == "v-id"
        # schema_version must be preserved
        assert result.get("schema_version") == "1.0", (
            "schema_version must be preserved through in-memory migration"
        )


# ---------------------------------------------------------------------------
# Invariant — sibling top-level keys are passed through unchanged
# ---------------------------------------------------------------------------

class TestLlmSectionPassthrough:
    """Migration touches only job_sources ↔ plugins; all other top-level keys pass through."""

    def test_llm_section_passthrough(self, tmp_path):
        """llm, provider_order, and other top-level keys are unchanged after migration."""
        fixture = {
            "provider_order": ["anthropic", "openai"],
            "llm": {
                "anthropic": {"api_key": "sk-ant", "model": "claude-haiku-4-5-20251001"},
                "openai":    {"api_key": "sk-oai", "model": "gpt-4o-mini"},
            },
            "job_sources": {
                "adzuna": {"app_id": "aid", "app_key": "akey"},
            },
        }
        _write(tmp_path / "providers.json", fixture)

        result = load_providers(providers_path=str(tmp_path / "providers.json"))

        # job_sources renamed to plugins
        assert "plugins" in result
        assert result["plugins"]["adzuna"]["app_id"] == "aid"

        # llm section completely preserved
        assert result["llm"]["anthropic"]["api_key"] == "sk-ant"
        assert result["llm"]["anthropic"]["model"] == "claude-haiku-4-5-20251001"
        assert result["llm"]["openai"]["api_key"] == "sk-oai"

        # provider_order preserved
        assert result["provider_order"] == ["anthropic", "openai"]
