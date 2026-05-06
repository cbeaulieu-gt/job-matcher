"""JobAggregatorProvider — SourceProvider implementation backed by job_aggregator.

This is the ONLY file in job-matcher-pr (besides requirements.txt) that
imports ``job_aggregator``.  A CI enforcement step in ``.github/workflows/ci.yml``
rejects any stray ``job_aggregator`` import outside this file.

Phase A scope
-------------
- Reads the legacy ``providers["job_sources"]`` shape unchanged (Phase B
  migrates the on-disk format).
- Filters by per-source ``enabled`` field **before** passing credentials to
  ``make_enabled_sources`` (Decision Log #9 — upstream does not read ``enabled``).
- Passes only the inner per-plugin dict to ``make_enabled_sources(credentials=…)``
  — NOT the whole providers dict (Decision Log #13 / registry.py:201).
- Catches ``CredentialsError``, ``PluginConflictError``, ``SchemaVersionError``
  per source and logs a warning rather than aborting (Risk #5).
- ``translate_job_record()`` converts upstream ``JobRecord`` shape to the
  in-tree DB row shape accepted by ``db.insert_listing()``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Iterator

from job_aggregator.errors import (
    CredentialsError,
    PluginConflictError,
    SchemaVersionError,
)
from job_aggregator.registry import list_plugins, make_enabled_sources
from job_aggregator.schema import SearchParams


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Concrete value types implementing the Protocol
# ---------------------------------------------------------------------------


@dataclass
class _PluginFieldImpl:
    """Concrete implementation of the PluginField Protocol.

    Attributes:
        name: Machine-readable field identifier.
        label: Human-readable display name.
        type: Input type hint (``"text"`` or ``"password"``).
        required: Whether the field is required for plugin operation.
        help_text: Optional tooltip or placeholder hint.
        default: Optional default value shown as a placeholder.
    """

    name: str
    label: str
    type: str
    required: bool
    help_text: str | None
    default: str | None


@dataclass
class _SourceInfoImpl:
    """Concrete implementation of the SourceInfo Protocol.

    Attributes:
        key: Canonical source key (DB ``source`` column value).
        label: Human-readable display name.
        fields: Ordered tuple of :class:`_PluginFieldImpl` objects.
        is_enabled: Whether this source is toggled on.
        credentials_required: True iff any field has ``required=True``.
    """

    key: str
    label: str
    fields: tuple
    is_enabled: bool
    credentials_required: bool


class _SourceClientWrapper:
    """Wraps an upstream ``job_aggregator.base.JobSource`` as a SourceClient.

    Delegates ``pages()`` to the upstream plugin and translates each yielded
    ``JobRecord`` dict into the in-tree DB row shape using
    :func:`translate_job_record`.

    Attributes:
        SOURCE: Canonical source key; matches the upstream plugin's ``SOURCE``.
    """

    def __init__(self, upstream_client: Any) -> None:
        """Initialise the wrapper.

        Args:
            upstream_client: An instantiated ``job_aggregator.base.JobSource``
                whose ``SOURCE`` attribute and ``pages()`` method will be
                proxied.
        """
        self._client = upstream_client
        self.SOURCE: str = upstream_client.SOURCE

    def pages(self) -> Iterator[list[dict]]:
        """Yield pages of translated DB-row dicts.

        Delegates to the upstream plugin's ``pages()`` generator.  Each
        raw record is first **normalised** via the plugin's own
        ``normalise()`` method (which maps source-specific field names
        to the canonical :class:`~job_aggregator.schema.JobRecord` shape
        and populates ``source`` / ``source_id``), then translated to
        the in-tree DB row shape via :func:`translate_job_record`.

        Records whose ``title`` is ``None`` or empty after normalisation
        are silently skipped with a warning log rather than emitted as
        broken rows.  Emitting them would crash ``prefilter()`` at
        ``ingest.py:370`` (``title.lower()``).

        Yields:
            Lists of translated listing dicts, one list per page.
            Pages may be shorter than the raw page when records are
            skipped due to a missing title.
        """
        for raw_page in self._client.pages():
            translated: list[dict] = []
            for raw in raw_page:
                normalised = self._client.normalise(raw)
                if not normalised.get("title"):
                    logger.warning(
                        "%s: skipping record with missing title "
                        "(source_id=%r) — would crash prefilter()",
                        self.SOURCE,
                        normalised.get("source_id"),
                    )
                    continue
                translated.append(translate_job_record(normalised))
            yield translated


# ---------------------------------------------------------------------------
# Public translation function (tested independently)
# ---------------------------------------------------------------------------


def translate_job_record(record: dict[str, Any]) -> dict[str, Any]:
    """Translate an upstream JobRecord dict into the in-tree DB row shape.

    The upstream ``JobRecord`` TypedDict is a superset of the in-tree
    canonical schema.  This function:

    - Renames ``url`` → ``redirect_url``
    - Renames ``posted_at`` → ``created_at``
    - Converts ``company: None`` → ``company: ""`` (in-tree convention)
    - Drops upstream-only fields: ``description_source``, ``extra``,
      ``remote_eligible``, ``salary_currency``

    All other fields (``source``, ``source_id``, ``title``, ``location``,
    ``salary_min``, ``salary_max``, ``salary_period``, ``contract_type``,
    ``contract_time``, ``description``) are passed through unchanged.

    Args:
        record: A dict conforming to ``job_aggregator.schema.JobRecord``.

    Returns:
        A dict whose keys and types are accepted by ``db.insert_listing()``.
    """
    result: dict[str, Any] = {}

    # --- Pass-through fields ---
    for key in (
        "source",
        "source_id",
        "title",
        "location",
        "salary_min",
        "salary_max",
        "salary_period",
        "contract_type",
        "contract_time",
        "description",
    ):
        result[key] = record.get(key)

    # --- Renamed fields ---
    result["redirect_url"] = record.get("url", "")
    result["created_at"] = record.get("posted_at")

    # --- company: None → "" (in-tree stores empty string, not None) ---
    company = record.get("company")
    result["company"] = company if company is not None else ""

    # Fields deliberately dropped:
    # - description_source (upstream-only provenance field)
    # - extra              (upstream-only blob)
    # - remote_eligible    (upstream-only boolean)
    # - salary_currency    (in-tree schema has no currency column)

    return result


# ---------------------------------------------------------------------------
# Helper: legacy shape → native credentials shape (in-memory, Phase A only)
# ---------------------------------------------------------------------------


def _extract_plugin_credentials(
    job_sources_cfg: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Extract per-plugin credentials from the legacy ``job_sources`` block.

    Phase A reads the legacy ``providers["job_sources"]`` shape unchanged.
    This helper strips the job-matcher-pr-specific ``enabled`` key and
    returns a dict keyed by source name, where each value is the credential
    fields dict expected by ``registry.py:201``'s ``credentials.get(key, {})``.

    Sources with ``enabled: false`` are silently omitted so they are never
    passed to ``make_enabled_sources``.  This implements the enablement
    filter required by Decision Log #9 / AC #5.

    Args:
        job_sources_cfg: The ``providers["job_sources"]`` sub-dict from
            ``providers.json``.

    Returns:
        Dict mapping enabled source keys to their credential field dicts.
    """
    result: dict[str, dict[str, Any]] = {}
    for key, cfg in job_sources_cfg.items():
        if not isinstance(cfg, dict):
            continue
        # Default: keyless sources (empty credentials) are enabled by
        # default; keyed sources default to False when absent.
        is_enabled = cfg.get("enabled", True)
        if not is_enabled:
            logger.debug(
                "Source %r has enabled=false; skipping before make_enabled_sources",
                key,
            )
            continue
        # Strip the ``enabled`` key — upstream does not expect it.
        creds = {k: v for k, v in cfg.items() if k != "enabled"}
        result[key] = creds
    return result


# ---------------------------------------------------------------------------
# JobAggregatorProvider
# ---------------------------------------------------------------------------


class JobAggregatorProvider:
    """SourceProvider implementation backed by the ``job_aggregator`` package.

    This is the sole consumer of ``job_aggregator`` in job-matcher-pr.
    The ingest pipeline and Settings UI talk to the ``SourceProvider``
    Protocol, never to this class directly.

    Phase A: reads legacy ``providers["job_sources"]`` shape; arbeitnow is
    routed through this provider when ``JOB_AGGREGATOR_SOURCES=arbeitnow``
    is set.  Phase B will extend this to all 10 sources and migrate the
    on-disk format.
    """

    def list_sources(self) -> list[_SourceInfoImpl]:
        """Return metadata for every upstream-registered source.

        Translates each upstream ``PluginInfo`` into a job-matcher-pr
        ``SourceInfo`` by:

        - Copying ``key`` and ``display_name`` → ``label``.
        - Translating upstream ``PluginField`` objects into
          ``_PluginFieldImpl`` (adding ``default=None`` which the Settings
          template reads but upstream does not expose).
        - Computing ``credentials_required`` from ``requires_credentials``.
        - Setting ``is_enabled=False`` as a safe default (the pipeline
          sets this from ``providers.json`` at runtime).

        Returns:
            List of ``_SourceInfoImpl`` objects, one per registered source.
        """
        infos: list[_SourceInfoImpl] = []
        try:
            upstream_infos = list_plugins()
        except (PluginConflictError, Exception) as exc:
            logger.warning("list_sources: failed to enumerate plugins: %s", exc)
            return infos

        for upstream in upstream_infos:
            fields: tuple[_PluginFieldImpl, ...] = tuple(
                _PluginFieldImpl(
                    name=f.name,
                    label=f.label,
                    type=f.type,
                    required=f.required,
                    help_text=f.help_text,
                    default=None,  # upstream PluginField has no default
                )
                for f in upstream.fields
            )
            infos.append(
                _SourceInfoImpl(
                    key=upstream.key,
                    label=upstream.display_name,
                    fields=fields,
                    is_enabled=False,  # set from providers.json at runtime
                    credentials_required=upstream.requires_credentials,
                )
            )
        return infos

    def make_clients(
        self,
        *,
        providers_data: dict[str, Any],
        search: dict[str, Any],
        only_sources: Iterable[str] | None = None,
    ) -> list[_SourceClientWrapper]:
        """Return ready-to-use clients for enabled, credentialled sources.

        Phase A reads the legacy ``providers["job_sources"]`` shape.

        Steps:
        1. Extract the ``job_sources`` sub-dict.
        2. Filter by ``enabled`` field (Decision Log #9) — disabled sources
           are removed from the credentials dict **before** calling
           ``make_enabled_sources``.
        3. Pass only the inner per-plugin dict to ``make_enabled_sources``
           (Decision Log #13 / registry.py:201 contract).
        4. Catch ``CredentialsError``, ``PluginConflictError``, and
           ``SchemaVersionError`` and log a warning rather than aborting
           (Risk #5).
        5. Apply the ``only_sources`` allow-list **after**
           ``make_enabled_sources`` returns.  This is the correct place to
           filter because keyless sources (himalayas, jobicy, remoteok,
           remotive) have no entries in the credentials dict — filtering the
           credentials dict alone is a no-op for them (Bug A, issue #363).
        6. Wrap each returned upstream ``JobSource`` in
           ``_SourceClientWrapper``.

        Args:
            providers_data: Full dict from ``credentials.load_providers()``.
            search: The ``config["search"]`` sub-dict.
            only_sources: When non-``None``, only clients whose ``SOURCE``
                attribute is in this iterable are returned.  Pass
                ``None`` (the default) to return all enabled clients.
                The ``JOB_AGGREGATOR_SOURCES`` env-var logic in
                ``ingest.py`` passes the parsed key set here so that
                keyless sources are properly excluded.

        Returns:
            List of :class:`_SourceClientWrapper` instances ready to iterate.
        """
        job_sources_cfg: dict[str, Any] = (
            providers_data.get("job_sources") or {}
        )

        # Step 2: filter by enabled (Decision Log #9)
        # Only enabled sources reach make_enabled_sources.
        plugin_credentials = _extract_plugin_credentials(job_sources_cfg)

        # Step 3: build SearchParams from config["search"]
        upstream_search = SearchParams(
            query=search.get("what"),
            location=search.get("where"),
            country=search.get("country"),
            hours=search.get("max_days_old", 7) * 24,
            max_pages=search.get("max_pages"),
        )

        # Step 4: call make_enabled_sources with inner dict, catch errors
        upstream_clients: list[Any] = []
        try:
            upstream_clients = make_enabled_sources(
                credentials=plugin_credentials,
                search=upstream_search,
            )
        except CredentialsError as exc:
            logger.warning(
                "JobAggregatorProvider.make_clients: CredentialsError — %s",
                exc,
            )
        except PluginConflictError as exc:
            logger.warning(
                "JobAggregatorProvider.make_clients: PluginConflictError — %s",
                exc,
            )
        except SchemaVersionError as exc:
            logger.warning(
                "JobAggregatorProvider.make_clients: SchemaVersionError — %s",
                exc,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "JobAggregatorProvider.make_clients: unexpected error — %s",
                exc,
            )

        # Step 5: apply only_sources allow-list AFTER make_enabled_sources.
        # Filtering the credentials dict (as ingest.py did before this fix)
        # is insufficient because keyless sources have no credential entries
        # to begin with — the upstream registry instantiates them regardless.
        # Filtering here, on the returned client list, catches all source
        # types correctly (Bug A fix, issue #363).
        if only_sources is not None:
            allow_set = frozenset(only_sources)
            upstream_clients = [
                c for c in upstream_clients if c.SOURCE in allow_set
            ]

        # Step 6: wrap upstream clients
        return [_SourceClientWrapper(c) for c in upstream_clients]

    def scrape(self, url: str) -> str:
        """Scrape a full job description from *url*.

        Delegates to the in-tree ``ingest.scrape_description()`` helper.
        In Phase A this method is not used by the pipeline directly (scraping
        remains in ``ingest.py``); it satisfies the Protocol signature.

        Args:
            url: The redirect URL for the listing.

        Returns:
            The scraped description text, or an empty string on failure.
        """
        # Phase A: scraping stays in ingest.py.  This satisfies the Protocol
        # but is not called by the pipeline yet.
        raise NotImplementedError(
            "scrape() is not yet delegated to JobAggregatorProvider; "
            "scraping is still handled in ingest.py for Phase A."
        )
