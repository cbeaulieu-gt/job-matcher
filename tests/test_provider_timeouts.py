"""
tests/test_provider_timeouts.py — Regression tests for issue #246.

Verify that every LLM SDK client and the Nominatim geolocator are constructed
with explicit HTTP timeouts so they cannot hang indefinitely at the TCP layer.

All external SDK constructors are patched — no network access needed.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # noqa: E402


# ---------------------------------------------------------------------------
# AnthropicProvider — constructor and validate_credentials both pass timeout
# ---------------------------------------------------------------------------

class TestAnthropicTimeout:
    def test_init_passes_timeout_to_sdk(self):
        """AnthropicProvider.__init__ passes timeout=_LLM_TIMEOUT_SECONDS to anthropic.Anthropic."""
        with patch("providers.anthropic_provider.anthropic.Anthropic") as mock_cls:
            mock_cls.return_value = MagicMock()
            from providers.anthropic_provider import AnthropicProvider, _LLM_TIMEOUT_SECONDS
            AnthropicProvider(api_key="k", model="claude-haiku-4-5-20251001")

        assert mock_cls.called
        _, kwargs = mock_cls.call_args
        assert kwargs.get("timeout") is not None
        assert kwargs["timeout"] == _LLM_TIMEOUT_SECONDS

    def test_validate_credentials_passes_timeout_to_sdk(self):
        """AnthropicProvider.validate_credentials passes timeout=_LLM_TIMEOUT_SECONDS to anthropic.Anthropic."""
        with patch("providers.anthropic_provider.anthropic.Anthropic") as mock_cls:
            instance = MagicMock()
            instance.messages.create.return_value = MagicMock()
            mock_cls.return_value = instance
            from providers.anthropic_provider import AnthropicProvider, _LLM_TIMEOUT_SECONDS
            AnthropicProvider.validate_credentials(api_key="k", model="claude-haiku-4-5-20251001")

        assert mock_cls.called
        _, kwargs = mock_cls.call_args
        assert kwargs.get("timeout") is not None
        assert kwargs["timeout"] == _LLM_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# OpenAIProvider — constructor and validate_credentials both pass timeout
# ---------------------------------------------------------------------------

class TestOpenAITimeout:
    def test_init_passes_timeout_to_sdk(self):
        """OpenAIProvider.__init__ passes timeout=_LLM_TIMEOUT_SECONDS to openai.OpenAI."""
        with patch("providers.openai_provider.openai.OpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            from providers.openai_provider import OpenAIProvider, _LLM_TIMEOUT_SECONDS
            OpenAIProvider(api_key="k", model="gpt-4o-mini")

        assert mock_cls.called
        _, kwargs = mock_cls.call_args
        assert kwargs.get("timeout") is not None
        assert kwargs["timeout"] == _LLM_TIMEOUT_SECONDS

    def test_validate_credentials_passes_timeout_to_sdk(self):
        """OpenAIProvider.validate_credentials passes timeout=_LLM_TIMEOUT_SECONDS to openai.OpenAI."""
        with patch("providers.openai_provider.openai.OpenAI") as mock_cls:
            instance = MagicMock()
            instance.chat.completions.create.return_value = MagicMock()
            mock_cls.return_value = instance
            from providers.openai_provider import OpenAIProvider, _LLM_TIMEOUT_SECONDS
            OpenAIProvider.validate_credentials(api_key="k", model="gpt-4o-mini")

        assert mock_cls.called
        _, kwargs = mock_cls.call_args
        assert kwargs.get("timeout") is not None
        assert kwargs["timeout"] == _LLM_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# GeminiProvider — constructor and validate_credentials pass HttpOptions(timeout=ms)
# ---------------------------------------------------------------------------

class TestGeminiTimeout:
    def test_init_passes_http_options_timeout_to_sdk(self):
        """GeminiProvider.__init__ passes HttpOptions(timeout=_LLM_TIMEOUT_MS) to genai.Client."""
        with patch("providers.gemini_provider.genai.Client") as mock_cls:
            mock_cls.return_value = MagicMock()
            from providers.gemini_provider import GeminiProvider, _LLM_TIMEOUT_MS
            GeminiProvider(api_key="k", model="gemini-1.5-flash")

        assert mock_cls.called
        _, kwargs = mock_cls.call_args
        http_options = kwargs.get("http_options")
        assert http_options is not None
        assert http_options.timeout == _LLM_TIMEOUT_MS

    def test_validate_credentials_passes_http_options_timeout_to_sdk(self):
        """GeminiProvider.validate_credentials passes HttpOptions(timeout=_LLM_TIMEOUT_MS) to genai.Client."""
        with patch("providers.gemini_provider.genai.Client") as mock_cls:
            instance = MagicMock()
            instance.models.generate_content.return_value = MagicMock()
            mock_cls.return_value = instance
            from providers.gemini_provider import GeminiProvider, _LLM_TIMEOUT_MS
            GeminiProvider.validate_credentials(api_key="k", model="gemini-1.5-flash")

        assert mock_cls.called
        _, kwargs = mock_cls.call_args
        http_options = kwargs.get("http_options")
        assert http_options is not None
        assert http_options.timeout == _LLM_TIMEOUT_MS

    def test_timeout_constant_is_milliseconds(self):
        """_LLM_TIMEOUT_MS is at least 1000 — confirms it is milliseconds, not seconds."""
        from providers.gemini_provider import _LLM_TIMEOUT_MS
        assert _LLM_TIMEOUT_MS >= 1000, (
            "_LLM_TIMEOUT_MS looks like it was set in seconds — it must be milliseconds"
        )


# ---------------------------------------------------------------------------
# Nominatim in ingest — _geolocator_instance passes timeout=_NOMINATIM_TIMEOUT_SECONDS
# ---------------------------------------------------------------------------

class TestNominatimTimeout:
    def test_geolocator_instance_passes_timeout(self):
        """GeoFilter._geolocator_instance passes timeout=_NOMINATIM_TIMEOUT_SECONDS to Nominatim."""
        with patch("ingest.Nominatim") as mock_nom:
            mock_nom.return_value = MagicMock()
            from ingest import GeoFilter, _NOMINATIM_TIMEOUT_SECONDS
            gf = GeoFilter.__new__(GeoFilter)
            gf._geolocator = None
            gf._geolocator_instance()

        assert mock_nom.called
        _, kwargs = mock_nom.call_args
        assert kwargs.get("timeout") is not None
        assert kwargs["timeout"] == _NOMINATIM_TIMEOUT_SECONDS
