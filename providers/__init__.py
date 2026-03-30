"""
providers/ — Pluggable LLM provider package for Job Matcher.

Public API
----------
* ``LLMProvider``          — abstract base class; import from here or ``providers.base``
* ``AnthropicProvider``    — Anthropic Claude backend (default)
* ``OpenAIProvider``       — OpenAI Chat Completions backend
* ``GeminiProvider``       — Google Gemini GenerativeAI backend
* ``make_provider()``      — factory that reads ``config`` and returns the right provider
* ``build_provider_chain`` — build an ordered fallback list from a parsed providers.json dict

Usage
-----
    from providers import make_provider, build_provider_chain

    provider = make_provider(config)              # reads scoring.provider from config
    result   = provider.complete(prompt)          # returns scored dict
    cost_usd = tokens / 1e6 * provider.input_cost_per_mtok

    chain = build_provider_chain(keys)            # ordered list from keys.json
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
    "build_provider_chain",
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


# ---------------------------------------------------------------------------
# Provider name → class mapping used by build_provider_chain
# ---------------------------------------------------------------------------

_PROVIDER_CLASS_MAP: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai":    OpenAIProvider,
    "gemini":    GeminiProvider,
}


def build_provider_chain(providers: dict) -> list[LLMProvider]:
    """Return an ordered list of initialised ``LLMProvider`` instances.

    Accepts the ``providers.json``-shaped dict introduced in Issue #147::

        {
            "provider_order": ["anthropic", "gemini", "openai"],
            "llm": {
                "anthropic": {"api_key": "...", "model": "..."},
                ...
            },
            ...
        }

    Ordering rules
    --------------
    1. Start from ``providers["provider_order"]`` (top-level key).
       If the key is absent or the list is empty, use ``_PROVIDER_CLASS_MAP``
       insertion order for all registered providers.
    2. Each entry in ``provider_order`` that is **not** in ``_PROVIDER_CLASS_MAP``
       is skipped with a ``WARNING`` log.
    3. Each entry in ``_PROVIDER_CLASS_MAP`` that is **not** in ``provider_order``
       is appended at the end in registry insertion order.
    4. Duplicate entries in ``provider_order`` are silently deduplicated (second
       occurrence dropped).
    5. Providers whose ``api_key`` is empty are skipped at runtime regardless of
       position.

    Args:
        providers: Parsed ``providers.json`` dict (or equivalent in-memory dict).

    Returns:
        List of ``LLMProvider`` instances in fallback order.  Providers with
        empty ``api_key`` values are silently skipped.  May be empty if all
        configured providers have empty keys.
    """
    import logging as _logging
    _log = _logging.getLogger(__name__)

    llm_section: dict = providers.get("llm") or {}
    raw_order: list = providers.get("provider_order") or []

    # --- Build the effective ordered name list, deduplicating as we go ---
    seen: set[str] = set()
    ordered_names: list[str] = []

    for name in raw_order:
        if name in seen:
            continue  # duplicate — silently drop
        seen.add(name)
        if name not in _PROVIDER_CLASS_MAP:
            _log.warning(
                "build_provider_chain: '%s' is in provider_order but not in the "
                "provider registry — skipping.",
                name,
            )
            continue
        ordered_names.append(name)

    # Append any registry providers not yet in the list (in registry order).
    for name in _PROVIDER_CLASS_MAP:
        if name not in seen:
            ordered_names.append(name)
            seen.add(name)

    # --- Instantiate providers that have a non-empty api_key ---
    chain: list[LLMProvider] = []
    for name in ordered_names:
        cfg = llm_section.get(name)
        if cfg is None:
            # Provider is registered but has no entry in the llm section —
            # warn so operators know why it is absent from the chain.
            _log.warning(
                "build_provider_chain: '%s' is in the provider registry but has no "
                "entry in providers[\"llm\"] — skipping.",
                name,
            )
            continue
        api_key: str = cfg.get("api_key", "") or ""
        if not api_key:
            continue  # empty key → skip regardless of position
        cls = _PROVIDER_CLASS_MAP[name]
        chain.append(cls(api_key=api_key, model=cfg.get("model", "")))

    return chain
