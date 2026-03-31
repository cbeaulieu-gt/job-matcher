# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@C:\Users\chris\.claude\standards\software-standards.md

## Commands

```powershell
# Install dependencies
uv pip install -r requirements.txt

# Run ingestion pipeline (fetch → filter → scrape → score → store)
python ingest.py
python ingest.py --hours 25        # Only process listings from the last 25 hours
python ingest.py --rescore         # Re-score all stored listings against updated config/profile.json

# Run web UI (http://localhost:5000)
python app.py

# Run tests
pytest
pytest tests/test_prefilter.py     # Single file
pytest -k "test_title_include"     # By name pattern
```

## Architecture

The app is two decoupled processes sharing a SQLite database (`jobs.db`):

- **`ingest.py`** — CLI pipeline: Adzuna API → pre-filter → scrape full JD → score with Claude Haiku → insert into DB. Runs on a schedule or manually.
- **`app.py`** — Flask web server. Read-only views of scored listings plus HTMX write actions (bookmark, dismiss, apply). Never talks to Adzuna or Anthropic.
- **`db.py`** — All SQLite access. JSON array columns (`matched_skills`, `missing_skills`, `concerns`) are serialized/deserialized here.

### Ingestion pipeline (per listing)

```
Adzuna page → [1] hours filter → [2] prefilter() → [3] dedup check → [4] scrape_description() → [5] score_listing() → db.insert_listing()
```

Any step can short-circuit the listing with a logged reason (`FILTERED`, `DUPE`, `SCRAPE FALLBACK`, `SCORE FAILED`). A summary is printed at the end of each run.

### LLM provider integration

`load_keys()` reads `config/keys.json` (falling back to env vars `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY` if the file is absent). `build_provider_chain()` returns an ordered list of `LLMProvider` instances based on the `preferred_provider` field and dict insertion order. `score_listing_with_fallback()` tries providers in sequence: auth failures (401/403) permanently remove a provider for the run; transient failures skip only the current listing. The scoring prompt expects a JSON response with exactly: `score` (0–10), `matched_skills`, `missing_skills`, `concerns`, `verdict`. Markdown code fences are stripped before parsing.

Results include a `model_used` field stored as `"provider/model"` per listing. Scoring threshold is set in `config/config.json` under `scoring`. Token counts and estimated cost are stored per listing and aggregated in the `/stats` view.

### Config & profile

- **`config/config.json`** — Adzuna credentials (`adzuna_app_id`, `adzuna_app_key`), search params (`country`, `what`, `where`, `distance`, `max_days_old`, `results_per_page`, `max_pages`), scoring threshold, and optional `prefilter` block (title include/exclude patterns, contract type/time).
- **`config/keys.json`** — LLM provider API keys and model selection. Each provider entry has `api_key` and `model`. Dict insertion order defines fallback sequence; `preferred_provider` names the first-choice provider. Managed via the `/settings` UI. Gitignored — copy from `config/keys.example.json` to get started. If absent, `load_keys()` constructs a keys dict from env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`) for backward compatibility.
- **`config/profile.json`** — Candidate skills and preferences injected verbatim into the scoring prompt. Fields: `primary_skills`, `anti_preferences`, `seniority`, `preferred_industries`, `location_preference`, `scoring_notes`.
- **`config/providers.json`** — Unified credential store (replaces `config/keys.json`). Managed via the `/settings` UI. Gitignored — copy from `config/providers.example.json` to get started.
- All files are gitignored. Copy from `*.example.json` to get started.
- Adzuna credentials and `DB_PATH` can be overridden via env vars: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`. `DB_PATH` defaults to `./jobs.db`.

### Database schema notes

- Unique constraint is on `adzuna_id` (one row per Adzuna listing).
- `seen=1` means the listing has been scored; `seen=0` means score failed and it should be retried.
- Schema migration uses `ALTER TABLE ... ADD COLUMN` wrapped in try/except to handle existing databases gracefully.

## Deployment

**Windows native (active deployment path):**
- `scripts/setup.ps1` — Registers waitress as an NSSM Windows service and creates a Task Scheduler job for daily ingest.
- `scripts/status.ps1` / `scripts/teardown.ps1` — Ops helpers.

## UI Development

All UI work must follow `docs/STYLE_GUIDE.md`. Read it before touching any HTML or CSS.

- **Consult first** — the guide documents every CSS token, component class, typography rule, and state convention. Do not introduce new patterns without checking whether an existing one already covers the case.
- **Keep it current** — if a change introduces a new component, token, or convention, update `docs/STYLE_GUIDE.md` in the same PR. The guide is the source of truth, not `static/style.css`.
- **Never hard-code hex values** — always use a CSS custom property from `:root`.
- **Tier colors are semantic** — green (`--score-high-*`) = success/configured/matched; amber (`--score-mid-*`) = warning; red (`--score-low-*`) = error. Do not use tier colors for decorative purposes.

## Key design decisions

| Decision | Why |
|---|---|
| Pre-filter before LLM | Each filtered listing saves a Haiku API call (~$0.001); meaningful at 500 listings/run |
| Scrape full JD | Adzuna snippets (200–300 chars) are too short for accurate skill matching |
| SQLite, no ORM | Schema is small and stable; avoids dependencies and migration tooling |
| HTMX, no JS framework | Zero build tooling for a read-mostly UI with two write actions |
| Decouple ingest from serve | Ingest takes minutes (scraping + LLM); it cannot run inside a web request |
| `config/profile.json` flat file | Edited manually as a whole unit; easier to version-control than a DB record |
| `config/keys.json` separate from `config/config.json` | API keys change more often and are more sensitive than search params; separation allows tighter file ACLs on `config/keys.json` |
