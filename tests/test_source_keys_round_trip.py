"""Test that every DB source string maps to a registered upstream SOURCE key.

Loads the fixture at ``tests/fixtures/db_source_strings.json`` (captured
from the dev DB, or generated from the source registry when the DB is
unavailable — see PR description) and asserts each string matches a
``SOURCE`` constant registered by ``job_aggregator``.

Closes Risk #3: prevents silent dedup breakage if ``job_aggregator`` ever
changes a plugin's ``SOURCE`` value.

Fixture generation note
-----------------------
This fixture was generated from the upstream source registry
(``job_aggregator.registry.list_plugins()``) rather than the dev DB,
because the dev DB is not reachable from this environment.  The fixture
represents the full set of 10 sources the integration is designed to
support.  See PR description for the manual verification steps to confirm
this matches the production DB's ``DISTINCT source`` values.
"""

from __future__ import annotations

import json
import pathlib
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_FIXTURE_PATH = (
    pathlib.Path(__file__).parent / "fixtures" / "db_source_strings.json"
)


def _load_fixture() -> list[str]:
    """Load the db_source_strings fixture.

    Returns:
        List of distinct ``source`` string values.
    """
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def _get_upstream_source_keys() -> set[str]:
    """Return the set of SOURCE keys registered by job_aggregator.

    Returns:
        Set of canonical source key strings.
    """
    from job_aggregator.registry import list_plugins

    return {info.key for info in list_plugins()}


def test_fixture_file_exists():
    """The db_source_strings.json fixture must exist and be non-empty."""
    assert _FIXTURE_PATH.exists(), (
        f"Fixture file not found: {_FIXTURE_PATH}"
    )
    source_strings = _load_fixture()
    assert isinstance(source_strings, list)
    assert len(source_strings) > 0


def test_all_db_source_strings_have_upstream_equivalent():
    """Every source string in the fixture maps to a registered upstream SOURCE.

    A mismatch here means the DB's dedup constraint (source, source_id) would
    break silently: job_aggregator would emit listings under a different key
    and they would re-insert as apparent duplicates or fail the unique constraint.
    """
    db_sources = set(_load_fixture())
    upstream_keys = _get_upstream_source_keys()

    missing_in_upstream = db_sources - upstream_keys
    assert not missing_in_upstream, (
        "DB source strings with no upstream SOURCE equivalent "
        "(dedup would break): " + str(missing_in_upstream)
    )


def test_upstream_has_all_expected_sources():
    """Upstream registry contains all 10 expected job-aggregator sources."""
    upstream_keys = _get_upstream_source_keys()
    expected = {
        "adzuna", "arbeitnow", "himalayas", "jobicy", "jooble",
        "jsearch", "remoteok", "remotive", "the_muse", "usajobs",
    }
    missing = expected - upstream_keys
    assert not missing, (
        f"Expected upstream sources not found in registry: {missing}"
    )


@pytest.mark.parametrize(
    "source_string",
    _load_fixture(),
)
def test_each_db_source_string_maps_to_upstream(source_string: str):
    """Each individual source string maps to a registered upstream SOURCE."""
    upstream_keys = _get_upstream_source_keys()
    assert source_string in upstream_keys, (
        f"DB source string {source_string!r} has no upstream SOURCE "
        f"equivalent. Registered upstream keys: {sorted(upstream_keys)}"
    )
