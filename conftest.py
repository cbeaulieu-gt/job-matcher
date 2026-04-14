"""
conftest.py — project-level pytest configuration.

Patches db.init_db() and db.get_listing_count() before any test module imports
app.py so that settings and other Flask-route tests can run without a live
PostgreSQL connection.

Tests that genuinely require the database (test_db.py, test_ingest_run.py,
etc.) must set DATABASE_URL in the environment to a real Postgres instance —
they connect normally because the patches applied here only prevent the
module-level init and the listing-count query used by the settings page.
"""
from __future__ import annotations

import os
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Suppress the module-level db.init_db() call in app.py and the per-request
# db.get_listing_count() call in the /settings GET handler so that tests
# which only exercise Flask routes (settings, reorder, security, etc.) do
# not require a live Postgres instance.
#
# The patch is applied before any test module is collected, which is when
# `import app` first runs.  Tests that intentionally exercise database
# behaviour will still work because they set DATABASE_URL to a real server
# and can re-enter psycopg2 freely — they just won't be blocked by the
# import-time init call.
# ---------------------------------------------------------------------------
if not os.environ.get("DATABASE_URL"):
    # Provide a dummy URL so db.py's startup guard doesn't raise, then
    # immediately patch the two DB entry-points used by app.py.
    os.environ.setdefault("DATABASE_URL", "postgresql://dummy:dummy@localhost:5432/dummy")

    _init_db_patcher = patch("db.init_db", return_value=None)
    _init_db_patcher.start()

    _listing_count_patcher = patch("db.get_listing_count", return_value=0)
    _listing_count_patcher.start()

    # Patchers are intentionally never stopped — they live for the whole
    # pytest session.
