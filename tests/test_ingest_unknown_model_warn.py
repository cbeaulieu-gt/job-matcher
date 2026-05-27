"""tests/test_ingest_unknown_model_warn.py — Regression test for PR #338 review.

Verifies that ``ingest.run()`` emits the unknown-model WARN log at most once
per ingest run for each distinct unknown ``model_used`` value, even when
multiple listings return the same unrecognised model SKU.

Without the dedup fix, a 500-listing run with one unknown model would produce
500 identical WARN lines.  The fix tracks seen-unknowns in a function-local set
and suppresses duplicate WARNs.

These are unit-style tests: the DB, LLM, and HTTP layers are all mocked so no
real DB or network connectivity is needed.

Regression for: PR #338 review feedback.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import ingest
from job_sources.base import JobSource


# ---------------------------------------------------------------------------
# Minimal JobSource stub
# ---------------------------------------------------------------------------

class _StubSource(JobSource):
    """Yields a configurable page of listings without any HTTP calls.

    Args:
        listings: The list of listing dicts to yield as a single page.
    """

    SOURCE = "stub"

    def __init__(self, listings: list[dict]) -> None:
        self._listings = listings

    def fetch_page(self, page: int) -> list[dict]:
        """Return listings on page 1, empty list otherwise."""
        return self._listings if page == 1 else []

    def total_pages(self) -> int:
        """Return 1 — a single page is always sufficient for these tests."""
        return 1

    def normalise(self, raw: dict) -> dict:
        """Pass through — fixture data is already normalised."""
        return raw

    @classmethod
    def settings_schema(cls) -> dict:
        """Return a minimal schema dict satisfying the abstract requirement."""
        return {"display_name": "Stub", "fields": []}

    def pages(self):
        """Yield the single fixture page."""
        yield self._listings


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_UNKNOWN_SKU = "newprovider/future-model-x"  # Not in db._PRICING_TABLE

_BASE_LISTING: dict = {
    "source": "stub",
    "source_id": "stub-warn-001",
    "title": "Software Engineer",
    "company": "ACME",
    "location": "Remote",
    "salary_min": None,
    "salary_max": None,
    "salary_is_predicted": 0,
    "contract_type": "permanent",
    "contract_time": "full_time",
    "description": "A test listing.",
    "redirect_url": "https://example.com/stub-warn-001",
    "created_at": "2026-04-01T00:00:00Z",
}


def _make_listing(source_id: str) -> dict:
    """Return a fixture listing with the given source_id.

    Args:
        source_id: Unique ID within the stub source.

    Returns:
        A normalised listing dict.
    """
    listing = dict(_BASE_LISTING)
    listing["source_id"] = source_id
    listing["redirect_url"] = f"https://example.com/{source_id}"
    return listing


def _score_result(model: str = _UNKNOWN_SKU) -> dict:
    """Return a minimal scoring result using the given model string.

    Args:
        model: The ``model_used`` value to embed in the result.

    Returns:
        A score result dict that ingest.run() will accept.
    """
    return {
        "score": 7,
        "matched_skills": ["Python"],
        "missing_skills": [],
        "concerns": [],
        "verdict": "Good.",
        "tokens_input": 100,
        "tokens_output": 50,
        "model_used": model,
    }


def _write_json(path: str, data: dict) -> None:
    """Serialise *data* as JSON to *path*.

    Args:
        path: Absolute path to write.
        data: JSON-serialisable dict.
    """
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def _make_config(tmp_path) -> str:
    """Write a minimal config.json and return its path.

    Args:
        tmp_path: pytest tmp_path fixture value.

    Returns:
        Absolute path to the written file.
    """
    cfg = {
        "search": {
            "country": "us",
            "what": "engineer",
            "results_per_page": 10,
            "max_pages": 1,
        },
        "scoring": {"threshold": 5.0},
    }
    path = str(tmp_path / "config.json")
    _write_json(path, cfg)
    return path


def _make_profile(tmp_path) -> str:
    """Write a minimal profile.json and return its path.

    Args:
        tmp_path: pytest tmp_path fixture value.

    Returns:
        Absolute path to the written file.
    """
    profile = {
        "primary_skills": [],
        "location": {"geocode_fallback": "pass"},
    }
    path = str(tmp_path / "profile.json")
    _write_json(path, profile)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestUnknownModelWarnDedup:
    """run() must emit the unknown-model WARN at most once per model per run."""

    def test_single_unknown_model_emits_exactly_one_warn(
        self, tmp_path, caplog
    ) -> None:
        """Two listings with the same unknown model_used → exactly one WARN.

        Before the fix, each listing that scored with an unknown model
        triggered a separate ``logger.warning()`` call, producing one WARN
        per listing.  After the fix a function-local seen-set ensures only
        the first encounter emits the warning.
        """
        config_path = _make_config(tmp_path)
        profile_path = _make_profile(tmp_path)
        keys_path = str(tmp_path / "keys.json")

        listings = [
            _make_listing("stub-warn-dup-01"),
            _make_listing("stub-warn-dup-02"),
        ]
        source = _StubSource(listings)

        # Both listings score successfully with the same unknown model.
        side_effects = [
            _score_result(_UNKNOWN_SKU),
            _score_result(_UNKNOWN_SKU),
        ]

        with (
            patch("ingest.make_enabled_sources", return_value=[source]),
            patch("ingest.scrape_description", return_value=("Full text.", True)),
            patch(
                "ingest.score_listing_with_fallback",
                side_effect=side_effects,
            ),
            patch("ingest.db.insert_listing"),
            patch("ingest.db.create_ingest_run", return_value=1),
            patch("ingest.db.finish_ingest_run"),
            patch("ingest.db.listing_exists", return_value=False),
            patch("ingest.db.listing_exists_by_url", return_value=False),
            caplog.at_level(logging.WARNING, logger="ingest"),
        ):
            ingest.run(
                config_path=config_path,
                profile_path=profile_path,
                keys_path=keys_path,
            )

        warn_records = [
            r for r in caplog.records
            if r.levelno == logging.WARNING
            and _UNKNOWN_SKU in r.getMessage()
        ]
        assert len(warn_records) == 1, (
            f"Expected exactly 1 WARN for {_UNKNOWN_SKU!r} but got "
            f"{len(warn_records)}.\nRecords: "
            + "\n".join(r.getMessage() for r in warn_records)
        )

    def test_two_distinct_unknown_models_each_emit_one_warn(
        self, tmp_path, caplog
    ) -> None:
        """Each *distinct* unknown model_used must emit exactly one WARN.

        This verifies the dedup is per-model, not a global suppress-all.
        """
        config_path = _make_config(tmp_path)
        profile_path = _make_profile(tmp_path)
        keys_path = str(tmp_path / "keys.json")

        _UNKNOWN_SKU_B = "otherprovider/another-new-model"

        listings = [
            _make_listing("stub-warn-two-01"),
            _make_listing("stub-warn-two-02"),
        ]
        source = _StubSource(listings)

        side_effects = [
            _score_result(_UNKNOWN_SKU),
            _score_result(_UNKNOWN_SKU_B),
        ]

        with (
            patch("ingest.make_enabled_sources", return_value=[source]),
            patch("ingest.scrape_description", return_value=("Full text.", True)),
            patch(
                "ingest.score_listing_with_fallback",
                side_effect=side_effects,
            ),
            patch("ingest.db.insert_listing"),
            patch("ingest.db.create_ingest_run", return_value=1),
            patch("ingest.db.finish_ingest_run"),
            patch("ingest.db.listing_exists", return_value=False),
            patch("ingest.db.listing_exists_by_url", return_value=False),
            caplog.at_level(logging.WARNING, logger="ingest"),
        ):
            ingest.run(
                config_path=config_path,
                profile_path=profile_path,
                keys_path=keys_path,
            )

        warn_a = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and _UNKNOWN_SKU in r.getMessage()
        ]
        warn_b = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and _UNKNOWN_SKU_B in r.getMessage()
        ]
        assert len(warn_a) == 1, (
            f"Expected 1 WARN for {_UNKNOWN_SKU!r}, got {len(warn_a)}"
        )
        assert len(warn_b) == 1, (
            f"Expected 1 WARN for {_UNKNOWN_SKU_B!r}, got {len(warn_b)}"
        )
