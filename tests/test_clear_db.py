"""
tests/test_clear_db.py — Tests for db.get_listing_count(), db.clear_all_listings(),
and the POST /admin/clear-db route.

Each test class uses a fresh NamedTemporaryFile database so tests are fully
isolated.  Flask route tests use a temp DB via monkeypatching app.DB_PATH.
"""

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
import app as app_module
from app import app as flask_app


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------

class TempDB:
    """Context manager: creates a fresh SQLite file, inits schema, removes on exit."""

    def __enter__(self) -> str:
        self._fh = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._fh.close()
        self.path = self._fh.name
        db.init_db(self.path)
        return self.path

    def __exit__(self, *_):
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def _insert(path: str, source_id: str, source: str = "adzuna") -> None:
    """Insert a minimal listing row into *path* for test setup."""
    db.insert_listing(
        {
            "source": source,
            "source_id": source_id,
            "title": "Engineer",
            "company": "Acme",
            "location": "Remote",
            "description": "A job.",
            "redirect_url": f"https://example.com/{source_id}",
            "created_at": "2026-01-01T00:00:00Z",
            "fetched_at": "2026-01-02T00:00:00Z",
            "score": 8.0,
            "matched_skills": ["Python"],
            "missing_skills": [],
            "concerns": [],
            "verdict": "Good.",
            "seen": 1,
        },
        db_path=path,
    )


# ---------------------------------------------------------------------------
# db.get_listing_count
# ---------------------------------------------------------------------------

class TestGetListingCount:
    def test_returns_zero_for_empty_db(self):
        """get_listing_count() returns 0 when the table has no rows."""
        with TempDB() as path:
            assert db.get_listing_count(db_path=path) == 0

    def test_returns_correct_count_after_inserts(self):
        """get_listing_count() reflects the actual number of inserted rows."""
        with TempDB() as path:
            _insert(path, "job-001")
            _insert(path, "job-002")
            _insert(path, "job-003")
            assert db.get_listing_count(db_path=path) == 3

    def test_count_decreases_after_manual_delete(self):
        """get_listing_count() is accurate after rows are removed externally."""
        with TempDB() as path:
            _insert(path, "job-001")
            _insert(path, "job-002")
            conn = db.get_connection(path)
            try:
                conn.execute("DELETE FROM listings WHERE source_id = 'job-001'")
                conn.commit()
            finally:
                conn.close()
            assert db.get_listing_count(db_path=path) == 1


# ---------------------------------------------------------------------------
# db.clear_all_listings
# ---------------------------------------------------------------------------

class TestClearAllListings:
    def test_deletes_all_rows_and_returns_count(self):
        """clear_all_listings() removes every row and returns the deleted count."""
        with TempDB() as path:
            _insert(path, "job-001")
            _insert(path, "job-002")
            conn = db.get_connection(path)
            try:
                deleted = db.clear_all_listings(conn)
            finally:
                conn.close()
            assert deleted == 2
            assert db.get_listing_count(db_path=path) == 0

    def test_returns_zero_on_empty_table(self):
        """clear_all_listings() returns 0 when there are no rows to delete."""
        with TempDB() as path:
            conn = db.get_connection(path)
            try:
                deleted = db.clear_all_listings(conn)
            finally:
                conn.close()
            assert deleted == 0

    def test_schema_intact_after_clear(self):
        """The listings table still exists and accepts new inserts after clearing."""
        with TempDB() as path:
            _insert(path, "job-001")
            conn = db.get_connection(path)
            try:
                db.clear_all_listings(conn)
            finally:
                conn.close()
            # Must be able to insert a new listing without error
            _insert(path, "job-002")
            assert db.get_listing_count(db_path=path) == 1

    def test_geocache_not_affected(self):
        """clear_all_listings() leaves location_geocache rows untouched."""
        with TempDB() as path:
            conn = db.get_connection(path)
            try:
                conn.execute(
                    "INSERT INTO location_geocache (location_text, lat, lon) "
                    "VALUES ('Miami, FL', 25.77, -80.19)"
                )
                conn.commit()
                _insert(path, "job-001")
                db.clear_all_listings(conn)
                rows = conn.execute(
                    "SELECT COUNT(*) FROM location_geocache"
                ).fetchone()
                assert rows[0] == 1
            finally:
                conn.close()

    def test_single_row_returns_count_one(self):
        """clear_all_listings() with exactly one row returns 1."""
        with TempDB() as path:
            _insert(path, "solo-001")
            conn = db.get_connection(path)
            try:
                deleted = db.clear_all_listings(conn)
            finally:
                conn.close()
            assert deleted == 1


# ---------------------------------------------------------------------------
# POST /admin/clear-db route
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db_path(tmp_path, monkeypatch):
    """Point app.DB_PATH at a fresh temp DB and ensure init_db has run."""
    path = str(tmp_path / "test.db")
    db.init_db(path)
    monkeypatch.setattr(app_module, "DB_PATH", path)
    return path


@pytest.fixture()
def client():
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


class TestAdminClearDbRoute:
    def test_rejects_wrong_confirmation(self, client, tmp_db_path):
        """POST /admin/clear-db with wrong phrase returns 400 and leaves DB intact."""
        _insert(tmp_db_path, "job-001")
        resp = client.post(
            "/admin/clear-db",
            data={"confirmation": "delete"},  # wrong case
        )
        assert resp.status_code == 400
        # Row must still be present
        assert db.get_listing_count(db_path=tmp_db_path) == 1

    def test_rejects_empty_confirmation(self, client, tmp_db_path):
        """POST /admin/clear-db with no phrase returns 400."""
        _insert(tmp_db_path, "job-001")
        resp = client.post("/admin/clear-db", data={})
        assert resp.status_code == 400
        assert db.get_listing_count(db_path=tmp_db_path) == 1

    def test_accepts_correct_confirmation_and_deletes(self, client, tmp_db_path):
        """POST /admin/clear-db with 'DELETE' clears all rows and returns 200."""
        _insert(tmp_db_path, "job-001")
        _insert(tmp_db_path, "job-002")
        resp = client.post(
            "/admin/clear-db",
            data={"confirmation": "DELETE"},
        )
        assert resp.status_code == 200
        assert db.get_listing_count(db_path=tmp_db_path) == 0

    def test_success_response_contains_deleted_count(self, client, tmp_db_path):
        """Success response body mentions the number of deleted listings."""
        _insert(tmp_db_path, "job-001")
        _insert(tmp_db_path, "job-002")
        resp = client.post(
            "/admin/clear-db",
            data={"confirmation": "DELETE"},
        )
        body = resp.data.decode()
        assert "2" in body
        assert "deleted" in body.lower()

    def test_empty_db_returns_zero_count(self, client, tmp_db_path):
        """Clearing an already-empty DB returns 200 with a 0-deleted message."""
        resp = client.post(
            "/admin/clear-db",
            data={"confirmation": "DELETE"},
        )
        assert resp.status_code == 200
        body = resp.data.decode()
        assert "0" in body

    def test_error_fragment_contains_message(self, client, tmp_db_path):
        """400 response body contains an explanatory error message."""
        resp = client.post(
            "/admin/clear-db",
            data={"confirmation": "WRONG"},
        )
        body = resp.data.decode()
        assert "did not match" in body.lower() or "confirmation" in body.lower()

    def test_singular_noun_for_one_listing(self, client, tmp_db_path):
        """Success message uses 'listing' (not 'listings') when exactly one row deleted."""
        _insert(tmp_db_path, "job-solo")
        resp = client.post(
            "/admin/clear-db",
            data={"confirmation": "DELETE"},
        )
        body = resp.data.decode()
        # "1 listing deleted" — not "1 listings deleted"
        assert "1 listing deleted" in body

    def test_plural_noun_for_multiple_listings(self, client, tmp_db_path):
        """Success message uses 'listings' when more than one row deleted."""
        _insert(tmp_db_path, "job-001")
        _insert(tmp_db_path, "job-002")
        resp = client.post(
            "/admin/clear-db",
            data={"confirmation": "DELETE"},
        )
        body = resp.data.decode()
        assert "listings deleted" in body


# ---------------------------------------------------------------------------
# GET /settings includes listing_count
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_providers_path(tmp_path, monkeypatch):
    """Isolate providers.json from the real config directory."""
    path = str(tmp_path / "providers.json")
    monkeypatch.setattr(app_module, "_PROVIDERS_PATH", path)
    return path


@pytest.fixture()
def tmp_keys_path(tmp_path, monkeypatch):
    path = str(tmp_path / "keys.json")
    monkeypatch.setattr(app_module, "_KEYS_PATH", path)
    return path


class TestSettingsListingCount:
    def test_settings_page_renders_listing_count(
        self, client, tmp_db_path, tmp_providers_path, tmp_keys_path
    ):
        """GET /settings page renders without error and includes the listing count."""
        _insert(tmp_db_path, "job-001")
        _insert(tmp_db_path, "job-002")
        resp = client.get("/settings")
        assert resp.status_code == 200
        body = resp.data.decode()
        # The count should appear somewhere in the page
        assert "2" in body

    def test_settings_page_shows_zero_count_when_empty(
        self, client, tmp_db_path, tmp_providers_path, tmp_keys_path
    ):
        """GET /settings shows 0 listings when the database is empty."""
        resp = client.get("/settings")
        assert resp.status_code == 200
        body = resp.data.decode()
        # "0 listings" should appear in the danger zone panel
        assert "0" in body
