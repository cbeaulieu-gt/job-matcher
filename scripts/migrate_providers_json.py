"""One-shot migration from legacy providers.json shape to native shape.

Converts the job-matcher-pr legacy ``{"job_sources": {...}}`` format to
the ``job_aggregator``-native ``{"schema_version": "1.0", "plugins": {...}}``
format.

Usage
-----
Run from the project root::

    python scripts/migrate_providers_json.py config/providers.json

**Phase A note:** This script is written and committed in Phase A but is
NOT invoked during Phase A's deploy path.  It is invoked at Phase B deploy
time via ``scripts/deploy-remote-linux.sh`` once all 10 sources have been
migrated to ``JobAggregatorProvider``.  See Decision Log #3.

Behaviour
---------
- **Idempotent:** if the file already has ``schema_version`` set to ``"1.0"``
  (native shape), the script exits 0 without modifying the file.
- **Backup:** before any mutation a ``.bak`` copy of the original file is
  written alongside the source file (e.g. ``providers.json.bak``).
- **enabled preservation:** the per-plugin ``enabled`` flag (a
  job-matcher-pr extension key) is preserved exactly in the migrated file.
- **Atomic write:** the migrated content is written to a temp file first
  then renamed over the original, preventing a half-written output on crash.
- **Non-zero exit on error:** malformed JSON or IO failures produce a
  non-zero exit code and do NOT overwrite the original file.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

_SCHEMA_VERSION = "1.0"


def migrate(providers_path: str) -> int:
    """Migrate *providers_path* from legacy shape to native shape in place.

    Does nothing (returns 0) if the file is already in native shape.
    Writes a ``.bak`` backup before any modification.

    Args:
        providers_path: Absolute or relative path to ``providers.json``.

    Returns:
        Exit code: 0 on success or no-op, non-zero on any failure.
    """
    # --- Read original ---
    try:
        with open(providers_path, encoding="utf-8") as fh:
            original_text = fh.read()
    except OSError as exc:
        logger.error("Cannot read %s: %s", providers_path, exc)
        return 1

    try:
        data: dict[str, Any] = json.loads(original_text)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON in %s: %s", providers_path, exc)
        return 1

    # --- Idempotency check ---
    if data.get("schema_version") == _SCHEMA_VERSION:
        logger.info(
            "%s is already in native shape (schema_version=%s); nothing to do.",
            providers_path,
            _SCHEMA_VERSION,
        )
        return 0

    # --- Backup ---
    bak_path = providers_path + ".bak"
    try:
        with open(bak_path, "w", encoding="utf-8") as fh:
            fh.write(original_text)
        logger.info("Backup written to %s", bak_path)
    except OSError as exc:
        logger.error("Cannot write backup to %s: %s", bak_path, exc)
        return 1

    # --- Build migrated dict ---
    migrated: dict[str, Any] = {"schema_version": _SCHEMA_VERSION}

    # Copy all top-level keys except job_sources
    for key, value in data.items():
        if key != "job_sources":
            migrated[key] = value

    # Rename job_sources → plugins (preserving enabled flag and all cred fields)
    job_sources_cfg: dict[str, Any] = data.get("job_sources") or {}
    migrated["plugins"] = {
        source_key: dict(cfg)  # shallow copy preserves all fields incl. enabled
        for source_key, cfg in job_sources_cfg.items()
    }

    # --- Atomic write ---
    dir_name = os.path.dirname(providers_path) or "."
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=dir_name,
            delete=False,
            suffix=".tmp",
        ) as tmp_fh:
            tmp_path = tmp_fh.name
            json.dump(migrated, tmp_fh, indent=2)
            tmp_fh.write("\n")
    except OSError as exc:
        logger.error("Cannot write temp file: %s", exc)
        return 1

    try:
        os.replace(tmp_path, providers_path)
    except OSError as exc:
        logger.error(
            "Cannot rename %s → %s: %s", tmp_path, providers_path, exc
        )
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return 1

    logger.info(
        "Migration complete: %s → schema_version=%s",
        providers_path,
        _SCHEMA_VERSION,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the migration script.

    Args:
        argv: Command-line arguments.  Defaults to ``sys.argv[1:]``.

    Returns:
        Exit code.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    args = argv if argv is not None else sys.argv[1:]

    if len(args) != 1:
        print(
            "Usage: python scripts/migrate_providers_json.py <path/to/providers.json>",
            file=sys.stderr,
        )
        return 2

    return migrate(args[0])


if __name__ == "__main__":
    sys.exit(main())
