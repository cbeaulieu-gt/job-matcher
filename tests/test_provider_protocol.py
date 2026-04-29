"""Tests for job_sources/provider.py Protocol definitions.

Verifies that the Protocol shapes are correct and that the file contains
no ``job_aggregator`` imports (the CI enforcement rule applied in-test).
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_provider_module_has_no_job_aggregator_import():
    """The provider module must not import job_aggregator at the code level.

    Checks actual import statements by scanning AST-parsed imports, not
    docstrings (which may legitimately mention the name for documentation).
    """
    import ast
    import pathlib
    provider_path = pathlib.Path(__file__).parent.parent / "job_sources" / "provider.py"
    tree = ast.parse(provider_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("job_aggregator"), (
                    f"job_sources/provider.py must not import job_aggregator "
                    f"(found: import {alias.name})"
                )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith("job_aggregator"), (
                f"job_sources/provider.py must not import job_aggregator "
                f"(found: from {module} import ...)"
            )


def test_plugin_field_protocol_has_required_attributes():
    """PluginField Protocol exposes name, label, type, required, help_text, default."""
    from job_sources.provider import PluginField
    from typing import get_protocol_members
    members = get_protocol_members(PluginField)
    for attr in ("name", "label", "type", "required", "help_text", "default"):
        assert attr in members, f"PluginField missing attribute: {attr}"


def test_source_info_protocol_has_required_attributes():
    """SourceInfo Protocol exposes key, label, fields, is_enabled, credentials_required."""
    from job_sources.provider import SourceInfo
    from typing import get_protocol_members
    members = get_protocol_members(SourceInfo)
    for attr in ("key", "label", "fields", "is_enabled", "credentials_required"):
        assert attr in members, f"SourceInfo missing attribute: {attr}"


def test_source_client_protocol_has_source_and_pages():
    """SourceClient Protocol exposes SOURCE attribute and pages() method."""
    from job_sources.provider import SourceClient
    from typing import get_protocol_members
    members = get_protocol_members(SourceClient)
    assert "SOURCE" in members
    assert "pages" in members


def test_source_provider_protocol_has_required_methods():
    """SourceProvider Protocol exposes list_sources, make_clients, scrape."""
    from job_sources.provider import SourceProvider
    from typing import get_protocol_members
    members = get_protocol_members(SourceProvider)
    for method in ("list_sources", "make_clients", "scrape"):
        assert method in members, f"SourceProvider missing method: {method}"
