"""
tests/test_provider_schema_choices.py — Tests for ``choices`` in provider model fields.

Verifies that every LLM provider exposes a ``choices`` list on its ``model``
field so that the settings UI can render a datalist for autocomplete.  Also
checks internal consistency: the ``default`` value must itself be one of the
choices so the pre-populated value is always in the suggestion list.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from providers import AnthropicProvider, OpenAIProvider, GeminiProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model_field(provider_cls) -> dict:
    """Return the 'model' field dict from *provider_cls*.settings_schema()."""
    schema = provider_cls.settings_schema()
    fields_by_name = {f["name"]: f for f in schema["fields"]}
    assert "model" in fields_by_name, (
        f"{provider_cls.__name__}: no 'model' field in settings_schema()"
    )
    return fields_by_name["model"]


# ---------------------------------------------------------------------------
# Parametrised: choices contract applies to every provider
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("provider_cls", [AnthropicProvider, OpenAIProvider, GeminiProvider])
class TestModelFieldChoices:
    """Every provider's model field must expose a non-empty ``choices`` list."""

    def test_choices_key_present(self, provider_cls):
        """'choices' key must exist on the model field."""
        field = _model_field(provider_cls)
        assert "choices" in field, (
            f"{provider_cls.__name__}: 'choices' missing from model field"
        )

    def test_choices_is_non_empty_list(self, provider_cls):
        """'choices' must be a list with at least one entry."""
        field = _model_field(provider_cls)
        assert isinstance(field["choices"], list), (
            f"{provider_cls.__name__}: 'choices' must be a list"
        )
        assert len(field["choices"]) > 0, (
            f"{provider_cls.__name__}: 'choices' must not be empty"
        )

    def test_choices_are_non_empty_strings(self, provider_cls):
        """Every entry in 'choices' must be a non-empty string."""
        field = _model_field(provider_cls)
        for entry in field["choices"]:
            assert isinstance(entry, str) and entry, (
                f"{provider_cls.__name__}: choice {entry!r} must be a non-empty string"
            )

    def test_default_is_in_choices(self, provider_cls):
        """The 'default' value must be one of the 'choices' entries.

        This ensures the pre-populated model ID in the UI is always in the
        datalist suggestion list; a default outside choices would silently
        offer an unlisted value.
        """
        field = _model_field(provider_cls)
        assert "default" in field, (
            f"{provider_cls.__name__}: model field has no 'default'"
        )
        assert field["default"] in field["choices"], (
            f"{provider_cls.__name__}: default {field['default']!r} "
            f"is not in choices {field['choices']!r}"
        )


# ---------------------------------------------------------------------------
# Provider-specific: expected model IDs (subset checks)
# ---------------------------------------------------------------------------


class TestAnthropicChoicesContent:
    """Anthropic choices must include current Claude 4-series models."""

    def test_haiku_in_choices(self):
        """Dated Haiku model must be present."""
        choices = _model_field(AnthropicProvider)["choices"]
        assert "claude-haiku-4-5-20251001" in choices

    def test_sonnet_4_6_in_choices(self):
        """Sonnet 4.6 (newest Sonnet) must be present."""
        choices = _model_field(AnthropicProvider)["choices"]
        assert "claude-sonnet-4-6" in choices

    def test_no_deprecated_claude_3_5_haiku(self):
        """Deprecated claude-3-5-haiku-20241022 must not be present."""
        choices = _model_field(AnthropicProvider)["choices"]
        assert "claude-3-5-haiku-20241022" not in choices

    def test_no_deprecated_claude_3_5_sonnet(self):
        """Deprecated claude-3-5-sonnet-20241022 must not be present."""
        choices = _model_field(AnthropicProvider)["choices"]
        assert "claude-3-5-sonnet-20241022" not in choices


class TestOpenAIChoicesContent:
    """OpenAI choices must include the primary GPT-4o variants."""

    def test_gpt4o_mini_in_choices(self):
        """gpt-4o-mini (default, cheapest) must be present."""
        choices = _model_field(OpenAIProvider)["choices"]
        assert "gpt-4o-mini" in choices

    def test_gpt4o_in_choices(self):
        """gpt-4o must be present."""
        choices = _model_field(OpenAIProvider)["choices"]
        assert "gpt-4o" in choices


class TestGeminiChoicesContent:
    """Gemini choices must include the primary Flash and Pro variants."""

    def test_flash_in_choices(self):
        """gemini-1.5-flash (default) must be present."""
        choices = _model_field(GeminiProvider)["choices"]
        assert "gemini-1.5-flash" in choices

    def test_pro_in_choices(self):
        """gemini-1.5-pro must be present."""
        choices = _model_field(GeminiProvider)["choices"]
        assert "gemini-1.5-pro" in choices
