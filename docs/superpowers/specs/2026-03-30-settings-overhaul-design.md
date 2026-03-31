# Settings Page Overhaul — Design Spec
_Date: 2026-03-30 | Last revised: 2026-03-30 (post adversarial review)_

## Context

The current Settings page is a flat, hardcoded form supporting exactly three LLM providers (Anthropic, OpenAI, Gemini) and one job source (Adzuna). Adding a new provider requires editing the template, the route handler, and the validation partial by hand.

Additionally, LLM credentials live in `keys.json` while Adzuna credentials are buried in `config.json` — a split that makes credential management inconsistent and will worsen as more job sources are added.

This overhaul introduces:
- A unified `providers.json` credential store (all secrets, one file)
- `settings_schema()` classmethods on existing provider/source classes (manual registry extension, not magic file scanning)
- A tabbed, dynamically-rendered Settings UI
- Drag-to-reorder provider fallback priority (replacing the single `preferred_provider` field)

---

## 1. Credential Architecture — `providers.json`

### Schema

`provider_order` is a **top-level key**, separate from provider credential dicts, to avoid mixing metadata with data.

```json
{
  "provider_order": ["anthropic", "gemini", "openai"],
  "llm": {
    "anthropic": { "api_key": "", "model": "claude-haiku-4-5-20251001" },
    "openai":    { "api_key": "", "model": "gpt-4o-mini" },
    "gemini":    { "api_key": "", "model": "gemini-1.5-flash" }
  },
  "job_sources": {
    "adzuna": { "app_id": "", "app_key": "" }
  }
}
```

- `keys.json` is retired. `config.json` retains search/scoring/prefilter config — zero credentials.
- `providers.example.json` ships alongside for first-time setup.
- Access patterns: `data["provider_order"]`, `data["llm"]["anthropic"]`, `data["job_sources"]["adzuna"]` — callers receive clean sub-dicts, never the entire nested structure.

### `load_providers()` — single shared function in `credentials.py`

**Problem being solved:** `ingest.py` and `app.py` currently each maintain a separate `load_keys()` with conflicting error behavior (one calls `SystemExit`, the other silently defaults). This is resolved by a single `load_providers()` in a new `credentials.py` module imported by both callers.

**Behavior:**
- Reads `providers.json`; if absent, falls back to env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GOOGLE_API_KEY`, `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`)
- Raises `CredentialError` (custom exception defined in `credentials.py`) when neither file nor any env var provides usable credentials
- **Does not** `SystemExit` — callers decide how to handle the error:
  - `ingest.py` catches `CredentialError` and calls `sys.exit(1)` with a clear message
  - `app.py` catches `CredentialError` and returns a safe empty-defaults dict (settings UI still renders)
- Env vars fire **only when `providers.json` is absent**. A present file with empty credential values is "configured but empty" — env vars do not override. This is explicit and documented in `providers.example.json`.

### Migration (auto, on first run)

Triggered when `providers.json` is absent. All cases handled:

| Condition | Behavior |
|---|---|
| `keys.json` present, `config.json` present | Read both, write `providers.json`, log migration notice |
| `keys.json` present, `config.json` absent or no Adzuna keys | Migrate LLM keys only; `job_sources.adzuna` fields written as empty strings |
| `keys.json` absent, `config.json` present with Adzuna keys | Write `providers.json` with empty LLM section, Adzuna credentials populated |
| Neither file present | No migration; fall back to env vars as before |

Migration is atomic: write to a temp file (`providers.json.tmp`), then rename. If the write fails, no partial file is left on disk. `keys.json` and `config.json` are never modified.

`preferred_provider` string → `provider_order` array: preferred becomes position 1, remaining providers appended in dict-insertion order from `keys.json`.

### `build_provider_chain()` — edge case rules

Reads `provider_order` from the top-level key. Explicit rules for all mismatch cases:

| Case | Rule |
|---|---|
| Entry in `provider_order` not in `_PROVIDER_CLASS_MAP` | Silently skipped with a `WARNING` log |
| Entry in `_PROVIDER_CLASS_MAP` not in `provider_order` | Appended at end in registry insertion order |
| Duplicate entries in `provider_order` | Second occurrence silently dropped |
| Empty `provider_order` array | All registered providers used in registry insertion order |
| `provider_order` key missing entirely | Treated as empty array (all providers, registry order) |
| Provider has empty `api_key` | Skipped at runtime regardless of position |

---

## 2. `settings_schema()` + Registry Extension

### What this is — and is not

The existing `providers/__init__.py` has `_PROVIDER_CLASS_MAP` and `job_sources/__init__.py` has `SOURCES`. **These are the registries.** This work extends them with `settings_schema()` — it does not introduce parallel registry dicts. "Auto-discovery" means: the settings route loops the existing registry to build the form, rather than hardcoding each provider in the template.

Adding a new provider still requires: (1) write the class, (2) add one line to the existing registry dict. No template, route, or validation changes required beyond that.

### `settings_schema()` classmethod

Added as an abstract method to `providers/base.py` (`LLMProvider`) and `job_sources/base.py` (`JobSource`). Each concrete class implements it.

**Supported field types in this release: `text` and `password` only.** Richer types (dropdown, toggle, OAuth flow, certificate upload) are explicitly out of scope and deferred. When a provider requires a field type beyond these two, the `settings_schema()` contract will be extended at that time — not speculatively now.

Each field dict must include `required: bool`. Fields marked `required: true` trigger client-side validation before save.

**LLM provider example** (`providers/anthropic_provider.py`):
```python
@classmethod
def settings_schema(cls):
    return {
        "display_name": "Anthropic",
        "fields": [
            {"name": "api_key", "label": "API Key",  "type": "password", "required": True},
            {"name": "model",   "label": "Model ID", "type": "text",     "required": True,
             "default": "claude-haiku-4-5-20251001"},
        ]
    }
```

**Job source example** (`job_sources/adzuna.py`):
```python
@classmethod
def settings_schema(cls):
    return {
        "display_name": "Adzuna",
        "fields": [
            {"name": "app_id",  "label": "App ID",  "type": "password", "required": True},
            {"name": "app_key", "label": "App Key", "type": "password", "required": True},
        ]
    }
```

`settings_schema()` is added to **all seven** existing `job_sources/` implementations (Adzuna, Arbeitnow, Himalayas, RemoteOK, USAJobs, TheMuse, Remotive), even those with no credentials to configure. Sources with no fields return `{"display_name": "...", "fields": []}` and render as a status-only card in the Job Sources tab.

---

## 3. Settings UI

### Tab structure

```
⚙ Settings
├── [LLM Providers]   [Job Sources]
```

**LLM Providers tab:**
- **Fallback Order** section: drag-to-reorder list of all entries in `_PROVIDER_CLASS_MAP`, numbered, with configured/not-set badge
- **Provider cards**: one card per entry in `_PROVIDER_CLASS_MAP`, fields rendered from `settings_schema()`
- **Validate Keys** button (HTMX, updated to loop registry dynamically)
- **Save** button

**Job Sources tab:**
- One card per entry in `SOURCES`, fields from `settings_schema()`
- Sources with empty `fields` list render as status-only (name + configured badge, no inputs)
- **Save** button

### Dynamic rendering

`settings.html` receives `llm_schemas` and `source_schemas` as template context — pre-computed dicts of `{key: settings_schema()}` output, not raw class references. Field types (`password`, `text`) drive the input element rendered via a Jinja2 `{% if %}` block.

### Tab switching

Tab state is tracked with a simple CSS class toggle driven by a **minimal inline `<script>`** — no `hx-push-url`, no query param, no browser history entries created. The correct tab is restored after a save redirect via a `?tab=` query param on the redirect URL only (read once on page load, then discarded). Users pressing Back after a save leave the settings page entirely, as expected.

---

## 4. Drag-to-Reorder Provider Priority

### SortableJS

- Vendored: `static/js/sortable.min.js` (~50 KB, no CDN dependency)
- Initialized via a small inline `<script>` block in `settings.html` (no build step)

### Ordering endpoint

`POST /api/providers/reorder`
- Body: `{"order": ["anthropic", "gemini", "openai"]}`
- Validates all entries are known keys in `_PROVIDER_CLASS_MAP`; rejects unknown entries with 400
- Writes only `provider_order` at the top level of `providers.json`
- On success (200): returns an HTMX fragment updating the order list badges
- On failure (4xx/5xx): returns an error fragment; SortableJS is configured with an `onEnd` callback that reverts the DOM to the server-confirmed order on non-200 response. User sees an inline error message: "Could not save order — check file permissions."

### Behaviour

- Unconfigured providers (empty `api_key`) remain in the list, dimmed, and can be repositioned
- At runtime, `build_provider_chain()` skips unconfigured providers regardless of position
- Order is persisted immediately on drop; no Save button required for ordering

---

## 5. Validation Endpoint Update

`POST /api/validate-keys` and `_validation_results.html` currently hardcode three provider rows. Both are updated to loop `_PROVIDER_CLASS_MAP` dynamically.

**Timeout:** Each provider API call is wrapped with a **5-second per-provider timeout**. If a provider times out, its result state is `unreachable` (same as today's network failure handling). Total endpoint duration is bounded at `5s × N providers` sequential, which is acceptable for ≤6 providers. If provider count grows beyond that, concurrent validation can be added then.

---

## 6. Files Changed

| File | Change |
|---|---|
| `providers.json` + `providers.example.json` | New — unified credential store |
| `.gitignore` | Add `providers.json` |
| `credentials.py` | New — `load_providers()`, `CredentialError`, migration logic |
| `ingest.py` | Replace `load_keys()` call with `load_providers()` from `credentials.py`; catch `CredentialError` → `sys.exit(1)` |
| `app.py` | Replace `_load_keys()` call with `load_providers()` from `credentials.py`; catch `CredentialError` → empty defaults |
| `providers/base.py` | Add abstract `settings_schema()` classmethod |
| `providers/anthropic_provider.py` | Implement `settings_schema()` |
| `providers/openai_provider.py` | Implement `settings_schema()` |
| `providers/gemini_provider.py` | Implement `settings_schema()` |
| `providers/__init__.py` | Update `build_provider_chain()` for top-level `provider_order` array + all edge case rules |
| `job_sources/base.py` | Add abstract `settings_schema()` classmethod |
| `job_sources/adzuna.py` | Implement `settings_schema()` |
| `job_sources/arbeitnow.py` | Implement `settings_schema()` (empty fields) |
| `job_sources/himalayas.py` | Implement `settings_schema()` (empty fields) |
| `job_sources/remoteok.py` | Implement `settings_schema()` (empty fields) |
| `job_sources/usajobs.py` | Implement `settings_schema()` |
| `job_sources/themuse.py` | Implement `settings_schema()` (empty fields) |
| `job_sources/remotive.py` | Implement `settings_schema()` (empty fields) |
| `app.py` (settings route) | Dynamic rendering from schemas; new `/api/providers/reorder` endpoint; updated validation endpoint |
| `templates/settings.html` | Tab structure; Jinja2 loops over schemas; SortableJS wiring + error recovery callback |
| `templates/_validation_results.html` | Loop `_PROVIDER_CLASS_MAP` dynamically |
| `static/js/sortable.min.js` | New — vendored SortableJS |

---

## 7. GitHub Issues / Milestone Plan

**Milestone: Settings Page Overhaul**

| # | Issue | Depends on |
|---|---|---|
| 1 | Introduce `providers.json` + `credentials.py`: unified credential store, `load_providers()` with `CredentialError`, atomic migration, `build_provider_chain()` edge cases, env var fallbacks | — |
| 2 | Add `settings_schema()` to `providers/base.py` + all three LLM provider classes + `job_sources/base.py` + all seven job source classes | #1 |
| 3 | Settings page: tabbed layout with dynamic rendering from schemas; tab switching via CSS class (no browser history); `?tab=` restore on redirect | #2 |
| 4 | Settings page: drag-to-reorder priority (vendor SortableJS, `/api/providers/reorder` with validation + DOM rollback on failure) | #3 |
| 5 | Update `/api/validate-keys` + `_validation_results.html` to loop `_PROVIDER_CLASS_MAP` dynamically; add 5s per-provider timeout | #2 |

Issues 4 and 5 can be worked in parallel once #3 and #2 are done respectively.

---

## 8. Verification

### Happy paths
1. **Migration — full**: delete `providers.json`, run `python ingest.py` with both `keys.json` and `config.json` present → `providers.json` written correctly, log notice visible, ingest succeeds
2. **New provider**: add a stub `providers/fake_provider.py` + one line to `_PROVIDER_CLASS_MAP` → confirm it appears in Settings UI with no other changes
3. **Ordering**: drag providers in UI → confirm `provider_order` updates in `providers.json`; confirm `build_provider_chain()` uses new order in next ingest run
4. **Validation**: hit "Validate Keys" → all registered LLM providers appear in results
5. **Job Sources tab**: Adzuna card renders from `settings_schema()`, save writes to `providers.json`
6. **Env var fallback**: remove `providers.json` entirely, set `ANTHROPIC_API_KEY` env var → ingest works without error

### Failure paths
7. **Migration — missing config.json**: delete `providers.json` and `config.json`, keep `keys.json` → LLM credentials migrate, Adzuna fields written as empty strings, no crash
8. **Migration — partial write failure**: simulate disk-full during write → `providers.json.tmp` is cleaned up, `providers.json` absent, next run retries migration cleanly
9. **Corrupt `providers.json`**: write invalid JSON to `providers.json` → `load_providers()` raises `CredentialError`, ingest exits with readable message, settings UI renders with empty defaults
10. **Reorder POST failure**: return 500 from `/api/providers/reorder` → UI shows error message, DOM reverts to previous order, `providers.json` unchanged
11. **`provider_order` / registry mismatch**: add `"unknown_llm"` to `provider_order` in `providers.json` → WARNING log, entry skipped, remaining order respected, no crash
12. **Duplicate in `provider_order`**: set `["anthropic", "anthropic", "openai"]` → second `anthropic` silently dropped, chain built correctly
13. **Validation provider timeout**: configure a provider with a deliberately unreachable endpoint → result shows `unreachable` within 5s, other providers unaffected
14. **Existing tests**: `pytest` passes with no regressions
