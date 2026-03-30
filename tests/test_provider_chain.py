"""
tests/test_provider_chain.py — Unit tests for build_provider_chain().

Updated to use the providers.json-shaped dict (with top-level ``provider_order``
and ``llm`` keys) introduced in Issue #147.

All provider SDK clients are patched so no real API keys or network access
are needed.  Covers:

  - provider_order determines chain ordering
  - providers with empty api_key silently skipped
  - provider_order absent → registry insertion order used
  - all empty api_keys → empty chain (no ValueError)
  - provider first in order but has empty key → skipped
  - single valid provider → chain length 1
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from providers import build_provider_chain, AnthropicProvider, OpenAIProvider, GeminiProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_providers(
    anthropic_key: str = "test-key-anthropic",
    openai_key: str    = "test-key-openai",
    gemini_key: str    = "test-key-gemini",
    provider_order: list | None = None,
) -> dict:
    """Return a providers.json-shaped dict for testing build_provider_chain()."""
    d: dict = {
        "llm": {
            "anthropic": {"api_key": anthropic_key, "model": "claude-haiku-4-5-20251001"},
            "openai":    {"api_key": openai_key,    "model": "gpt-4o-mini"},
            "gemini":    {"api_key": gemini_key,    "model": "gemini-1.5-flash"},
        },
        "job_sources": {"adzuna": {"app_id": "", "app_key": ""}},
    }
    if provider_order is not None:
        d["provider_order"] = provider_order
    return d


# Patch all three SDK constructors so no real clients are created.
_PATCHES = [
    patch("providers.anthropic_provider.anthropic.Anthropic"),
    patch("providers.openai_provider.openai.OpenAI"),
    patch("providers.gemini_provider.genai.Client"),
]


def _start_patches() -> list:
    return [p.start() for p in _PATCHES]


def _stop_patches(mocks) -> None:
    for p in _PATCHES:
        p.stop()


# ---------------------------------------------------------------------------
# TestBuildProviderChain
# ---------------------------------------------------------------------------

class TestBuildProviderChain(unittest.TestCase):
    """Unit tests for build_provider_chain() using the providers.json API."""

    def setUp(self) -> None:
        self._mocks = _start_patches()

    def tearDown(self) -> None:
        _stop_patches(self._mocks)

    # ------------------------------------------------------------------
    # 1. provider_order determines chain ordering
    # ------------------------------------------------------------------

    def test_provider_order_first_is_first_in_chain(self):
        """Chain starts with the first entry in provider_order."""
        providers = _make_providers(provider_order=["openai", "anthropic", "gemini"])
        chain = build_provider_chain(providers)

        self.assertIsInstance(chain[0], OpenAIProvider,
            "OpenAI should be first when it leads provider_order")
        self.assertEqual(len(chain), 3,
            "All three providers should appear in the chain")

    # ------------------------------------------------------------------
    # 2. Providers with empty api_key are skipped
    # ------------------------------------------------------------------

    def test_empty_key_skipped(self):
        """Providers with an empty api_key are silently omitted from the chain."""
        providers = _make_providers(
            anthropic_key="",
            provider_order=["openai", "anthropic", "gemini"],
        )
        chain = build_provider_chain(providers)

        types = [type(p) for p in chain]
        self.assertNotIn(AnthropicProvider, types,
            "AnthropicProvider should be absent when its api_key is empty")
        self.assertIn(OpenAIProvider, types,
            "OpenAIProvider should be present with a valid key")

    # ------------------------------------------------------------------
    # 3. No provider_order → registry insertion order
    # ------------------------------------------------------------------

    def test_missing_provider_order_falls_back_to_registry_order(self):
        """When provider_order is absent the order follows _PROVIDER_CLASS_MAP insertion order."""
        providers = _make_providers()  # no provider_order key
        chain = build_provider_chain(providers)

        self.assertIsInstance(chain[0], AnthropicProvider,
            "First provider should be 'anthropic' (first in registry) when provider_order absent")
        self.assertIsInstance(chain[1], OpenAIProvider)
        self.assertIsInstance(chain[2], GeminiProvider)

    # ------------------------------------------------------------------
    # 4. All empty keys → empty chain (no exception)
    # ------------------------------------------------------------------

    def test_all_empty_keys_returns_empty_chain(self):
        """When every provider has an empty api_key the chain is empty (no crash)."""
        providers = _make_providers(
            anthropic_key="",
            openai_key="",
            gemini_key="",
            provider_order=["anthropic", "openai", "gemini"],
        )
        chain = build_provider_chain(providers)
        self.assertEqual(chain, [],
            "Empty chain expected when all api_keys are empty")

    # ------------------------------------------------------------------
    # 5. First provider in order has empty key → skipped, next valid one leads
    # ------------------------------------------------------------------

    def test_first_in_order_empty_key_skipped(self):
        """First entry in provider_order is skipped when its api_key is empty."""
        providers = _make_providers(
            anthropic_key="",
            provider_order=["anthropic", "openai", "gemini"],
        )
        chain = build_provider_chain(providers)

        self.assertIsInstance(chain[0], OpenAIProvider,
            "OpenAI (next valid) should lead when first provider's key is empty")
        types = [type(p) for p in chain]
        self.assertNotIn(AnthropicProvider, types,
            "AnthropicProvider must not appear when its api_key is empty")

    # ------------------------------------------------------------------
    # 6. Single provider → chain length 1
    # ------------------------------------------------------------------

    def test_single_provider(self):
        """A providers dict with only one provider with a key produces a chain of length 1."""
        providers = {
            "provider_order": ["gemini"],
            "llm": {
                "gemini": {"api_key": "test-key-123", "model": "gemini-1.5-flash"},
            },
            "job_sources": {"adzuna": {"app_id": "", "app_key": ""}},
        }
        chain = build_provider_chain(providers)

        self.assertEqual(len(chain), 1,
            "Chain should contain exactly one provider")
        self.assertIsInstance(chain[0], GeminiProvider)


if __name__ == "__main__":
    unittest.main()
