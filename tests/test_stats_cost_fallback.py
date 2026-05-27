"""tests/test_stats_cost_fallback.py — Regression tests for #306.

Verifies that ``db.get_usage_stats()`` applies the Haiku fallback rates for
unknown ``model_used`` values instead of nulling the entire cost aggregate.

These are integration tests — they require a live PostgreSQL instance whose
name contains "test".  Set ``DATABASE_URL`` before running:

    export DATABASE_URL="postgresql://jobmatcher:<pw>@localhost:5432/jobmatcher_test"
    pytest tests/test_stats_cost_fallback.py

TEST ISOLATION: rows are inserted with the prefix ``"t306-"`` and deleted in
teardown so the suite does not pollute the database.

Regression for: GitHub issue #306
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db

# ---------------------------------------------------------------------------
# Constants mirrored from db.py (read-only — do not import the private names
# directly; compare structurally instead).
# ---------------------------------------------------------------------------

_FALLBACK_IN  = db._FALLBACK_INPUT_COST_PER_MTOK
_FALLBACK_OUT = db._FALLBACK_OUTPUT_COST_PER_MTOK

# A known Anthropic model and its exact pricing from _PRICING_TABLE.
_KNOWN_MODEL  = "anthropic/claude-haiku-4-20250307"
_KNOWN_IN     = 0.80   # USD / MTok  — claude-haiku- prefix entry
_KNOWN_OUT    = 4.00

_UNKNOWN_MODEL = "openai/gpt-4.1"           # Not in _PRICING_TABLE
_PREFIX = "t306-"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_listing(source_id: str, **kwargs) -> dict:
    """Return a minimal listing dict suitable for ``db.insert_listing()``.

    Args:
        source_id: Unique identifier within the ``test`` source.
        **kwargs: Any listing fields to override.

    Returns:
        Dict with all required columns populated.
    """
    base: dict = {
        "source": "test",
        "source_id": source_id,
        "title": "Test Engineer",
        "company": "ACME",
        "location": "Remote",
        "salary_min": None,
        "salary_max": None,
        "salary_is_predicted": 0,
        "contract_type": "permanent",
        "contract_time": "full_time",
        "description": "Test description.",
        "redirect_url": f"https://example.com/{source_id}",
        "created_at": "2026-04-01T00:00:00Z",
        "fetched_at": "2026-04-01T00:00:00Z",
        "score": 7.5,
        "matched_skills": ["Python"],
        "missing_skills": [],
        "concerns": [],
        "verdict": "Good match.",
        "bookmarked": 0,
        "dismissed": 0,
        "seen": 1,
        "applied": 0,
        "job_type": None,
        "model_used": None,
        "posted_at": None,
        "description_source": "full",
        "tokens_input": 1000,
        "tokens_output": 500,
    }
    base.update(kwargs)
    return base


def _cleanup() -> None:
    """Delete all rows with source_id starting with ``_PREFIX``."""
    with db.get_connection() as conn:
        conn.execute(
            "DELETE FROM listings WHERE source_id LIKE %s",
            (_PREFIX + "%",),
        )


# ---------------------------------------------------------------------------
# Pytest guard — skip the whole module if no real DB is available.
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(
    "postgresql://dummy" in os.environ.get("DATABASE_URL", ""),
    reason=(
        "DATABASE_URL is a placeholder — set a real test DB to run these tests"
    ),
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGetUsageStatsFallback:
    """Integration tests for the Haiku fallback logic in get_usage_stats()."""

    def setup_method(self) -> None:
        """Ensure a clean slate before each test."""
        _cleanup()

    def teardown_method(self) -> None:
        """Remove rows inserted by this test."""
        _cleanup()

    # ------------------------------------------------------------------
    # (a) Mixed known + unknown → non-None total; fallback used for
    #     unknown portion.
    # ------------------------------------------------------------------

    def test_mixed_known_and_unknown_total_is_non_none(self) -> None:
        """When some rows have a known model and some have an unknown one, \
estimated_cost_usd must be a float (not None).

        Previously the first unknown model caused a ``break`` that set the
        total to None and discarded all accumulated cost.
        """
        db.insert_listing(_make_listing(
            f"{_PREFIX}known-01",
            model_used=_KNOWN_MODEL,
            tokens_input=1_000_000,
            tokens_output=0,
        ))
        db.insert_listing(_make_listing(
            f"{_PREFIX}unknown-01",
            model_used=_UNKNOWN_MODEL,
            tokens_input=0,
            tokens_output=0,
        ))

        stats = db.get_usage_stats()

        assert stats["estimated_cost_usd"] is not None, (
            "estimated_cost_usd must not be None when unknown model present"
        )

    def test_mixed_known_and_unknown_cost_uses_fallback_for_unknown(
        self,
    ) -> None:
        """Cost for unknown models must use fallback rates, not be excluded.

        Sets up:
          - 1 MTok input for a *known* model  → _KNOWN_IN  USD
          - 1 MTok output for an *unknown* model → _FALLBACK_OUT USD

        Expected total = _KNOWN_IN + _FALLBACK_OUT.
        """
        db.insert_listing(_make_listing(
            f"{_PREFIX}known-02",
            model_used=_KNOWN_MODEL,
            tokens_input=1_000_000,
            tokens_output=0,
        ))
        db.insert_listing(_make_listing(
            f"{_PREFIX}unknown-02",
            model_used=_UNKNOWN_MODEL,
            tokens_input=0,
            tokens_output=1_000_000,
        ))

        stats = db.get_usage_stats()

        expected = _KNOWN_IN + _FALLBACK_OUT
        assert stats["estimated_cost_usd"] == pytest.approx(expected, rel=1e-6), (
            f"Expected {expected} (known_in={_KNOWN_IN} + fallback_out="
            f"{_FALLBACK_OUT}), got {stats['estimated_cost_usd']}"
        )

    def test_mixed_populates_unknown_models_list(self) -> None:
        """Unknown model names must be surfaced in the return dict.

        The template uses this list to annotate the cost figure with a
        tooltip.  The key ``unknown_models`` must be a non-empty list
        containing the unrecognised SKU.
        """
        db.insert_listing(_make_listing(
            f"{_PREFIX}known-03",
            model_used=_KNOWN_MODEL,
            tokens_input=100,
            tokens_output=50,
        ))
        db.insert_listing(_make_listing(
            f"{_PREFIX}unknown-03",
            model_used=_UNKNOWN_MODEL,
            tokens_input=100,
            tokens_output=50,
        ))

        stats = db.get_usage_stats()

        assert "unknown_models" in stats, (
            "get_usage_stats() must return 'unknown_models' key"
        )
        assert _UNKNOWN_MODEL in stats["unknown_models"], (
            f"{_UNKNOWN_MODEL!r} must appear in unknown_models; "
            f"got {stats['unknown_models']!r}"
        )
        assert _KNOWN_MODEL not in stats["unknown_models"], (
            f"Known model {_KNOWN_MODEL!r} must NOT appear in unknown_models"
        )

    # ------------------------------------------------------------------
    # (b) All-unknown → non-None total via fallback only.
    # ------------------------------------------------------------------

    def test_all_unknown_total_is_non_none(self) -> None:
        """When every row has an unknown model, cost must still be a float.

        Uses _FALLBACK_* rates for all rows so the total is deterministic.
        """
        db.insert_listing(_make_listing(
            f"{_PREFIX}unk-only-01",
            model_used=_UNKNOWN_MODEL,
            tokens_input=0,
            tokens_output=0,
        ))

        stats = db.get_usage_stats()

        assert stats["estimated_cost_usd"] is not None, (
            "estimated_cost_usd must be a float (0.0) even when all models "
            "are unknown"
        )

    def test_all_unknown_uses_fallback_rates(self) -> None:
        """All-unknown total must equal tokens * fallback rates.

        1 MTok input + 1 MTok output for an unknown model:
        expected = _FALLBACK_IN + _FALLBACK_OUT.
        """
        db.insert_listing(_make_listing(
            f"{_PREFIX}unk-only-02",
            model_used=_UNKNOWN_MODEL,
            tokens_input=1_000_000,
            tokens_output=1_000_000,
        ))

        stats = db.get_usage_stats()

        expected = _FALLBACK_IN + _FALLBACK_OUT
        assert stats["estimated_cost_usd"] == pytest.approx(expected, rel=1e-6), (
            f"Expected fallback total {expected}, got {stats['estimated_cost_usd']}"
        )

    def test_all_unknown_populates_unknown_models_list(self) -> None:
        """All-unknown scenario still populates unknown_models."""
        db.insert_listing(_make_listing(
            f"{_PREFIX}unk-only-03",
            model_used=_UNKNOWN_MODEL,
            tokens_input=100,
            tokens_output=50,
        ))

        stats = db.get_usage_stats()

        assert "unknown_models" in stats
        assert _UNKNOWN_MODEL in stats["unknown_models"]

    # ------------------------------------------------------------------
    # (c) All-known → exact pricing unchanged.
    # ------------------------------------------------------------------

    def test_all_known_exact_pricing(self) -> None:
        """When all rows have known models, cost is calculated exactly.

        1 MTok input via _KNOWN_MODEL: expected = _KNOWN_IN.
        No fallback should be applied.
        """
        db.insert_listing(_make_listing(
            f"{_PREFIX}known-only-01",
            model_used=_KNOWN_MODEL,
            tokens_input=1_000_000,
            tokens_output=0,
        ))

        stats = db.get_usage_stats()

        assert stats["estimated_cost_usd"] == pytest.approx(_KNOWN_IN, rel=1e-6), (
            f"Expected exact price {_KNOWN_IN}, got {stats['estimated_cost_usd']}"
        )

    def test_all_known_unknown_models_list_is_empty(self) -> None:
        """When all models are known, unknown_models must be an empty list."""
        db.insert_listing(_make_listing(
            f"{_PREFIX}known-only-02",
            model_used=_KNOWN_MODEL,
            tokens_input=100,
            tokens_output=50,
        ))

        stats = db.get_usage_stats()

        assert "unknown_models" in stats
        assert stats["unknown_models"] == [], (
            f"Expected empty unknown_models, got {stats['unknown_models']!r}"
        )

    def test_all_known_total_is_non_none(self) -> None:
        """Sanity: all-known total must be a non-None float (unchanged)."""
        db.insert_listing(_make_listing(
            f"{_PREFIX}known-only-03",
            model_used=_KNOWN_MODEL,
            tokens_input=1_000,
            tokens_output=500,
        ))

        stats = db.get_usage_stats()

        assert stats["estimated_cost_usd"] is not None

    # ------------------------------------------------------------------
    # Per-day bucket — same fallback treatment.
    # ------------------------------------------------------------------

    def test_per_day_unknown_uses_fallback(self) -> None:
        """Per-day cost_usd must use fallback for unknown models, not None."""
        db.insert_listing(_make_listing(
            f"{_PREFIX}day-unk-01",
            model_used=_UNKNOWN_MODEL,
            tokens_input=1_000_000,
            tokens_output=0,
            fetched_at="2026-04-15T00:00:00Z",
        ))

        stats = db.get_usage_stats()

        day_entry = next(
            (d for d in stats["by_date"] if d["date"] == "2026-04-15"),
            None,
        )
        assert day_entry is not None, "Expected a 2026-04-15 entry in by_date"
        assert day_entry["cost_usd"] is not None, (
            "Per-day cost_usd must not be None for unknown model"
        )
        expected = _FALLBACK_IN  # 1 MTok input only
        assert day_entry["cost_usd"] == pytest.approx(expected, rel=1e-6)

    def test_per_day_known_exact(self) -> None:
        """Per-day cost_usd is exact for known models (no regression)."""
        db.insert_listing(_make_listing(
            f"{_PREFIX}day-known-01",
            model_used=_KNOWN_MODEL,
            tokens_input=1_000_000,
            tokens_output=0,
            fetched_at="2026-04-16T00:00:00Z",
        ))

        stats = db.get_usage_stats()

        day_entry = next(
            (d for d in stats["by_date"] if d["date"] == "2026-04-16"),
            None,
        )
        assert day_entry is not None
        assert day_entry["cost_usd"] == pytest.approx(_KNOWN_IN, rel=1e-6)

    # ------------------------------------------------------------------
    # (e) NULL / empty model_used → labelled "(null)" in unknown_models.
    # ------------------------------------------------------------------

    def test_null_model_used_appears_as_null_label(self) -> None:
        """Rows with model_used=None must be labelled '(null)' in unknown_models.

        The DB stores NULL for rows that were never scored with an LLM
        (e.g. score_failed rows).  ``get_usage_stats()`` must surface
        these as the string ``"(null)"`` rather than omitting them or
        raising an error.
        """
        db.insert_listing(_make_listing(
            f"{_PREFIX}null-model-01",
            model_used=None,
            tokens_input=1_000_000,
            tokens_output=0,
        ))

        stats = db.get_usage_stats()

        assert "(null)" in stats["unknown_models"], (
            "model_used=None must appear as '(null)' in unknown_models; "
            f"got {stats['unknown_models']!r}"
        )

    def test_empty_string_model_used_appears_as_null_label(self) -> None:
        """Rows with model_used='' must also be labelled '(null)' in unknown_models.

        An empty string is falsy in Python, so the expression
        ``mrow["model_used"] or "(null)"`` maps both None and '' to the
        same label.  This test asserts that collapsed behaviour explicitly.
        """
        db.insert_listing(_make_listing(
            f"{_PREFIX}empty-model-01",
            model_used="",
            tokens_input=0,
            tokens_output=1_000_000,
        ))

        stats = db.get_usage_stats()

        assert "(null)" in stats["unknown_models"], (
            "model_used='' must appear as '(null)' in unknown_models; "
            f"got {stats['unknown_models']!r}"
        )

    def test_null_and_empty_model_used_collapsed_to_single_entry(self) -> None:
        """None and '' both map to '(null)' — only one entry in unknown_models.

        Because both values are falsy, ``mrow["model_used"] or "(null)"``
        produces the same label for both, and the dedup logic in
        ``get_usage_stats()`` must not produce duplicate entries.
        """
        db.insert_listing(_make_listing(
            f"{_PREFIX}null-model-02",
            model_used=None,
            tokens_input=500_000,
            tokens_output=0,
        ))
        db.insert_listing(_make_listing(
            f"{_PREFIX}empty-model-02",
            model_used="",
            tokens_input=0,
            tokens_output=500_000,
        ))

        stats = db.get_usage_stats()

        null_count = stats["unknown_models"].count("(null)")
        assert null_count == 1, (
            "Expected exactly one '(null)' entry in unknown_models; "
            f"got {null_count} in {stats['unknown_models']!r}"
        )

    def test_null_model_used_total_cost_uses_fallback(self) -> None:
        """Rows with model_used=None must contribute to total cost via fallback.

        1 MTok input with model_used=None must yield _FALLBACK_IN USD,
        proving the fallback path runs rather than being skipped entirely.
        """
        db.insert_listing(_make_listing(
            f"{_PREFIX}null-model-03",
            model_used=None,
            tokens_input=1_000_000,
            tokens_output=0,
        ))

        stats = db.get_usage_stats()

        assert stats["estimated_cost_usd"] is not None, (
            "estimated_cost_usd must not be None when model_used is NULL"
        )
        assert stats["estimated_cost_usd"] == pytest.approx(
            _FALLBACK_IN, rel=1e-6
        ), (
            f"Expected fallback input rate {_FALLBACK_IN}, "
            f"got {stats['estimated_cost_usd']}"
        )
