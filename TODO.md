# Job Matcher — Implementation Plan

## Phase 1: Foundation

- [x] Create `requirements.txt` with `flask`, `requests`, `beautifulsoup4`, `anthropic`
- [x] Create `config.example.json` with all keys, placeholder values, and comments
- [x] Create `profile.json` with example skills profile structure
- [x] Create `.gitignore` (exclude `config.json`, `jobs.db`, `__pycache__`, `.env`)
- [x] Implement `db.py` — schema init, all query helpers (`init_db`, `listing_exists`, `insert_listing`, `update_score`, `get_feed`, `get_bookmarks`, `set_bookmarked`, `set_dismissed`)

## Phase 2: Ingestion Pipeline

- [x] Implement `AdzunaClient` in `ingest.py` — paginated fetch, respects `max_pages` config
- [x] Implement `prefilter()` — title include/exclude regex, salary floor, contract type/time
- [x] Implement `scrape_description()` — GET redirect_url, extract visible text via BS4, fallback to API snippet on failure
- [x] Implement `score_listing()` — call Claude Haiku, parse structured JSON response, retry once on failure
- [x] Wire up `run()` orchestrator in `ingest.py` — full pipeline with summary output
- [x] Add startup validation — raise clearly if config keys are missing

## Phase 3: Flask UI

- [x] Implement `app.py` — routes for `/`, `/bookmarks`, `/bookmark/<id>`, `/dismiss/<id>`
- [x] Create `templates/index.html` — header/nav, listing cards, score badge, skill tags
- [x] Create `templates/_card.html` — reusable card partial for HTMX swaps
- [x] Wire up HTMX bookmark toggle — `hx-post`, `hx-swap="outerHTML"` on action buttons
- [x] Wire up HTMX dismiss — `hx-post`, removes card from DOM on success
- [x] Create `static/style.css` — score badge colours, card layout, minimal polish
- [x] Add `get_listing_by_id()` to `db.py` for bookmark toggle read-modify-write
- [x] Create `templates/_actions.html` — action partial returned by POST /bookmark/<id>

## Phase 4: Polish & Documentation

- [x] Add logging throughout `ingest.py` (counts: fetched / pre-filtered / deduped / scraped / scored)
- [x] Handle `score = NULL` listings in UI gracefully (show "pending score" state)
- [x] Write `README.md` — setup steps, config instructions, how to run ingest + server, cron example
- [ ] Manual end-to-end test with real Adzuna API credentials

## Feature: Search Distance Parameter

- [x] Add `search.distance` (km) to `config.example.json`
- [x] Wire `distance` param through `AdzunaClient.fetch_page()` when present
- [x] Update `config.json` to Coconut Creek, 32km (~20 miles)

## Feature: Pre-filter Rejection Reasons

- [x] Change `prefilter()` to return the rejection reason string instead of bare `False`
- [x] Log the specific reason for each filtered listing (title_exclude match, title_include miss, salary, contract type/time)

## Feature: Usage & Cost Tracking

- [x] Add `tokens_input` and `tokens_output` columns to `listings` table (migrate existing DB)
- [x] Capture token usage from Anthropic API response in `score_listing()`, return alongside score data
- [x] Store token counts per listing in DB via `insert_listing()` / `update_score()`
- [x] Add `get_usage_stats()` to `db.py` — total tokens, estimated cost, per-run breakdown
- [x] Print per-run cost estimate in ingest summary line
- [x] Add `/stats` route to `app.py` and `stats` nav tab showing cumulative usage and cost
