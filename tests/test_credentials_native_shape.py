"""tests/test_credentials_native_shape.py — TDD tests for dual-emit in-memory shape.

Tests the Phase B Stream 0 dual-emit behaviour of credentials.load_providers()
(refs #366).  After Stream 0, load_providers() always returns BOTH `job_sources`
(legacy key, for existing readers) AND `plugins` (native key, for Stream 1+
readers), holding identical deep-copied data regardless of the on-disk shape.

Edge cases covered:

  | Input shape                                              | Test name                                  |
  |----------------------------------------------------------|--------------------------------------------|
  | {job_sources: X} only (legacy)                          | test_legacy_only_dual_emits                |
  | {plugins: X} only (native)                              | test_native_only_dual_emits                |
  | {job_sources: A, plugins: B} A != B (both, conflict)   | test_both_keys_sync_to_plugins_with_warning|
  | {job_sources: {}, plugins: X} (empty legacy + native)  | test_empty_legacy_dropped_silently         |
  | {job_sources: X, plugins: {}} (empty native + legacy)  | test_empty_native_dropped_silently         |
  | {schema_version: "1.0", job_sources: X} (versioned)   | test_versioned_legacy_dual_emits           |
  | {llm: ..., job_sources: X} (llm passthrough)           | test_llm_section_passthrough               |
  | legacy input; mutate one key; other unchanged           | test_dual_emit_uses_deep_copies            |
  | legacy input; file not modified on disk                 | test_legacy_only_does_not_write_to_disk    |

Cross-reference: scripts/migrate_providers_json.py is the on-disk migrator.
These tests target only the in-memory dual-emit path in load_providers().
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
    """Write *data* as JSON to *path*.

    Args:
        path: Destination file path.
        data: Dictionary to serialise as JSON.
    """
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Edge case 1 — legacy-only input dual-emits both keys
# ---------------------------------------------------------------------------

class TestLegacyOnlyDualEmits:
    """``{job_sources: X}`` → both ``job_sources`` and ``plugins`` in memory."""

    def test_legacy_only_dual_emits(self, tmp_path: Path) -> None:
        """Legacy-only file produces both job_sources and plugins with identical data."""
        legacy_shape = {
            "provider_order": ["anthropic"],
            "llm": {
                "anthropic": {
                    "api_key": "sk-ant",
                    "model": "claude-haiku-4-5-20251001",
                }
            },
            "job_sources": {
                "adzuna": {"app_id": "my-id", "app_key": "my-key"},
            },
        }
        _write(tmp_path / "providers.json", legacy_shape)

        result = load_providers(providers_path=str(tmp_path / "providers.json"))

        assert "plugins" in result, "in-memory result must have 'plugins' key"
        assert "job_sources" in result, (
            "in-memory result must ALSO have 'job_sources' key (dual-emit)"
        )
        assert result["plugins"]["adzuna"]["app_id"] == "my-id"
        assert result["plugins"]["adzuna"]["app_key"] == "my-key"
        assert result["job_sources"] == result["plugins"], (
            "job_sources and plugins must hold identical data"
        )

    def test_legacy_only_does_not_write_to_disk(self, tmp_path: Path) -> None:
        """The in-memory dual-emit must NOT write back to providers.json."""
        legacy_shape = {
            "provider_order": [],
            "llm": {
                "anthropic": {
                    "api_key": "sk-ant",
                    "model": "claude-haiku-4-5-20251001",
                }
            },
            "job_sources": {"adzuna": {"app_id": "x", "app_key": "y"}},
        }
        providers_path = tmp_path / "providers.json"
        _write(providers_path, legacy_shape)
        mtime_before = providers_path.stat().st_mtime

        load_providers(providers_path=str(providers_path))

        assert providers_path.stat().st_mtime == mtime_before, (
            "load_providers() must not modify providers.json during in-memory "
            "dual-emit"
        )
        # File on disk must still have the legacy shape (no write-back)
        on_disk = json.loads(providers_path.read_text())
        assert "job_sources" in on_disk, (
            "On-disk file must retain legacy shape — no write-back"
        )
        assert "plugins" not in on_disk


# ---------------------------------------------------------------------------
# Edge case 2 — native-only input dual-emits both keys
# ---------------------------------------------------------------------------

class TestNativeOnlyDualEmits:
    """``{plugins: X}`` → both ``plugins`` and ``job_sources`` in memory."""

    def test_native_only_dual_emits(self, tmp_path: Path) -> None:
        """Native-only file produces both plugins and job_sources with identical data."""
        native_shape = {
            "schema_version": "1.0",
            "provider_order": ["anthropic"],
            "llm": {
                "anthropic": {
                    "api_key": "sk-ant",
                    "model": "claude-haiku-4-5-20251001",
                }
            },
            "plugins": {
                "adzuna": {"app_id": "pid", "app_key": "pkey"},
            },
        }
        _write(tmp_path / "providers.json", native_shape)

        result = load_providers(providers_path=str(tmp_path / "providers.json"))

        assert "plugins" in result
        assert "job_sources" in result, (
            "native-only input must also produce job_sources key (dual-emit)"
        )
        assert result["plugins"]["adzuna"]["app_id"] == "pid"
        assert result["job_sources"] == result["plugins"], (
            "job_sources and plugins must hold identical data"
        )
        assert result.get("schema_version") == "1.0", (
            "schema_version sibling key must be preserved"
        )


# ---------------------------------------------------------------------------
# Edge case 3 — both keys present: prefer plugins, sync job_sources to match
# ---------------------------------------------------------------------------

class TestBothKeysSyncToPluginsWithWarning:
    """``{job_sources: A, plugins: B}`` A != B → both keys synced to B; warning."""

    def test_both_keys_sync_to_plugins_with_warning(
        self, tmp_path: Path, caplog
    ) -> None:
        """Both keys present: plugins wins, job_sources is synced to match it."""
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

        with caplog.at_level(logging.WARNING, logger="credentials"):
            result = load_providers(providers_path=str(tmp_path / "providers.json"))

        # Both keys must be present after dual-emit
        assert "plugins" in result
        assert "job_sources" in result

        # plugins value (native) must win
        assert result["plugins"]["adzuna"]["app_id"] == "native-id", (
            "plugins values must win over job_sources when both are non-empty"
        )
        # job_sources must be synced to match plugins
        assert result["job_sources"]["adzuna"]["app_id"] == "native-id", (
            "job_sources must be synced to plugins value after conflict resolution"
        )
        assert result["job_sources"] == result["plugins"]

        # A WARNING must be logged naming 'job_sources'
        assert any(
            "job_sources" in record.message and record.levelno >= logging.WARNING
            for record in caplog.records
        ), "A WARNING mentioning 'job_sources' must be logged when both keys conflict"


# ---------------------------------------------------------------------------
# Edge case 4 — empty legacy + native: drop empty job_sources silently
# ---------------------------------------------------------------------------

class TestEmptyLegacyDroppedSilently:
    """``{job_sources: {}, plugins: X}`` → both keys equal native value; no warning."""

    def test_empty_legacy_dropped_silently(
        self, tmp_path: Path, caplog
    ) -> None:
        """Empty job_sources alongside plugins is absorbed silently into dual-emit."""
        empty_legacy_shape = {
            "provider_order": [],
            "llm": {},
            "job_sources": {},  # empty
            "plugins": {"adzuna": {"app_id": "n-id", "app_key": "n-key"}},
        }
        _write(tmp_path / "providers.json", empty_legacy_shape)

        with caplog.at_level(logging.WARNING, logger="credentials"):
            result = load_providers(providers_path=str(tmp_path / "providers.json"))

        assert "plugins" in result
        assert "job_sources" in result
        assert result["plugins"]["adzuna"]["app_id"] == "n-id"
        assert result["job_sources"] == result["plugins"], (
            "job_sources must be synced to plugins when legacy was empty"
        )
        # No warning should be emitted for an empty legacy leftover
        warning_msgs = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert not any("job_sources" in m for m in warning_msgs), (
            "No WARNING should be emitted for an empty job_sources leftover"
        )


# ---------------------------------------------------------------------------
# Edge case 5 — empty native + legacy: symmetric of edge case 4
# ---------------------------------------------------------------------------

class TestEmptyNativeDroppedSilently:
    """``{plugins: {}, job_sources: X}`` → both keys equal legacy value; no warning."""

    def test_empty_native_dropped_silently(
        self, tmp_path: Path, caplog
    ) -> None:
        """Empty plugins alongside job_sources is absorbed silently into dual-emit."""
        empty_native_shape = {
            "provider_order": [],
            "llm": {},
            "plugins": {},  # empty
            "job_sources": {"adzuna": {"app_id": "l-id", "app_key": "l-key"}},
        }
        _write(tmp_path / "providers.json", empty_native_shape)

        with caplog.at_level(logging.WARNING, logger="credentials"):
            result = load_providers(providers_path=str(tmp_path / "providers.json"))

        assert "plugins" in result
        assert "job_sources" in result
        assert result["job_sources"]["adzuna"]["app_id"] == "l-id"
        assert result["job_sources"] == result["plugins"], (
            "plugins must be synced to job_sources when native was empty"
        )
        # No warning for an empty native leftover
        warning_msgs = [
            r.message for r in caplog.records if r.levelno >= logging.WARNING
        ]
        assert not any("job_sources" in m for m in warning_msgs), (
            "No WARNING should be emitted for an empty plugins leftover"
        )


# ---------------------------------------------------------------------------
# Edge case 6 — schema_version: "1.0" + job_sources only: force dual-emit
# ---------------------------------------------------------------------------

class TestVersionedLegacyDualEmits:
    """``{schema_version: "1.0", job_sources: X}`` → dual-emit; schema_version preserved."""

    def test_versioned_legacy_dual_emits(self, tmp_path: Path) -> None:
        """A versioned file using job_sources shape is dual-emitted; schema_version kept."""
        versioned_legacy = {
            "schema_version": "1.0",
            "provider_order": ["anthropic"],
            "llm": {
                "anthropic": {
                    "api_key": "sk-ant",
                    "model": "claude-haiku-4-5-20251001",
                }
            },
            "job_sources": {
                "adzuna": {"app_id": "v-id", "app_key": "v-key"},
            },
        }
        _write(tmp_path / "providers.json", versioned_legacy)

        result = load_providers(providers_path=str(tmp_path / "providers.json"))

        assert "plugins" in result, (
            "A versioned file with job_sources (no plugins) must be dual-emitted"
        )
        assert "job_sources" in result, (
            "job_sources must remain present in dual-emit output"
        )
        assert result["plugins"]["adzuna"]["app_id"] == "v-id"
        assert result["job_sources"] == result["plugins"]
        assert result.get("schema_version") == "1.0", (
            "schema_version must be preserved through dual-emit"
        )


# ---------------------------------------------------------------------------
# Invariant — sibling top-level keys are passed through unchanged
# ---------------------------------------------------------------------------

class TestLlmSectionPassthrough:
    """Migration touches only job_sources <-> plugins; all other top-level keys pass through."""

    def test_llm_section_passthrough(self, tmp_path: Path) -> None:
        """llm, provider_order, and other top-level keys are unchanged after dual-emit."""
        fixture = {
            "provider_order": ["anthropic", "openai"],
            "llm": {
                "anthropic": {
                    "api_key": "sk-ant",
                    "model": "claude-haiku-4-5-20251001",
                },
                "openai": {
                    "api_key": "sk-oai",
                    "model": "gpt-4o-mini",
                },
            },
            "job_sources": {
                "adzuna": {"app_id": "aid", "app_key": "akey"},
                "jooble": {"api_key": "jk"},
            },
        }
        _write(tmp_path / "providers.json", fixture)

        result = load_providers(providers_path=str(tmp_path / "providers.json"))

        # Both keys present with identical data
        assert "plugins" in result
        assert "job_sources" in result
        assert result["plugins"]["adzuna"]["app_id"] == "aid"
        assert result["job_sources"] == result["plugins"], (
            "job_sources and plugins must hold identical data"
        )

        # llm section completely preserved
        assert result["llm"]["anthropic"]["api_key"] == "sk-ant"
        assert result["llm"]["anthropic"]["model"] == "claude-haiku-4-5-20251001"
        assert result["llm"]["openai"]["api_key"] == "sk-oai"

        # provider_order preserved
        assert result["provider_order"] == ["anthropic", "openai"]


# ---------------------------------------------------------------------------
# Invariant — dual-emit uses deep copies (mutation isolation)
# ---------------------------------------------------------------------------

class TestDualEmitUsesDeepCopies:
    """Mutating one key must not affect the other (deep-copy guarantee)."""

    def test_dual_emit_uses_deep_copies(self, tmp_path: Path) -> None:
        """Mutating result['plugins'] does not corrupt result['job_sources']."""
        legacy_shape = {
            "provider_order": ["anthropic"],
            "llm": {
                "anthropic": {
                    "api_key": "sk-ant",
                    "model": "claude-haiku-4-5-20251001",
                }
            },
            "job_sources": {
                "adzuna": {"app_id": "orig-id", "app_key": "orig-key"},
                "jooble": {"api_key": "jk"},
            },
        }
        _write(tmp_path / "providers.json", legacy_shape)

        result = load_providers(providers_path=str(tmp_path / "providers.json"))

        # Sanity: both keys start equal
        assert result["plugins"] == result["job_sources"]

        # Mutate through the plugins key
        result["plugins"]["adzuna"]["app_id"] = "mutated"
        result["plugins"]["new_source"] = {"api_key": "added"}

        # job_sources must be completely unaffected
        assert result["job_sources"]["adzuna"]["app_id"] == "orig-id", (
            "Mutating result['plugins'] must not affect result['job_sources'] "
            "(deep-copy invariant)"
        )
        assert "new_source" not in result["job_sources"], (
            "Adding a key to result['plugins'] must not appear in result['job_sources']"
        )
