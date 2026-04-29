"""LegacyInTreeProvider — SourceProvider shim wrapping the existing in-tree loader.

This shim exists for Phase A only.  During Phase A, the 9 non-arbeitnow
sources continue to run through the in-tree plugin loader
(``job_sources/__init__.py::make_enabled_sources``) while arbeitnow is
routed through ``JobAggregatorProvider``.

**Deletion trigger:** Phase B.  Once all 10 sources are routed through
``JobAggregatorProvider`` (Phase B), this file is deleted.  The deletion
is listed explicitly in the Phase B "Files touched" section of the plan
(Decision Log #12).
"""

from __future__ import annotations

import logging
from typing import Any

from job_sources import make_enabled_sources as make_enabled_sources_legacy
from job_sources.base import JobSource

logger = logging.getLogger(__name__)


class LegacyInTreeProvider:
    """SourceProvider shim that wraps the existing ``job_sources`` loader.

    Satisfies the ``SourceProvider`` Protocol so the ingest pipeline can
    iterate over a uniform ``list[SourceProvider]`` during the Phase A
    transition period.

    Notes:
        This class must be **deleted in Phase B** once all 10 sources are
        routed through ``JobAggregatorProvider``.  It is intentionally
        minimal — no new behaviour belongs here.
    """

    def list_sources(self) -> list:
        """Return an empty list (legacy sources are not introspected here).

        The legacy loader does not expose a ``list_sources()`` equivalent.
        The Settings UI continues to use ``services/provider_schemas.py``
        for source introspection during Phase A.

        Returns:
            Empty list — the legacy shim does not provide source metadata.
        """
        return []

    def make_clients(
        self,
        *,
        providers_data: dict[str, Any],
        search: dict[str, Any],
    ) -> list[JobSource]:
        """Return enabled in-tree ``JobSource`` instances.

        Delegates directly to :func:`job_sources.make_enabled_sources`
        with the full ``providers_data`` and ``search`` dicts, preserving
        the existing calling convention.

        Args:
            providers_data: Full dict from ``credentials.load_providers()``.
            search: The ``config["search"]`` sub-dict.

        Returns:
            List of instantiated ``JobSource`` objects from the in-tree
            plugin loader.
        """
        return make_enabled_sources_legacy(providers_data, search)

    def scrape(self, url: str) -> str:
        """Not implemented — scraping stays in ``ingest.py`` during Phase A.

        Args:
            url: The redirect URL for the listing.

        Raises:
            NotImplementedError: Always.  Scraping is handled directly
                in ``ingest.py`` for both the legacy and aggregator paths
                during Phase A.
        """
        raise NotImplementedError(
            "LegacyInTreeProvider.scrape() is not implemented; "
            "scraping is handled in ingest.py directly."
        )
