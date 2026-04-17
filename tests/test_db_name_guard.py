"""tests/test_db_name_guard.py — Unit tests for the DB-name safety guard.

These tests exercise ``tests._db_name_guard.check_database_url_is_test``
as a pure function — no live database, no env-var coupling, no subprocess.
The conftest's real env-coupling is intentionally NOT tested here; it only
passes env values into this function.
"""
from __future__ import annotations

import sys

import pytest

from tests._db_name_guard import check_database_url_is_test


# ---------------------------------------------------------------------------
# Happy-path: DB names that contain "test" should pass silently
# ---------------------------------------------------------------------------


class TestAllowedDatabaseNames:
    """DB URLs whose name contains 'test' are accepted without error."""

    def test_jobmatcher_test_passes(self):
        """The canonical test DB name passes without raising."""
        check_database_url_is_test(
            "postgresql://jobmatcher:pw@localhost:5432/jobmatcher_test"
        )

    def test_jobmatcher_test_with_suffix_passes(self):
        """Suffixed test DB names (e.g. jobmatcher_test_pr42) also pass."""
        check_database_url_is_test(
            "postgresql://jobmatcher:pw@localhost:5432/jobmatcher_test_pr42"
        )

    def test_name_containing_test_inline_passes(self):
        """Any name that embeds 'test' anywhere is allowed."""
        check_database_url_is_test(
            "postgresql://u:p@host:5432/mytest_db"
        )

    def test_name_test_only_passes(self):
        """A DB named exactly 'test' passes."""
        check_database_url_is_test("postgresql://u:p@host:5432/test")

    def test_case_insensitive_TEST_upper(self):
        """Upper-case TEST in the DB name is accepted (case-insensitive)."""
        check_database_url_is_test(
            "postgresql://u:p@host:5432/JOBMATCHER_TEST"
        )

    def test_case_insensitive_Test_mixed(self):
        """Mixed-case Test in the DB name is accepted."""
        check_database_url_is_test(
            "postgresql://u:p@host:5432/JobMatcher_Test"
        )

    def test_url_with_query_params_passes(self):
        """Query params (sslmode, etc.) do not interfere with DB name parsing."""
        check_database_url_is_test(
            "postgresql://u:p@host:5432/jobmatcher_test?sslmode=require"
        )

    def test_url_with_port_and_query_passes(self):
        """Non-default port plus query params still parse correctly."""
        check_database_url_is_test(
            "postgresql://u:p@db.example.com:5433/jobmatcher_test"
            "?application_name=pytest&sslmode=require"
        )


# ---------------------------------------------------------------------------
# Fail-fast: non-test DB names without override should raise UsageError
# ---------------------------------------------------------------------------


class TestRejectedDatabaseNames:
    """DB URLs whose name does NOT contain 'test' raise pytest.UsageError."""

    def test_jobmatcher_dev_raises(self):
        """The dev DB name raises UsageError."""
        with pytest.raises(pytest.UsageError, match="jobmatcher_dev"):
            check_database_url_is_test(
                "postgresql://jobmatcher:pw@localhost:5432/jobmatcher_dev"
            )

    def test_jobmatcher_raises(self):
        """A bare 'jobmatcher' DB name (no suffix) raises UsageError."""
        with pytest.raises(pytest.UsageError, match="jobmatcher"):
            check_database_url_is_test(
                "postgresql://jobmatcher:pw@localhost:5432/jobmatcher"
            )

    def test_prod_name_raises(self):
        """A production-style DB name raises UsageError."""
        with pytest.raises(pytest.UsageError, match="jobmatcher_prod"):
            check_database_url_is_test(
                "postgresql://jobmatcher:pw@localhost:5432/jobmatcher_prod"
            )

    def test_error_message_contains_pattern_hint(self):
        """The error message explains how to fix the problem."""
        with pytest.raises(pytest.UsageError) as exc_info:
            check_database_url_is_test(
                "postgresql://u:p@host:5432/myapp_dev"
            )
        msg = str(exc_info.value)
        assert "test" in msg.lower()
        assert "ALLOW_NON_TEST_DB" in msg


# ---------------------------------------------------------------------------
# Override: non-test DB name with allow_override=True warns but proceeds
# ---------------------------------------------------------------------------


class TestAllowOverride:
    """With allow_override=True the guard emits a warning instead of raising."""

    def test_dev_db_with_override_does_not_raise(self):
        """allow_override=True lets a non-test DB through without raising."""
        # Should not raise — just return normally.
        check_database_url_is_test(
            "postgresql://jobmatcher:pw@localhost:5432/jobmatcher_dev",
            allow_override=True,
        )

    def test_dev_db_with_override_emits_stderr_warning(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """allow_override=True prints a WARNING line to stderr."""
        check_database_url_is_test(
            "postgresql://jobmatcher:pw@localhost:5432/jobmatcher_dev",
            allow_override=True,
        )
        captured = capsys.readouterr()
        assert "WARNING" in captured.err
        assert "jobmatcher_dev" in captured.err

    def test_test_db_with_override_does_not_warn(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """A correctly-named test DB produces no warning even with override."""
        check_database_url_is_test(
            "postgresql://u:p@host:5432/jobmatcher_test",
            allow_override=True,
        )
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_prod_name_with_override_does_not_raise(self):
        """Production-named DB is allowed through when override is set."""
        # No exception expected.
        check_database_url_is_test(
            "postgresql://u:p@host:5432/myapp_prod",
            allow_override=True,
        )


# ---------------------------------------------------------------------------
# Malformed / edge-case URLs
# ---------------------------------------------------------------------------


class TestMalformedUrls:
    """Unparseable or structurally invalid URLs raise ValueError."""

    def test_missing_path_raises(self):
        """A URL with no database name component raises ValueError."""
        with pytest.raises(ValueError, match="database name"):
            check_database_url_is_test("postgresql://user:pw@host:5432/")

    def test_url_with_only_slash_raises(self):
        """A URL path of just '/' (empty DB name) raises ValueError."""
        with pytest.raises(ValueError, match="database name"):
            check_database_url_is_test("postgresql://user:pw@host/")

    def test_no_path_at_all_raises(self):
        """A URL with no path component raises ValueError."""
        with pytest.raises(ValueError, match="database name"):
            check_database_url_is_test("postgresql://user:pw@host:5432")

    def test_correct_parsing_of_url_with_query(self):
        """Query params do not bleed into the extracted DB name."""
        # This should pass silently — 'jobmatcher_test' is a valid test name
        # even when followed by ?sslmode=require.
        check_database_url_is_test(
            "postgresql://u:p@host:5432/jobmatcher_test?sslmode=require"
        )

    def test_postgres_scheme_alias_accepted(self):
        """Both 'postgresql' and 'postgres' scheme prefixes are handled."""
        check_database_url_is_test(
            "postgres://u:p@host:5432/jobmatcher_test"
        )
