# Plan: JSearch API Plugin

## Context

The job-matcher tool has a plugin-based architecture for job sources. The user wants to add JSearch (RapidAPI) as a new source. JSearch aggregates from Google for Jobs and returns full job descriptions in the API response — making it a rich source that doesn't require scraping. The plugin system auto-discovers new plugins at startup with zero changes to core code.

---

## Files to Create

| File | Purpose |
|---|---|
| `plugins/sources/jsearch/plugin.py` | `JSearchClient` class + module-level helpers |
| `plugins/sources/jsearch/source.json` | Plugin metadata, credential field declaration |
| `tests/test_job_sources_jsearch.py` | Unit tests (no real network calls) |

**No core files need modification.** The loader auto-discovers the plugin.

---

## Reference Implementations

| Pattern | Borrow from |
|---|---|
| Keyed constructor (raises ValueError on missing key) | `plugins/sources/jooble/plugin.py` |
| 429 backoff retry loop | `plugins/sources/adzuna/plugin.py` |
| `_CONTRACT_TIME_MAP` + helper function | `plugins/sources/jooble/plugin.py` |
| Test structure, mock patterns | `tests/test_job_sources_jooble.py` |

---

## `source.json`

```json
{
  "source_key": "jsearch",
  "display_name": "JSearch (RapidAPI)",
  "description": "Job aggregator powered by Google for Jobs, accessed via RapidAPI. Free tier: 200 requests/month.",
  "home_url": "https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch",
  "fields": [
    {
      "name": "api_key",
      "label": "RapidAPI Key",
      "type": "password",
      "required": true
    }
  ]
}
```

---

## `plugin.py` Design

### Constants

```
_JSEARCH_URL  = "https://jsearch.p.rapidapi.com/search"
_JSEARCH_HOST = "jsearch.p.rapidapi.com"
```

### Module-level helpers

**`_CONTRACT_TIME_MAP: dict[str, str]`** — keyed by JSearch uppercase strings:

| JSearch | Canonical |
|---|---|
| `FULLTIME` | `full_time` |
| `PARTTIME` | `part_time` |
| `CONTRACTOR` | `contract` |
| `INTERN` | `intern` |

**`_SALARY_PERIOD_MAP: dict[str, str]`**:

| JSearch | Canonical |
|---|---|
| `YEAR` | `annual` |
| `DAY` | `daily` |
| `HOUR` | `hourly` |
| `MONTH` | `month` (pass-through, not in canonical list but preserved) |
| `WEEK` | `week` (pass-through) |

**`_normalise_contract_time(raw: str | None) -> str | None`** — upper() lookup in `_CONTRACT_TIME_MAP`; unknown values lowercased and passed through; `None` → `None`.

**`_normalise_salary_period(raw: str | None) -> str | None`** — upper() lookup in `_SALARY_PERIOD_MAP`; unknown values return `None`; `None` → `None`.

**`_map_date_posted(max_days_old: int) -> str | None`**:

| `max_days_old` | Returns |
|---|---|
| 0 | `None` (omit param) |
| 1 | `"today"` |
| ≤ 3 | `"3days"` |
| ≤ 7 | `"week"` |
| > 7 | `"month"` |

### `JSearchClient(JobSource)`

**`__init__`**
- Credential resolution: `credentials` dict → `config["jsearch"]` legacy sub-dict → `ValueError`
- Store `self._api_key`, `self._search = config["search"]`
- No caching fields needed (unlike Jooble)

**`fetch_page(self, page: int) -> list[dict]`**
- Method: `GET _JSEARCH_URL`
- Headers: `X-RapidAPI-Key`, `X-RapidAPI-Host`
- Params: `query` (built from `what` + optional `" in " + where`), `page`, `num_pages=1`
- Conditional: add `date_posted` if `_map_date_posted(max_days_old)` is not None
- **Timeout: 20s** (JSearch is slow: 1–8s typical)
- 429 backoff (identical pattern to Adzuna): delays `[2, 4, 8]`, 4 total attempts
- Return `[]` on: non-200 non-429, exhausted retries, network exception, bad JSON
- Additional check: `if data.get("status") != "OK": return []` (guards HTTP 200 error envelopes)
- On success: `[self.normalise(job) for job in data.get("data", [])]`

**`total_pages(self) -> int`**
- `return self._search["max_pages"]` — one line, no API call

**`normalise(self, raw: dict) -> dict`**

| Canonical key | Source |
|---|---|
| `source` | `"jsearch"` |
| `source_id` | `str(raw["job_id"])` |
| `title` | `raw["job_title"]` |
| `company` | `raw["employer_name"]` |
| `location` | Join `[job_city, job_state, job_country]` filtering empty; fallback to `job_location` |
| `salary_min` | `raw["job_min_salary"]` (numeric or None, no parsing needed) |
| `salary_max` | `raw["job_max_salary"]` (numeric or None, no parsing needed) |
| `salary_period` | `_normalise_salary_period(raw["job_salary_period"])` |
| `contract_type` | `None` (JSearch doesn't expose this distinction) |
| `contract_time` | `_normalise_contract_time(raw["job_employment_type"])` |
| `description` | `raw["job_description"]` (full plaintext — no HTML stripping needed) |
| `redirect_url` | `raw["job_apply_link"] or raw["job_google_link"] or ""` |
| `created_at` | `raw["job_posted_at_datetime_utc"]` (already ISO 8601) |
| `skip_scrape` | `True` — full description provided; apply links are ATS portals |

**No `pages()` override** — the base class implementation is correct. Unlike Jooble, `total_pages()` makes no API call so there's nothing to cache or reuse.

---

## `tests/test_job_sources_jsearch.py`

Import helpers via the loader-registered module name:
```python
from job_sources._plugin_jsearch import (
    _CONTRACT_TIME_MAP, _SALARY_PERIOD_MAP,
    _normalise_contract_time, _normalise_salary_period, _map_date_posted,
)
JSearchClient = SOURCES["jsearch"]
```

### Test classes

| Class | Key assertions |
|---|---|
| `TestNormaliseContractTime` | All 4 map entries; case-insensitive; unmapped → lowercased passthrough; None → None |
| `TestNormaliseSalaryPeriod` | YEAR/DAY/HOUR mapped; MONTH/WEEK lowercased; unknown → None; None → None |
| `TestMapDatePosted` | Boundary cases at 0, 1, 3, 4, 7, 8, 30 |
| `TestJSearchClientConstructor` | ValueError when key absent/empty; credentials > config legacy; empty-string fallback |
| `TestJSearchNormalise` | All canonical keys present; location assembly; salary passthrough; skip_scrape=True; minimal dict no-raise |
| `TestJSearchClientFetchPage` | 200 success; empty data; status≠OK; non-200; 429 retry×4; network exc; bad JSON; query construction; headers; date_posted inclusion/omission; num_pages=1; timeout=20 |
| `TestJSearchClientTotalPages` | Returns max_pages from config; no HTTP call made |
| `TestJSearchClientPages` | Yields 2 pages; stops early on empty page |
| `TestSourcesRegistry` | "jsearch" in SOURCES; is JobSource subclass |
| `TestJSearchSettingsSchema` | display_name present; 1 field: api_key, password, required |

---

## Known Limitations / Notes

- **`results_per_page` is ignored** — JSearch fixes its own page size (~10). Log at DEBUG in `__init__`.
- **Free tier**: 200 req/month. Default `max_pages=3` is intentionally conservative.
- **No `remote_jobs_only` filter** — current config has no remote flag; can be added later.
- **`MONTH`/`WEEK` salary periods** — not in canonical list but passed through to avoid data loss.

---

## Verification

```powershell
# 1. Validate source.json structure
pytest tests/test_source_json.py -v

# 2. Run new plugin tests (no real network calls)
pytest tests/test_job_sources_jsearch.py -v

# 3. Full test suite (regression check)
pytest

# 4. Start app and verify plugin appears in /settings (requires providers.json update)
python app.py
# Navigate to http://localhost:5000/settings → JSearch (RapidAPI) should appear, disabled

# 5. Add RapidAPI key in /settings, enable, then run ingest
python ingest.py --verbose
```
