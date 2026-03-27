# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@C:\Users\chris\.claude\standards\software-standards.md

## Commands

```powershell
# Install dependencies
pip install -r requirements.txt

# Run ingestion pipeline (fetch → filter → scrape → score → store)
python ingest.py
python ingest.py --hours 25        # Only process listings from the last 25 hours
python ingest.py --rescore         # Re-score all stored listings against updated profile.json

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

### Claude integration

`score_listing()` sends the full job description + `profile.json` to Claude Haiku via `client.messages.create()`. It expects a JSON response with exactly: `score` (0–10), `matched_skills`, `missing_skills`, `concerns`, `verdict`. Markdown code fences are stripped before parsing. One retry with a 2-second delay on failure; if both fail, the listing is stored with `score=NULL` for later re-scoring.

Model and threshold are set in `config.json` under `scoring`. Token counts and estimated cost are stored per listing and aggregated in the `/stats` view.

### Config & profile

- **`config.json`** — API keys, Adzuna search params (`country`, `what`, `where`, `distance`, `max_days_old`, `results_per_page`, `max_pages`), scoring threshold and model, and optional `prefilter` block (title include/exclude patterns, contract type/time).
- **`profile.json`** — Candidate skills and preferences injected verbatim into the Haiku prompt. Fields: `primary_skills`, `anti_preferences`, `seniority`, `preferred_industries`, `location_preference`, `scoring_notes`.
- Both files are gitignored. Copy from `*.example.json` to get started.
- All three API keys can be overridden via env vars: `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`, `ANTHROPIC_API_KEY`. `DB_PATH` defaults to `./jobs.db`.

### Database schema notes

- Unique constraint is on `adzuna_id` (one row per Adzuna listing).
- `seen=1` means the listing has been scored; `seen=0` means score failed and it should be retried.
- Schema migration uses `ALTER TABLE ... ADD COLUMN` wrapped in try/except to handle existing databases gracefully.

## Deployment

**Windows native (active deployment path):**
- `scripts/setup.ps1` — Registers gunicorn as an NSSM Windows service and creates a Task Scheduler job for daily ingest.
- `scripts/status.ps1` / `scripts/teardown.ps1` — Ops helpers.

**Docker Compose (portable, not used on homelab server — Docker unsupported there):**
```powershell
docker compose up -d --build
```
Runs `web` (gunicorn) and `scheduler` (daily `ingest.py --hours 25`) services with a bind-mounted data directory.

## Key design decisions

| Decision | Why |
|---|---|
| Pre-filter before LLM | Each filtered listing saves a Haiku API call (~$0.001); meaningful at 500 listings/run |
| Scrape full JD | Adzuna snippets (200–300 chars) are too short for accurate skill matching |
| SQLite, no ORM | Schema is small and stable; avoids dependencies and migration tooling |
| HTMX, no JS framework | Zero build tooling for a read-mostly UI with two write actions |
| Decouple ingest from serve | Ingest takes minutes (scraping + LLM); it cannot run inside a web request |
| `profile.json` flat file | Edited manually as a whole unit; easier to version-control than a DB record |
