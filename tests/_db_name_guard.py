"""tests/_db_name_guard.py — Pure-function guard for test database name checks.

Exposes ``check_database_url_is_test`` so it can be unit-tested independently
of conftest hooks.  The conftest imports this module, pulls the two env-vars
it needs, and calls the function — keeping all env-coupling in one place.

Design choice — allowlist pattern
----------------------------------
We use a **substring match** (``re.search(r"test", name, re.IGNORECASE)``)
rather than the stricter ``^jobmatcher_test(_.*)?$`` anchor.  Rationale:

* Broader coverage — CI may use ephemeral names like ``github_test_123`` or
  ``myapp_test_pr456``.  Anchoring to the project name would silently reject
  those and force developers to set ``ALLOW_NON_TEST_DB=1`` unnecessarily.
* The common-sense rule is already clear: the word "test" must appear
  somewhere in the database name.  That is easy to reason about and matches
  what every other test in this project already assumes via the
  ``source_id`` prefix convention.
* The escape hatch (``ALLOW_NON_TEST_DB=1``) exists for the narrow case where
  a legitimate non-test DB name is intentional (e.g., an ephemeral CI
  ``jobmatcher_dev`` container spun up just for that run).
"""
from __future__ import annotations

import re
import sys
from urllib.parse import urlparse

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Regex applied (case-insensitively) to the database name portion of the URL.
#: Any DB whose name contains the word "test" is accepted without warning.
_TEST_DB_PATTERN: re.Pattern[str] = re.compile(r"test", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_database_url_is_test(
    url: str,
    allow_override: bool = False,
) -> None:
    """Raise or warn when ``url`` does not point at a test database.

    Parses the DB name out of ``url`` and checks it against the allowlist
    pattern (any name containing the word ``test``, case-insensitive).

    Args:
        url: A PostgreSQL connection URL, e.g.
            ``postgresql://user:pass@host:5432/dbname``.
        allow_override: When ``True``, a non-test DB name emits a stderr
            warning and returns normally instead of raising.

    Raises:
        pytest.UsageError: When the DB name does not match the test-DB
            pattern and ``allow_override`` is ``False``.
        ValueError: When ``url`` cannot be parsed or yields an empty DB name.
    """
    db_name = _extract_db_name(url)

    if _TEST_DB_PATTERN.search(db_name):
        return  # All good — looks like a test DB.

    message = (
        f"DATABASE_URL points at '{db_name}', which does not match the "
        "test-DB pattern (name must contain 'test'). Running the suite here "
        "risks destructive cleanup against real data. "
        "Point DATABASE_URL at a test DB (name containing 'test') or set "
        "ALLOW_NON_TEST_DB=1 to override."
    )

    if allow_override:
        print(
            f"WARNING: {message}",
            file=sys.stderr,
        )
        return

    raise pytest.UsageError(message)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_db_name(url: str) -> str:
    """Return the database name component from a PostgreSQL URL.

    Args:
        url: A connection URL such as
            ``postgresql://user:pass@host:5432/dbname?sslmode=require``.

    Returns:
        The database name string (leading ``/`` stripped, query params
        excluded).

    Raises:
        ValueError: When the URL cannot be parsed or the path component is
            empty after stripping the leading slash.
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:  # pragma: no cover — urlparse rarely throws
        raise ValueError(f"Could not parse DATABASE_URL: {url!r}") from exc

    # urlparse exposes the path as "/dbname" for postgres URLs.
    path = parsed.path
    if not path or path == "/":
        raise ValueError(
            f"Could not extract a database name from DATABASE_URL: {url!r}. "
            "Expected a URL of the form "
            "postgresql://user:pass@host:5432/dbname."
        )

    # Strip the leading slash; ignore any trailing query params (already
    # excluded by urlparse) and fragment.
    db_name = path.lstrip("/")
    if not db_name:
        raise ValueError(
            f"DATABASE_URL has an empty database name: {url!r}"
        )
    return db_name
