"""Protocol definitions for pluggable job-source providers.

This module defines the ``SourceProvider`` Protocol and its associated
value types (``SourceInfo``, ``SourceClient``, ``PluginField``).  These
types describe what ``job-matcher-pr`` consumes from any job-source
provider, regardless of the underlying implementation.

Design rationale
----------------
The types here are *owned by job-matcher-pr*, not by any upstream
package.  ``is_enabled`` and ``credentials_required`` are job-matcher-pr
UX concepts with no upstream equivalent.  ``default`` exists because the
Settings template reads ``field.default`` directly (see
``templates/settings.html`` lines 397, 398, 516).

The ``JobAggregatorProvider`` implementation translates upstream
``job_aggregator`` types into these locally-defined types; a future
``MCPSourceProvider`` would implement the same Protocol directly, with no
knowledge of ``job_aggregator``.

No ``job_aggregator`` import may appear in this file.  A CI enforcement
step (see ``.github/workflows/ci.yml``) rejects any stray import.
"""

from __future__ import annotations

from typing import Iterator, Protocol, runtime_checkable


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@runtime_checkable
class PluginField(Protocol):
    """Describes one credential or configuration field for a source.

    Consumed by the Settings UI to render credential input forms.

    Attributes:
        name: Machine-readable identifier used as the dict key in
            ``providers.json`` (e.g. ``"app_id"``).
        label: Human-readable display name for the Settings template.
        type: Input type hint for the UI; one of ``"text"`` or
            ``"password"``.
        required: ``True`` when the source cannot function without this
            field; drives the ``credentials_required`` rollup.
        help_text: Optional tooltip or placeholder hint shown alongside
            the input.
        default: Optional default value shown as a placeholder in the
            Settings template (``settings.html`` lines 397, 398, 516).
            ``None`` means no default.
    """

    name: str
    label: str
    type: str
    required: bool
    help_text: str | None
    default: str | None


@runtime_checkable
class SourceInfo(Protocol):
    """Complete description of a registered job source.

    Returned by ``SourceProvider.list_sources()`` and consumed by the
    Settings UI and the ingest pipeline.

    Attributes:
        key: Canonical source identifier that maps to the ``source``
            column in the ``listings`` table (e.g. ``"arbeitnow"``).
        label: Human-readable display name for the Settings page.
        fields: Ordered tuple of :class:`PluginField` objects describing
            each credential field.
        is_enabled: ``True`` when the source is active for this ingest
            run.  Derived from the ``enabled`` key in ``providers.json``.
        credentials_required: ``True`` when at least one field has
            ``required=True``.  Computed by the provider implementation.
    """

    key: str
    label: str
    fields: tuple  # tuple[PluginField, ...]
    is_enabled: bool
    credentials_required: bool


@runtime_checkable
class SourceClient(Protocol):
    """A ready-to-use job-source client returned by
    ``SourceProvider.make_clients()``.

    Attributes:
        SOURCE: Canonical source key (e.g. ``"arbeitnow"``).  Must match
            the ``source`` column stored in the ``listings`` table so that
            the dedup check works correctly.
    """

    SOURCE: str

    def pages(self) -> Iterator[list[dict]]:
        """Yield pages of normalised listing dicts.

        Each yielded list contains listing dicts whose keys conform to
        the canonical schema accepted by :func:`db.insert_listing`.
        The caller (``ingest.py``) iterates over pages and individual
        listings within each page.

        Yields:
            A list of canonical listing dicts, one list per page.
        """
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# Provider Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SourceProvider(Protocol):
    """Protocol that any job-source provider implementation must satisfy.

    The ingest pipeline (``ingest.py``) talks to ``SourceProvider``
    instances exclusively — it never imports ``job_aggregator`` or any
    other provider-specific module.  New providers (e.g.
    ``MCPSourceProvider``) are added by implementing this Protocol and
    registering them with the pipeline's provider list.

    Two implementations exist today:

    - ``JobAggregatorProvider`` (``job_sources/aggregator_provider.py``)
      — the upstream ``job_aggregator`` package behind the Protocol.
    - ``LegacyInTreeProvider`` (``job_sources/legacy_provider.py``)
      — wraps the existing ``job_sources/auto_register.py`` loader for
      backward compatibility during Phase A; deleted in Phase B.
    """

    def list_sources(self) -> list[SourceInfo]:
        """Return metadata for every source this provider knows about.

        Used by the Settings UI to render the sources panel and by the
        ingest pipeline to enumerate available sources.

        Returns:
            List of :class:`SourceInfo` objects, one per registered
            source, in stable order.
        """
        ...  # pragma: no cover

    def make_clients(
        self,
        *,
        providers_data: dict,
        search: dict,
    ) -> list[SourceClient]:
        """Return ready-to-use clients for all enabled, credentialled sources.

        Each returned client satisfies the :class:`SourceClient` Protocol;
        calling ``client.pages()`` yields normalised listing dicts.

        Implementations must:

        - Read ``enabled`` from ``providers_data`` and skip disabled
          sources *before* passing credentials to any upstream library.
        - Catch credential / plugin errors per source and log a warning
          rather than aborting the entire call.

        Args:
            providers_data: The full dict returned by
                :func:`credentials.load_providers`.
            search: The ``config["search"]`` sub-dict from
                ``config.json``.

        Returns:
            List of :class:`SourceClient` instances that are ready to
            iterate.
        """
        ...  # pragma: no cover

    def scrape(self, url: str) -> str:
        """Scrape a full job description from *url*.

        Args:
            url: The redirect URL for a listing whose description snippet
                needs to be replaced by the full text.

        Returns:
            The scraped description text.

        Raises:
            Exception: Any network or parse error propagated from the
                underlying scrape implementation.
        """
        ...  # pragma: no cover
