# Fix #114: JSearch Listings Incorrectly Flagged as Snippets

**Date:** 2026-04-09
**Issue:** [#114](https://github.com/cbeaulieu-gt/job-matcher-pr/issues/114)
**Type:** Bug fix

## Problem

The ingestion pipeline equates `skip_scrape=True` with `description_source="snippet"`.
This is semantically incorrect for sources like JSearch that provide full job descriptions
via their API. All JSearch listings end up in the Snippets feed instead of the main
Listings feed, even though they have complete description text.

### Root Cause

In `ingest.py` (~line 1146), the scrape-skip branch unconditionally sets
`description_source = "snippet"`:

```python
if listing.get("skip_scrape"):
    listing["description_source"] = "snippet"
```

JSearch's `normalise()` sets `skip_scrape=True` because its apply links point to ATS
portals that don't yield useful scraped content — but the API's `job_description` field
contains the full job description. The pipeline conflates "didn't scrape" with "doesn't
have a full description."

Jooble also sets `skip_scrape=True`, but legitimately — its API returns short snippets,
not full descriptions. Any fix must distinguish between these two cases.

## Design: Trust But Verify

Add an optional `description_is_full` boolean field to the canonical listing schema.
When a plugin sets `skip_scrape=True` AND `description_is_full=True`, the pipeline
marks the listing as `"full"` — **provided** the description passes the existing
`_SCRAPE_MIN_LENGTH` (100 chars) sanity check. If the description is too short, it
falls back to `"snippet"` regardless of the flag.

### Why trust-but-verify over pure trust or pure inference

- **Pure trust** (no length check): A JSearch listing with an empty or malformed
  `job_description` would be marked `"full"` incorrectly. API responses can have
  missing fields for individual listings.
- **Pure inference** (length-only, no plugin flag): Would require choosing a threshold
  that works across all sources. Jooble snippets can be 200+ chars — long enough to
  pass a naive length check but still not full descriptions. Plugin intent is the
  better signal.
- **Trust but verify**: Plugin declares intent, pipeline validates with the existing
  100-char floor. Best of both — respects source knowledge while catching edge cases.

## Changes

### 1. Canonical listing schema — new optional field

**Field:** `description_is_full` (boolean, optional, default `False`)

Plugins set this to `True` when their API provides complete job descriptions that
don't need web scraping enrichment. Omitting the field or setting it to `False`
preserves current behavior.

| Plugin | `skip_scrape` | `description_is_full` | Resulting `description_source` |
|--------|--------------|----------------------|-------------------------------|
| JSearch | `True` | `True` | `"full"` (if description >= 100 chars) |
| Jooble | `True` | `False` (default) | `"snippet"` (unchanged) |
| Adzuna | `False` | `False` (default) | Determined by scrape result (unchanged) |
| Himalayas | `False` (default) | `False` (default) | Determined by scrape result (unchanged) |
| Future plugin | `True` | `True` | `"full"` (if description >= 100 chars) |

### 2. Ingest pipeline — `ingest.py` (~line 1146)

Replace the current `skip_scrape` branch:

```python
# Current
if listing.get("skip_scrape"):
    scraped_skipped += 1
    listing["description_source"] = "snippet"
    logger.info("SCRAPE SKIP      [%s] %s", src_name, title)
```

With:

```python
# New
if listing.get("skip_scrape"):
    scraped_skipped += 1
    if (listing.get("description_is_full")
            and len(listing.get("description", "")) >= _SCRAPE_MIN_LENGTH):
        listing["description_source"] = "full"
        logger.info("SCRAPE SKIP (full) [%s] %s", src_name, title)
    else:
        listing["description_source"] = "snippet"
        logger.info("SCRAPE SKIP (snippet) [%s] %s", src_name, title)
```

### 3. JSearch plugin — `plugins/sources/jsearch/plugin.py`

Add `"description_is_full": True` to the `normalise()` return dict, alongside the
existing `"skip_scrape": True`:

```python
"skip_scrape": True,           # Apply links are ATS portals, not scrapable
"description_is_full": True,   # API provides complete job descriptions
```

### 4. DB migration — `db.py` `init_db()`

Add a migration step to reclassify existing JSearch listings:

```sql
UPDATE listings
SET description_source = 'full'
WHERE source = 'jsearch'
  AND LENGTH(description) >= 100
  AND description_source = 'snippet';
```

Wrapped in try/except like existing `ALTER TABLE` migrations, with a log line
reporting how many rows were updated.

### 5. Plugin development docs

Update `docs/PLUGIN_DEVELOPMENT.md` and the plugin template at
`plugins/sources/_template/` to document `description_is_full` as an optional
field in the canonical schema.

### 6. Tests

**`tests/test_snippets.py`:**
- New test: `skip_scrape=True` + `description_is_full=True` + description >= 100
  chars -> `description_source = "full"`
- New test: `skip_scrape=True` + `description_is_full=True` + description < 100
  chars -> `description_source = "snippet"` (verify guard works)
- New test: `skip_scrape=True` + `description_is_full` absent -> `description_source
  = "snippet"` (backward compat)
- Existing tests for scrape-success and scrape-fallback paths remain unchanged.

**`tests/test_job_sources_jsearch.py`:**
- New assertion: `normalise()` output includes `description_is_full=True`
- Existing `test_skip_scrape_is_true` remains unchanged.

**`tests/test_db.py` (or inline in test_snippets.py):**
- Test that the migration updates JSearch snippet rows with long descriptions.
- Test that the migration does NOT update Jooble or other source rows.
- Test that JSearch rows with short descriptions are left as `"snippet"`.

## What doesn't change

- Scraping logic for sources that don't set `skip_scrape` (Adzuna, etc.)
- The `_SCRAPE_MIN_LENGTH` threshold value (100 chars)
- The `/snippets` and `/` feed filtering logic in `app.py` and `db.py`
- Jooble behavior (`skip_scrape=True`, no `description_is_full`)
- Himalayas behavior (does not set `skip_scrape`; unaffected)
- Score calculation or LLM prompt construction
- Database schema columns (no new columns needed — `description_source` already exists)

## Risks

- **Low:** If a plugin incorrectly sets `description_is_full=True` for a source that
  actually provides snippets, listings would appear in the main feed with short
  descriptions. The 100-char guard mitigates this, and plugin authors control their
  own flags.
- **Low:** The DB migration is a targeted UPDATE on `source='jsearch'` rows only.
  No schema changes, no new columns, no index changes.
