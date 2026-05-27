"""Capture an ingest baseline snapshot for regression comparison.

Captures per-source listing counts and a sample of 3 listings per source
from the database, writing a timestamped JSON file to ``docs/baselines/``.

Usage
-----
Run from the project root::

    python scripts/capture_ingest_baseline.py [--output docs/baselines/YYYY-MM-DD-label.json]

The output file is named automatically if ``--output`` is not specified:
``docs/baselines/<today's date>-<label>.json``.

This script is a Phase A deliverable and is reused for pre/post baselines
in every subsequent phase (B, C, D).  The verification procedure is
documented in the plan at ``docs/superpowers/plans/2026-04-27-job-aggregator-integration.md``
§4 Verification Strategy.

Baseline JSON schema
--------------------
::

    {
      "captured_at": "2026-04-27T12:00:00Z",
      "label": "pre-aggregator",
      "sources": {
        "arbeitnow": {
          "count": 42,
          "sample": [<first 3 listing dicts>]
        },
        ...
      }
    }

Verification diff procedure
---------------------------
After each integration phase, re-run this script and diff the two JSON files:

- **Counts:** within ±10% per source.
- **Sample fields:** ``source``, ``source_id``, ``title``, ``company``,
  ``location``, ``redirect_url`` are byte-identical for at least 1 of 3
  sample listings per source.
- **Description length:** mean and median within ±20%.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).parent.parent
_BASELINES_DIR = _PROJECT_ROOT / "docs" / "baselines"


def capture_baseline(label: str, output_path: str | None = None) -> Path:
    """Capture a baseline snapshot from the database.

    Reads the ``DATABASE_URL`` environment variable and queries the
    ``listings`` table for per-source counts and a sample of 3 listings.

    Args:
        label: Short descriptive label for the snapshot
            (e.g. ``"pre-aggregator"``).
        output_path: Optional explicit output file path.  If ``None``,
            a path is generated from the current date and label.

    Returns:
        The path to the written baseline JSON file.

    Raises:
        SystemExit: If ``DATABASE_URL`` is not set or the query fails.
    """
    import psycopg2
    import psycopg2.extras

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.error("DATABASE_URL is not set; cannot capture baseline.")
        sys.exit(1)

    captured_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        conn = psycopg2.connect(
            db_url, cursor_factory=psycopg2.extras.RealDictCursor
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Cannot connect to database: %s", exc)
        sys.exit(1)

    sources_data: dict[str, dict] = {}

    try:
        with conn.cursor() as cur:
            # Per-source counts
            cur.execute(
                "SELECT source, COUNT(*) AS cnt FROM listings GROUP BY source"
            )
            for row in cur.fetchall():
                sources_data[row["source"]] = {"count": row["cnt"], "sample": []}

            # Per-source sample (first 3 listings by id)
            for source_key in list(sources_data.keys()):
                cur.execute(
                    """
                    SELECT
                        source, source_id, title, company, location,
                        salary_min, salary_max, description,
                        redirect_url, created_at
                    FROM listings
                    WHERE source = %s
                    ORDER BY id
                    LIMIT 3
                    """,
                    (source_key,),
                )
                rows = cur.fetchall()
                sources_data[source_key]["sample"] = [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.error("Query failed: %s", exc)
        sys.exit(1)
    finally:
        conn.close()

    baseline = {
        "captured_at": captured_at,
        "label": label,
        "sources": sources_data,
    }

    if output_path is None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        _BASELINES_DIR.mkdir(parents=True, exist_ok=True)
        out_file = _BASELINES_DIR / f"{today}-{label}.json"
    else:
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)

    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(baseline, fh, indent=2, default=str)
        fh.write("\n")

    logger.info("Baseline captured to %s", out_file)
    return out_file


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments.

    Returns:
        Exit code.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Capture an ingest baseline snapshot from the database."
    )
    parser.add_argument(
        "--label",
        default="baseline",
        help="Short label for the snapshot (default: baseline)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path (default: docs/baselines/<date>-<label>.json)",
    )

    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    out = capture_baseline(label=args.label, output_path=args.output)
    print(f"Baseline written to: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
