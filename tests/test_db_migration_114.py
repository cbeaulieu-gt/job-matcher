"""Tests for the #114 migration: reclassify JSearch snippet listings as 'full'.

Uses the project-standard scoped DELETE convention — each test inserts rows
with ``source_id`` values prefixed by ``test_114_`` and the autouse fixture
removes exactly those rows before and after every test.  No other data in
the ``listings`` table is touched.
"""

import pytest

import db

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Prefix used for all source_id values in this test module.
#: The fixture below deletes only rows whose source_id starts with this value,
#: matching the convention used in test_db.py, test_clear_db.py, etc.
_TEST_PREFIX = "test_114_"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_listings():
    """Delete test-prefixed rows before and after each test for isolation.

    Calls ``db.init_db()`` first so the schema exists regardless of whether
    any other test file has already run.  ``init_db()`` is idempotent, so
    calling it on a pre-existing table is safe.

    Only rows whose ``source_id`` begins with ``_TEST_PREFIX`` are removed,
    leaving all other data in the ``listings`` table untouched.
    """
    db.init_db()

    def _purge() -> None:
        with db.get_connection() as conn:
            conn.execute(
                "DELETE FROM listings WHERE source_id LIKE %s",
                (_TEST_PREFIX + "%",),
            )

    _purge()
    yield
    _purge()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_listing(
    source: str,
    source_id: str,
    description: str,
    description_source: str,
) -> None:
    """Insert a minimal listing row via db.insert_listing() for testing.

    Args:
        source: Job source name (e.g. ``"jsearch"``).
        source_id: Unique source identifier for this listing.
        description: Full job description text.
        description_source: Either ``"snippet"`` or ``"full"``.
    """
    db.insert_listing({
        "source": source,
        "source_id": source_id,
        "title": "Test Job",
        "company": "Test Co",
        "location": "NYC",
        "salary_min": None,
        "salary_max": None,
        "salary_is_predicted": None,
        "contract_type": None,
        "contract_time": None,
        "description": description,
        "redirect_url": "https://example.com/job/1",
        "created_at": "2026-01-01T00:00:00Z",
        "fetched_at": "2026-01-02T00:00:00Z",
        "score": 5.0,
        "matched_skills": [],
        "missing_skills": [],
        "concerns": [],
        "verdict": "Test",
        "bookmarked": 0,
        "dismissed": 0,
        "seen": 1,
        "applied": 0,
        "job_type": None,
        "model_used": None,
        "posted_at": None,
        "description_source": description_source,
    })


def _get_description_source(source: str, source_id: str) -> str | None:
    """Read description_source for a specific listing.

    Args:
        source: Job source name used when the listing was inserted.
        source_id: Unique source identifier for the listing.

    Returns:
        The ``description_source`` string, or ``None`` if no row found.
    """
    with db.get_connection() as conn:
        cur = conn.execute(
            "SELECT description_source FROM listings"
            " WHERE source=%s AND source_id=%s",
            (source, source_id),
        )
        row = cur.fetchone()
        return row["description_source"] if row else None


def _run_migration() -> int:
    """Run only the JSearch reclassification migration SQL.

    Returns:
        Number of rows updated.
    """
    with db.get_connection() as conn:
        cur = conn.execute(
            """UPDATE listings
               SET description_source = 'full'
               WHERE source = 'jsearch'
                 AND LENGTH(description) >= 100
                 AND description_source = 'snippet'"""
        )
        return cur.rowcount


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestJSearchMigration:
    """Verify the #114 migration reclassifies JSearch snippets correctly."""

    def test_reclassifies_jsearch_with_long_description(self):
        """Long JSearch snippets (>=100 chars) are reclassified as 'full'."""
        _insert_listing("jsearch", "test_114_m1", "A" * 150, "snippet")
        count = _run_migration()
        assert count == 1
        assert _get_description_source("jsearch", "test_114_m1") == "full"

    def test_does_not_reclassify_jsearch_with_short_description(self):
        """Short JSearch snippets (<100 chars) are left as 'snippet'."""
        _insert_listing("jsearch", "test_114_m2", "Short", "snippet")
        count = _run_migration()
        assert count == 0
        assert _get_description_source("jsearch", "test_114_m2") == "snippet"

    def test_does_not_reclassify_other_sources(self):
        """Non-JSearch sources are never reclassified, regardless of length."""
        _insert_listing("jooble", "test_114_m3", "A" * 200, "snippet")
        count = _run_migration()
        assert count == 0
        assert _get_description_source("jooble", "test_114_m3") == "snippet"

    def test_does_not_reclassify_already_full(self):
        """Listings already marked 'full' are not touched by the migration."""
        _insert_listing("jsearch", "test_114_m4", "A" * 150, "full")
        count = _run_migration()
        assert count == 0
        assert _get_description_source("jsearch", "test_114_m4") == "full"
