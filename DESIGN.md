# Job Matcher — Design Document

> Derived from `REQUIREMENTS.MD`. This document covers architecture, component design,
> data flow, key decisions, and edge-case handling. It is the reference for implementation.

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      ingest.py (CLI)                    │
│                                                         │
│  AdzunaClient → PreFilter → Scraper → Scorer → DB       │
└───────────────────────────┬─────────────────────────────┘
                            │ writes to
                      jobs.db (SQLite)
                            │ reads from
┌───────────────────────────▼─────────────────────────────┐
│                   app.py (Flask server)                  │
│                                                         │
│  GET /          → main feed (scored, not dismissed)     │
│  GET /bookmarks → bookmarked listings only              │
│  POST /bookmark/<id>  → HTMX toggle bookmark           │
│  POST /dismiss/<id>   → HTMX dismiss listing           │
└─────────────────────────────────────────────────────────┘
```

The ingestion pipeline and web server are **fully decoupled**. `ingest.py` is a CLI
script that can be run manually or via cron whether or not the Flask server is running.
They communicate only through the shared SQLite file.

---

## 2. Component Design

### 2.1 `db.py` — Database Layer

Owns all SQLite interactions. Other modules import from here; nothing else touches the DB directly.

**Responsibilities:**
- `init_db()` — create `listings` table if it does not exist
- `listing_exists(adzuna_id)` — dedup check before fetching full description
- `insert_listing(listing_dict)` — insert a new raw listing
- `update_score(adzuna_id, score_dict)` — write Haiku results back to a row
- `get_feed(threshold)` — listings with score ≥ threshold, not dismissed, ordered by score DESC
- `get_bookmarks()` — bookmarked listings ordered by score DESC
- `set_bookmarked(id, value)` — toggle bookmark flag
- `set_dismissed(id, value)` — toggle dismissed flag

**Schema note:** `matched_skills`, `missing_skills`, and `concerns` are stored as JSON
strings and deserialised in Python before being passed to templates.

---

### 2.2 `ingest.py` — Ingestion Pipeline

Runs as a standalone script. Orchestrates the full pipeline in sequence:

```
1. Load config.json and profile.json
2. For each page of Adzuna results (up to exhaustion or page cap):
   a. Fetch page via AdzunaClient
   b. For each listing:
      i.   Pre-filter (title regex, salary, contract type)
      ii.  Dedup check against DB
      iii. Scrape full description from redirect_url
      iv.  Score via Claude Haiku
      v.   Persist to DB
3. Print summary (fetched / filtered / scored / skipped)
```

**Key classes / functions:**

| Name | Purpose |
|---|---|
| `AdzunaClient` | Wraps Adzuna REST API, handles pagination |
| `prefilter(listing, config)` | Returns `True` if listing passes all heuristics |
| `scrape_description(url)` | GETs the redirect URL, extracts visible text via BS4 |
| `score_listing(description, profile, config)` | Calls Haiku, parses structured JSON response |
| `run()` | Top-level orchestrator |

---

### 2.3 `app.py` — Flask Server

Thin server layer. Routes delegate to `db.py`; no business logic lives here.

| Route | Method | Template / Response |
|---|---|---|
| `/` | GET | `index.html` with feed listings |
| `/bookmarks` | GET | `index.html` with bookmarked listings |
| `/bookmark/<id>` | POST | HTMX partial — updated action buttons for that card |
| `/dismiss/<id>` | POST | HTMX — removes card from DOM (empty 200 response) |

HTMX actions swap only the affected card or button — no full page reload.

---

### 2.4 `templates/index.html` — UI

Single template, two modes (`feed` vs `bookmarks`) controlled by a Jinja2 context variable.

**Layout:**
```
┌──────────────────────────────────┐
│  Header: "Job Matcher" | nav     │
├──────────────────────────────────┤
│  [Feed]  [Bookmarks]             │
├──────────────────────────────────┤
│  Card: Title / Company / Location│
│        Score bar  |  Salary      │
│        Matched: Python, Go ...   │
│        Missing:  K8s ...         │
│        Concerns: ...             │
│        Verdict: one sentence     │
│        [View listing] [⭐] [✕]   │
├──────────────────────────────────┤
│  Card: ...                       │
└──────────────────────────────────┘
```

- Score rendered as a coloured badge (green ≥ 8, yellow ≥ 6, red < 6)
- Bookmark (⭐) and Dismiss (✕) use `hx-post` + `hx-swap` to update in place
- "View listing" opens `redirect_url` in a new tab
- No JavaScript other than the HTMX CDN script tag

---

### 2.5 `profile.json` — Skills Profile

Human-editable. Loaded at scoring time and injected into the Haiku prompt verbatim.

```json
{
  "primary_skills": [
    "Python, 5yr, active",
    "Go, 2yr, active",
    "SQL, 6yr, active"
  ],
  "anti_preferences": [
    "no .NET",
    "no pure frontend",
    "no QA/testing roles"
  ],
  "seniority": "Senior / Staff",
  "preferred_industries": ["fintech", "developer tooling", "infrastructure"],
  "location_preference": "remote or Miami, FL"
}
```

---

### 2.6 `config.json` — Runtime Configuration

Never committed to source control (contains API keys). A `config.example.json` is
provided with placeholder values.

```json
{
  "adzuna_app_id": "",
  "adzuna_app_key": "",
  "anthropic_api_key": "",
  "search": {
    "country": "us",
    "what": "software engineer",
    "where": "miami",
    "salary_min": 120000,
    "results_per_page": 50,
    "max_pages": 5
  },
  "scoring": {
    "threshold": 7.0,
    "model": "claude-haiku-4-5-20251001"
  },
  "prefilter": {
    "title_exclude": ["junior", "intern", "lead", "manager", "director", "principal"],
    "title_include": ["engineer", "developer", "architect", "sre", "devops"],
    "require_contract_time": "full_time",
    "require_contract_type": "permanent"
  }
}
```

---

## 3. Data Flow — Ingestion Run

```
ingest.py
  │
  ├─ load config.json, profile.json
  │
  ├─ db.init_db()
  │
  └─ for page in AdzunaClient.pages():
       for listing in page:
         │
         ├─ prefilter() → skip if fails
         ├─ db.listing_exists() → skip if duplicate
         ├─ scrape_description(redirect_url) → full text or fallback to snippet
         ├─ score_listing(text, profile) → {score, matched_skills, ...}
         └─ db.insert_listing({...score data merged in})
```

**Scraping fallback:** If the scraper fails (timeout, bot block, parsing error), the
Adzuna snippet is used as the description and a `scrape_failed` flag is logged. Scoring
still proceeds on the snippet — the score may be lower quality but the listing is not lost.

**Scoring retry:** If the Haiku API call fails or returns malformed JSON, retry once
with a 2-second delay. If it fails again, insert the listing with `score = NULL` and
`seen = FALSE` so it can be re-scored in a future run.

---

## 4. Data Flow — UI Interaction

```
Browser
  │
  ├─ GET / → Flask → db.get_feed(threshold) → render index.html
  │
  ├─ POST /bookmark/42
  │    hx-swap="outerHTML" on the button group
  │    → Flask → db.set_bookmarked(42, True) → render _action_buttons.html partial
  │
  └─ POST /dismiss/42
       hx-swap="outerHTML" hx-target="#card-42"
       → Flask → db.set_dismissed(42, True) → return "" (removes card)
```

---

## 5. Key Design Decisions

### Why SQLite stdlib (not SQLAlchemy)
Keeps dependencies minimal and the schema explicit. The query surface is small and
well-defined; an ORM would add complexity without benefit for a single-user local tool.

### Why HTMX (not React/Vue)
Zero build tooling. The UI is a read-mostly display layer with two write actions.
HTMX handles both with a CDN script tag and two HTML attributes per button.

### Why pre-filter before LLM
Each Haiku call costs ~$0.001. At 500 listings/run with a 60% filter rate, this saves
~300 calls per run (~$0.30). Over weeks of daily runs this compounds meaningfully.

### Why scrape the full description
Adzuna's API snippet is typically 200–300 characters — not enough for reliable skill
matching. The full JD gives Haiku the context it needs for accurate scoring.

### Why decouple ingest from serve
The ingestion run can take minutes (scraping + LLM calls). Running it inside the web
request would be unacceptable. Decoupling means the UI is always snappy and the
ingestion can be automated independently.

### Why `profile.json` rather than a DB table
The profile is edited by the user manually, infrequently, and as a whole unit. A flat
file is simpler to edit and version-control than a DB row.

---

## 6. Error Handling Strategy

| Failure | Handling |
|---|---|
| Adzuna API error (4xx/5xx) | Log and abort run; do not insert partial data |
| Adzuna rate limit (429) | Exponential backoff, max 3 retries |
| Scrape timeout / bot block | Use API snippet as fallback; log warning |
| Scrape produces empty text | Use API snippet as fallback |
| Haiku returns non-JSON | Retry once; if still broken, store with NULL score |
| Haiku API error | Same as above |
| DB write failure | Log and skip listing; do not crash run |
| Missing config keys | Raise on startup with a clear error message |

---

## 7. Dependency List

```
flask
requests
beautifulsoup4
anthropic
```

No other third-party packages. SQLite is stdlib. HTMX is loaded from CDN in the template.

---

## 8. File Map

```
job-matcher/
├── ingest.py              # CLI pipeline: fetch → filter → scrape → score → store
├── app.py                 # Flask server + route handlers
├── db.py                  # SQLite schema init and all query helpers
├── profile.json           # User skills profile (edit this)
├── config.json            # API keys and search config (not committed)
├── config.example.json    # Safe template for config.json
├── requirements.txt       # Python dependencies
├── templates/
│   ├── index.html         # Main template (feed + bookmarks)
│   └── _card.html         # Listing card partial (reused by HTMX swaps)
├── static/
│   └── style.css          # Minimal stylesheet
├── jobs.db                # SQLite database (generated, not committed)
├── REQUIREMENTS.MD        # Original requirements
├── DESIGN.md              # This document
└── TODO.md                # Implementation task list
```

---

## 9. Out of Scope (v1)

See `REQUIREMENTS.MD`. Notably excluded:
- Application status tracking / notes
- Multiple job sources beyond Adzuna
- Resume parsing to generate `profile.json`
- Email digest or notifications
- Any cloud deployment path
