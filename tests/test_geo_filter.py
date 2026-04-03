"""
tests/test_geo_filter.py — Unit tests for the geospatial filter in ingest.py.

Tests cover:
- Listing within radius passes
- Listing outside radius is discarded
- Remote / worldwide listing always passes regardless of radius
- Listing with ungeocoded location respects fallback setting (pass / discard)
- Filter is skipped entirely when location_center is absent
- Filter is skipped when location_radius_km is absent
- Center not geocodable → filter skipped (fail-open)
- geo_filter() module-level helper API
- GeoFilter class with in-memory geocache

All tests use the module-level geo_filter() helper (no DB, no network).
GeoFilter integration tests use a temporary SQLite DB.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db
from ingest import geo_filter, GeoFilter, _is_remote_location


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# Miami, FL  (approx lat/lon used as the filter center in most tests)
_MIAMI = (25.7617, -80.1918)

# Fort Lauderdale, FL — ~45 km north of Miami (within 80 km radius)
_FORT_LAUDERDALE = (26.1224, -80.1373)

# Orlando, FL — ~380 km from Miami (outside 80 km radius)
_ORLANDO = (28.5383, -81.3792)

# A profile dict with geospatial filter enabled.
_BASE_PROFILE = {
    "location_center": "Miami, FL",
    "location_radius_km": 80,
    "location_geocode_fallback": "pass",
}


def _listing(location: str = "Fort Lauderdale, FL") -> dict:
    return {"title": "Software Engineer", "location": location}


def _geocache(
    *,
    center: tuple | None = _MIAMI,
    listing_loc: str = "Fort Lauderdale, FL",
    listing_coords: tuple | None = _FORT_LAUDERDALE,
) -> dict:
    """Build a geocache dict suitable for the geo_filter() helper."""
    cache = {}
    if center is not None:
        cache["Miami, FL"] = center
    if listing_coords is not None:
        cache[listing_loc] = listing_coords
    return cache


# ---------------------------------------------------------------------------
# _is_remote_location helper
# ---------------------------------------------------------------------------

def test_is_remote_location_detects_remote():
    assert _is_remote_location("Remote") is True


def test_is_remote_location_detects_worldwide():
    assert _is_remote_location("Worldwide") is True


def test_is_remote_location_case_insensitive():
    assert _is_remote_location("REMOTE - US only") is True
    assert _is_remote_location("worldwide / remote") is True


def test_is_remote_location_normal_city_false():
    assert _is_remote_location("Miami, FL") is False


def test_is_remote_location_empty_string_false():
    assert _is_remote_location("") is False


# ---------------------------------------------------------------------------
# geo_filter() — filter disabled
# ---------------------------------------------------------------------------

def test_geo_filter_disabled_when_no_center():
    """Filter is skipped entirely when location_center is absent."""
    profile = {"location_radius_km": 80}
    listing = _listing("Orlando, FL")
    cache = {"Miami, FL": _MIAMI, "Orlando, FL": _ORLANDO}
    assert geo_filter(listing, profile, cache) is None


def test_geo_filter_disabled_when_no_radius():
    """Filter is skipped entirely when location_radius_km is absent."""
    profile = {"location_center": "Miami, FL"}
    listing = _listing("Orlando, FL")
    cache = {"Miami, FL": _MIAMI, "Orlando, FL": _ORLANDO}
    assert geo_filter(listing, profile, cache) is None


def test_geo_filter_disabled_when_both_absent():
    """Filter is skipped when neither field is present."""
    listing = _listing("Orlando, FL")
    assert geo_filter(listing, {}, {}) is None


# ---------------------------------------------------------------------------
# geo_filter() — remote / worldwide listings
# ---------------------------------------------------------------------------

def test_geo_filter_remote_listing_passes():
    """Listing with 'Remote' location always passes even when outside radius."""
    profile = _BASE_PROFILE
    listing = _listing("Remote")
    cache = _geocache()  # no entry for "Remote" — doesn't matter
    assert geo_filter(listing, profile, cache) is None


def test_geo_filter_worldwide_listing_passes():
    """Listing with 'Worldwide' location always passes."""
    listing = _listing("Worldwide")
    cache = _geocache()
    assert geo_filter(listing, _BASE_PROFILE, cache) is None


def test_geo_filter_remote_substring_passes():
    """'Remote (US)' passes because it contains 'remote'."""
    listing = _listing("Remote (US)")
    cache = _geocache()
    assert geo_filter(listing, _BASE_PROFILE, cache) is None


def test_geo_filter_empty_location_passes():
    """An empty location string is treated the same as remote — passes."""
    listing = _listing("")
    cache = _geocache()
    assert geo_filter(listing, _BASE_PROFILE, cache) is None


# ---------------------------------------------------------------------------
# geo_filter() — within radius
# ---------------------------------------------------------------------------

def test_geo_filter_within_radius_passes():
    """Fort Lauderdale (~45 km from Miami) passes a 80 km radius."""
    listing = _listing("Fort Lauderdale, FL")
    cache = _geocache()
    assert geo_filter(listing, _BASE_PROFILE, cache) is None


def test_geo_filter_exact_center_passes():
    """A listing at the exact center coordinates always passes."""
    listing = _listing("Miami, FL")
    cache = {
        "Miami, FL": _MIAMI,
    }
    assert geo_filter(listing, _BASE_PROFILE, cache) is None


# ---------------------------------------------------------------------------
# geo_filter() — outside radius
# ---------------------------------------------------------------------------

def test_geo_filter_outside_radius_discarded():
    """Orlando (~380 km from Miami) is rejected by an 80 km radius."""
    listing = _listing("Orlando, FL")
    cache = {
        "Miami, FL": _MIAMI,
        "Orlando, FL": _ORLANDO,
    }
    result = geo_filter(listing, _BASE_PROFILE, cache)
    assert result is not None
    assert "geo_filter" in result
    assert "Orlando" in result


def test_geo_filter_rejection_message_contains_distance():
    """Rejection message includes a km distance figure."""
    listing = _listing("Orlando, FL")
    cache = {"Miami, FL": _MIAMI, "Orlando, FL": _ORLANDO}
    result = geo_filter(listing, _BASE_PROFILE, cache)
    assert result is not None
    assert "km" in result


def test_geo_filter_rejection_message_contains_radius():
    """Rejection message includes the configured radius."""
    listing = _listing("Orlando, FL")
    cache = {"Miami, FL": _MIAMI, "Orlando, FL": _ORLANDO}
    result = geo_filter(listing, _BASE_PROFILE, cache)
    assert result is not None
    assert "80" in result


# ---------------------------------------------------------------------------
# geo_filter() — ungeocoded location + fallback
# ---------------------------------------------------------------------------

def test_geo_filter_ungeocoded_fallback_pass():
    """Ungeocoded location passes when fallback='pass' (the default)."""
    profile = {**_BASE_PROFILE, "location_geocode_fallback": "pass"}
    listing = _listing("Unknown Small Town, XY")
    cache = {"Miami, FL": _MIAMI}  # no entry for the listing location
    assert geo_filter(listing, profile, cache) is None


def test_geo_filter_ungeocoded_fallback_discard():
    """Ungeocoded location is rejected when fallback='discard'."""
    profile = {**_BASE_PROFILE, "location_geocode_fallback": "discard"}
    listing = _listing("Unknown Small Town, XY")
    cache = {"Miami, FL": _MIAMI}
    result = geo_filter(listing, profile, cache)
    assert result is not None
    assert "geo_filter" in result
    assert "could not be geocoded" in result


def test_geo_filter_ungeocoded_fallback_defaults_to_pass():
    """When location_geocode_fallback is absent, ungeocoded locations pass."""
    profile = {
        "location_center": "Miami, FL",
        "location_radius_km": 80,
        # no location_geocode_fallback key
    }
    listing = _listing("Unknown Small Town, XY")
    cache = {"Miami, FL": _MIAMI}
    assert geo_filter(listing, profile, cache) is None


def test_geo_filter_center_not_in_geocache_skips_filter():
    """When the center itself is absent from the geocache, the filter is skipped.

    This prevents silently discarding every listing when the center
    location string cannot be geocoded.
    """
    profile = _BASE_PROFILE
    listing = _listing("Orlando, FL")
    cache = {"Orlando, FL": _ORLANDO}  # center missing
    assert geo_filter(listing, profile, cache) is None


# ---------------------------------------------------------------------------
# GeoFilter class — with a real temporary SQLite DB
# ---------------------------------------------------------------------------

def _make_temp_db() -> str:
    """Create a temporary jobs.db for testing and return its path."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db.init_db(db_path=path)
    return path


def _prepopulate_geocache(db_path: str, entries: dict[str, tuple]) -> None:
    """Insert geocache entries directly into the DB for test setup."""
    conn = db.get_connection(db_path)
    try:
        for loc, (lat, lon) in entries.items():
            db.geocache_put(conn, loc, lat, lon)
    finally:
        conn.close()


class TestGeoFilterClass:
    """Integration tests for GeoFilter using an in-process SQLite DB."""

    def test_inactive_when_no_center(self):
        path = _make_temp_db()
        gf = GeoFilter(profile={"location_radius_km": 80}, db_path=path)
        assert gf.is_active is False

    def test_inactive_when_no_radius(self):
        path = _make_temp_db()
        gf = GeoFilter(profile={"location_center": "Miami, FL"}, db_path=path)
        assert gf.is_active is False

    def test_check_returns_none_when_inactive(self):
        path = _make_temp_db()
        gf = GeoFilter(profile={}, db_path=path)
        listing = _listing("Orlando, FL")
        assert gf.check(listing) is None

    def test_remote_listing_passes_when_active(self):
        path = _make_temp_db()
        _prepopulate_geocache(path, {"Miami, FL": _MIAMI})
        gf = GeoFilter(profile=_BASE_PROFILE, db_path=path)
        assert gf.check(_listing("Remote")) is None

    def test_within_radius_from_db_cache(self):
        """Listing within radius passes when coords come from the DB geocache."""
        path = _make_temp_db()
        _prepopulate_geocache(path, {
            "Miami, FL": _MIAMI,
            "Fort Lauderdale, FL": _FORT_LAUDERDALE,
        })
        gf = GeoFilter(profile=_BASE_PROFILE, db_path=path)
        assert gf.check(_listing("Fort Lauderdale, FL")) is None

    def test_outside_radius_from_db_cache(self):
        """Listing outside radius is rejected when coords come from the DB geocache."""
        path = _make_temp_db()
        _prepopulate_geocache(path, {
            "Miami, FL": _MIAMI,
            "Orlando, FL": _ORLANDO,
        })
        gf = GeoFilter(profile=_BASE_PROFILE, db_path=path)
        result = gf.check(_listing("Orlando, FL"))
        assert result is not None
        assert "geo_filter" in result

    def test_geocache_hit_counter(self):
        """DB cache hits are counted in gf.hits."""
        path = _make_temp_db()
        _prepopulate_geocache(path, {
            "Miami, FL": _MIAMI,
            "Fort Lauderdale, FL": _FORT_LAUDERDALE,
        })
        gf = GeoFilter(profile=_BASE_PROFILE, db_path=path)
        # The center "Miami, FL" was resolved during __init__ via DB cache.
        # Now check a listing whose location is also in the DB cache.
        gf.check(_listing("Fort Lauderdale, FL"))
        assert gf.hits >= 1

    def test_ungeocoded_fallback_discard_via_class(self):
        """GeoFilter.check() respects fallback=discard for unresolvable locations."""
        path = _make_temp_db()
        _prepopulate_geocache(path, {"Miami, FL": _MIAMI})
        profile = {**_BASE_PROFILE, "location_geocode_fallback": "discard"}
        gf = GeoFilter(profile=profile, db_path=path)
        result = gf.check(_listing("Nonexistent Place, ZZ"))
        assert result is not None
        assert "could not be geocoded" in result

    def test_ungeocoded_fallback_pass_via_class(self):
        """GeoFilter.check() lets unresolvable locations through when fallback=pass."""
        path = _make_temp_db()
        _prepopulate_geocache(path, {"Miami, FL": _MIAMI})
        profile = {**_BASE_PROFILE, "location_geocode_fallback": "pass"}
        gf = GeoFilter(profile=profile, db_path=path)
        assert gf.check(_listing("Nonexistent Place, ZZ")) is None

    def test_geo_discarded_counter_increments(self):
        """geo_discarded counter increments when a listing is rejected by radius."""
        path = _make_temp_db()
        _prepopulate_geocache(path, {
            "Miami, FL": _MIAMI,
            "Orlando, FL": _ORLANDO,
        })
        gf = GeoFilter(profile=_BASE_PROFILE, db_path=path)
        gf.check(_listing("Orlando, FL"))
        assert gf.geo_discarded == 1

    def test_in_memory_cache_prevents_repeated_db_reads(self):
        """Second check for same location uses in-memory cache, not DB."""
        path = _make_temp_db()
        _prepopulate_geocache(path, {
            "Miami, FL": _MIAMI,
            "Fort Lauderdale, FL": _FORT_LAUDERDALE,
        })
        gf = GeoFilter(profile=_BASE_PROFILE, db_path=path)

        # First check — reads from DB (1 hit for Fort Lauderdale).
        gf.check(_listing("Fort Lauderdale, FL"))
        hits_after_first = gf.hits

        # Second check — reads from in-memory cache, no new DB hit.
        gf.check(_listing("Fort Lauderdale, FL"))
        assert gf.hits == hits_after_first  # no additional DB reads
