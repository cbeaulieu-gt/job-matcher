"""Tests for scripts/migrate_providers_json.py.

Covers:
- Basic migration from legacy shape to native shape
- Idempotency: running twice produces the same result
- Backup (.bak) file is written before mutation
- Malformed input (invalid JSON) exits non-zero without corrupting the file
- enabled field preservation across migration
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _run_migrate(path: str) -> int:
    """Run the migration script on the given path and return the exit code."""
    from scripts.migrate_providers_json import migrate

    return migrate(path)


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def _read_json(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_LEGACY_PROVIDERS = {
    "provider_order": ["anthropic"],
    "llm": {
        "anthropic": {
            "api_key": "sk-test",
            "model": "claude-haiku-4-5-20251001",
        }
    },
    "job_sources": {
        "arbeitnow": {"enabled": True},
        "adzuna": {
            "enabled": True,
            "app_id": "abc123",
            "app_key": "def456",
        },
        "jooble": {
            "enabled": False,
            "api_key": "jooble-key",
        },
    },
}

_NATIVE_PROVIDERS = {
    "schema_version": "1.0",
    "provider_order": ["anthropic"],
    "llm": {
        "anthropic": {
            "api_key": "sk-test",
            "model": "claude-haiku-4-5-20251001",
        }
    },
    "plugins": {
        "arbeitnow": {"enabled": True},
        "adzuna": {
            "enabled": True,
            "app_id": "abc123",
            "app_key": "def456",
        },
        "jooble": {
            "enabled": False,
            "api_key": "jooble-key",
        },
    },
}


# ---------------------------------------------------------------------------
# Basic migration
# ---------------------------------------------------------------------------

def test_migrate_converts_job_sources_to_plugins():
    """Legacy job_sources key is renamed to plugins after migration."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_LEGACY_PROVIDERS, fh)
        path = fh.name

    try:
        exit_code = _run_migrate(path)
        result = _read_json(path)
    finally:
        os.unlink(path)
        bak = path + ".bak"
        if os.path.exists(bak):
            os.unlink(bak)

    assert exit_code == 0
    assert "plugins" in result
    assert "job_sources" not in result


def test_migrate_adds_schema_version():
    """Migration adds schema_version=1.0 to the output."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_LEGACY_PROVIDERS, fh)
        path = fh.name

    try:
        _run_migrate(path)
        result = _read_json(path)
    finally:
        os.unlink(path)
        bak = path + ".bak"
        if os.path.exists(bak):
            os.unlink(bak)

    assert result.get("schema_version") == "1.0"


def test_migrate_preserves_plugin_data():
    """All per-plugin entries are preserved correctly after migration."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_LEGACY_PROVIDERS, fh)
        path = fh.name

    try:
        _run_migrate(path)
        result = _read_json(path)
    finally:
        os.unlink(path)
        bak = path + ".bak"
        if os.path.exists(bak):
            os.unlink(bak)

    plugins = result["plugins"]
    assert plugins["adzuna"]["app_id"] == "abc123"
    assert plugins["adzuna"]["app_key"] == "def456"
    assert plugins["arbeitnow"] == {"enabled": True}


def test_migrate_preserves_llm_section():
    """The llm section and provider_order are preserved unchanged."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_LEGACY_PROVIDERS, fh)
        path = fh.name

    try:
        _run_migrate(path)
        result = _read_json(path)
    finally:
        os.unlink(path)
        bak = path + ".bak"
        if os.path.exists(bak):
            os.unlink(bak)

    assert result["llm"] == _LEGACY_PROVIDERS["llm"]
    assert result["provider_order"] == _LEGACY_PROVIDERS["provider_order"]


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------

def test_migrate_is_idempotent():
    """Running migration twice produces the same output as running it once."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_LEGACY_PROVIDERS, fh)
        path = fh.name

    bak = path + ".bak"
    try:
        _run_migrate(path)
        result_first = _read_json(path)
        exit_code = _run_migrate(path)
        result_second = _read_json(path)
    finally:
        os.unlink(path)
        if os.path.exists(bak):
            os.unlink(bak)

    assert exit_code == 0
    assert result_first == result_second


def test_migrate_idempotent_on_already_native():
    """Migration of an already-native file exits 0 without changing it."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_NATIVE_PROVIDERS, fh)
        path = fh.name

    bak = path + ".bak"
    try:
        exit_code = _run_migrate(path)
        result = _read_json(path)
    finally:
        os.unlink(path)
        if os.path.exists(bak):
            os.unlink(bak)

    assert exit_code == 0
    assert result["schema_version"] == "1.0"
    assert "plugins" in result
    assert "job_sources" not in result


# ---------------------------------------------------------------------------
# Backup (.bak) file
# ---------------------------------------------------------------------------

def test_migrate_writes_bak_file():
    """Migration writes a .bak copy of the original file before mutating."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_LEGACY_PROVIDERS, fh)
        path = fh.name

    bak = path + ".bak"
    try:
        _run_migrate(path)
        assert os.path.exists(bak), ".bak file must be created by migration"
        bak_data = _read_json(bak)
        assert bak_data == _LEGACY_PROVIDERS
    finally:
        os.unlink(path)
        if os.path.exists(bak):
            os.unlink(bak)


# ---------------------------------------------------------------------------
# Malformed input
# ---------------------------------------------------------------------------

def test_migrate_returns_nonzero_on_invalid_json():
    """Migration returns a non-zero exit code when input is not valid JSON."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        fh.write("{not valid json")
        path = fh.name

    try:
        exit_code = _run_migrate(path)
    finally:
        os.unlink(path)
        bak = path + ".bak"
        if os.path.exists(bak):
            os.unlink(bak)

    assert exit_code != 0


def test_migrate_does_not_corrupt_on_invalid_json():
    """When input is malformed, the original file is not overwritten."""
    original_content = "{not valid json"
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(original_content)
        path = fh.name

    try:
        _run_migrate(path)
        with open(path, encoding="utf-8") as fh:
            content_after = fh.read()
    finally:
        os.unlink(path)
        bak = path + ".bak"
        if os.path.exists(bak):
            os.unlink(bak)

    assert content_after == original_content


# ---------------------------------------------------------------------------
# enabled preservation
# ---------------------------------------------------------------------------

def test_migrate_preserves_enabled_true():
    """Sources with enabled=True remain enabled after migration."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_LEGACY_PROVIDERS, fh)
        path = fh.name

    bak = path + ".bak"
    try:
        _run_migrate(path)
        result = _read_json(path)
    finally:
        os.unlink(path)
        if os.path.exists(bak):
            os.unlink(bak)

    assert result["plugins"]["arbeitnow"]["enabled"] is True
    assert result["plugins"]["adzuna"]["enabled"] is True


def test_migrate_preserves_enabled_false():
    """Sources with enabled=False remain disabled after migration."""
    with tempfile.NamedTemporaryFile(
        suffix=".json", mode="w", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(_LEGACY_PROVIDERS, fh)
        path = fh.name

    bak = path + ".bak"
    try:
        _run_migrate(path)
        result = _read_json(path)
    finally:
        os.unlink(path)
        if os.path.exists(bak):
            os.unlink(bak)

    assert result["plugins"]["jooble"]["enabled"] is False
