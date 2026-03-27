"""
providers/ — Pluggable LLM provider package for Job Matcher.

Public API
----------
* ``LLMProvider``       — abstract base class; import from here or ``providers.base``
* ``AnthropicProvider`` — Anthropic Claude backend (default)
* ``OpenAIProvider``    — OpenAI Chat Completions backend
* ``GeminiProvider``    — Google Gemini GenerativeAI backend
* ``make_provider()``   — factory that reads ``config`` and returns the right provider

Usage
-----
    from providers import make_provider

    provider = make_provider(config)          # reads scoring.provider from config
    result   = provider.complete(prompt)      # returns scored dict
    cost_usd = tokens / 1e6 * provider.input_cost_per_mtok
"""

from __future__ import annotations

import os

from .base import LLMProvider
from .anthropic_provider import AnthropicProvider
from .openai_provider import OpenAIProvider
from .gemini_provider import GeminiProvider

__all__ = [
    "LLMProvider",
    "AnthropicProvider",
    "OpenAIProvider",
    "GeminiProvider",
    "make_provider",
]


def make_provider(config: dict) -> LLMProvider:
    """Instantiate and return the correct ``LLMProvider`` for *config*.

    Reads ``config["scoring"]["provider"]`` (default: ``"anthropic"``) and
    ``config["scoring"]["model"]``, then resolves the API key from the config
    dict first and the corresponding environment variable second.

    Supported provider names and their key sources:

    +-------------+-----------------------------+----------------------------+
    | provider    | config key                  | env var                    |
    +=============+=============================+============================+
    | anthropic   | ``anthropic_api_key``       | ``ANTHROPIC_API_KEY``      |
    | openai      | ``openai_api_key``          | ``OPENAI_API_KEY``         |
    | gemini      | ``google_api_key``          | ``GOOGLE_API_KEY``         |
    +-------------+-----------------------------+----------------------------+

    Args:
        config: Full config dict as returned by ``ingest.load_config()``.

    Returns:
        An initialised ``LLMProvider`` instance.

    Raises:
        ValueError: If ``provider`` names an unsupported backend.
    """
    scoring = config.get("scoring", {})
    provider_name: str = scoring.get("provider", "anthropic")
    model: str = scoring["model"]

    if provider_name == "anthropic":
        api_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        return AnthropicProvider(api_key=api_key, model=model)

    if provider_name == "openai":
        api_key = config.get("openai_api_key") or os.environ.get("OPENAI_API_KEY", "")
        return OpenAIProvider(api_key=api_key, model=model)

    if provider_name == "gemini":
        api_key = config.get("google_api_key") or os.environ.get("GOOGLE_API_KEY", "")
        return GeminiProvider(api_key=api_key, model=model)

    raise ValueError(
        f"Unknown provider: {provider_name!r}. "
        "Supported values: 'anthropic', 'openai', 'gemini'."
    )
