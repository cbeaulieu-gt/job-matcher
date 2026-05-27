# Phase B — job-aggregator migration: remaining 9 sources + flag removal

**Tracking:** Issue #347 under Milestone #8 ("Phase 2: job-aggregator integration") in `cbeaulieu-gt/job-matcher-pr`.

**Predecessor plan:** [`docs/superpowers/plans/2026-04-27-job-aggregator-integration.md`](./2026-04-27-job-aggregator-integration.md) — that document covers Phases A→E at the architectural level. **This file does not modify the predecessor plan.** It is the Phase B execution plan, scoped to the work that lands in PR(s) closing #347.

**Phase A status (verified 2026-05-06 against `main` @ `9c04f11`):**
- `JobAggregatorProvider` and `LegacyInTreeProvider` exist (PR #351, file `job_sources/aggregator_provider.py`, `job_sources/legacy_provider.py`).
- Feature flag `JOB_AGGREGATOR_SOURCES` routes per-source between providers; arbeitnow is the only source currently routed through the aggregator.
- Bug-fix PRs #358, #361, #362, #364 are merged; PR #364's live smoke proved exclusive routing for arbeitnow with 0 LISTING FAILED and no `None:` source bucket.
- Pre-Phase-B verify script `scripts/verify_phase_a_pre_b.ps1` exists (PR #353).
- 2192 unit tests green.

---

## 1. Objective

Phase B retires the `JOB_AGGREGATOR_SOURCES` feature flag by routing the remaining 9 in-tree sources (`adzuna`, `himalayas`, `jobicy`, `jooble`, `jsearch`, `remoteok`, `remotive`, `the_muse`, `usajobs`) through `JobAggregatorProvider`, deleting `job_sources/legacy_provider.py`, and migrating `config/providers.json`'s on-disk shape from `{"job_sources": {...}}` to `{"schema_version": "1.0", "plugins": {...}}` per the predecessor plan's Decision Log #3 and #12.

**Definition of done (the merge criterion for #347):**

1. `grep -rn JOB_AGGREGATOR_SOURCES` over the repo returns empty (CLAUDE.md removal criterion, lines 23–27).
2. `grep -rn 'providers\["job_sources"\]\|providers.get("job_sources")\|"job_sources"' --include='*.py'` returns empty.
3. `git ls-tree HEAD -- job_sources/legacy_provider.py` returns empty (file deleted).
4. Routing parity with the legacy baseline (`docs/baselines/2026-05-06-phase-b-legacy-baseline.log`, captured in Stream 0's PR per §5 Step 0.5) — `python ingest.py --hours 24` completes against the dev DB with all 10 sources fetched via `JobAggregatorProvider`, 0 `LISTING FAILED`, 0 `None:` source buckets in the summary. A source that returned 0 rows on the legacy path may return 0 rows on the aggregator path; that is acceptable as long as the routing change itself is neutral or positive. Zero-row diagnosis is tracked in separate issues, not in #347. See §5 "Severable item — zero-row diagnosis" for process.
5. All `pytest` suites green (≥ the 2192-test baseline; new tests added per §3).
6. `scripts/deploy-remote-linux.sh` preflight detects + migrates a legacy-shape `providers.json` on the prod server, leaves a `.bak`, and aborts cleanly on migration failure.
7. The final PR body contains the plain-text closing keyword `Closes #347` (CLAUDE.md "Pull Requests" rule — backticks break GitHub's parser; do NOT format as ``Closes #347``).

---

## 2. Strategy

Three options were considered. Recommendation: **Option B — three-stream migration: in-memory auto-migration first (Stream 0), source routing + shape migration second (Stream 1), flag and legacy-provider deletion last (Stream 2).**

**Why this is not a return to the original three-stream plan.** The original Stream 1 was a no-op rehearsal — it extended the env-var to include 4 keyless sources whose routing path stayed dormant until the flag was deleted. Inquisitor pass 1 rejected that as ceremony and collapsed it into the shape migration. Stream 0 here is structurally different: it is a safety-net-first addition. The in-memory auto-migration in `credentials.load_providers()` is a pure addition to one function — no readers change, no on-disk format changes, no routing changes. It must land in its own PR so that a regression bisect of Stream 1 can distinguish auto-migration bugs from shape-rewrite misses from routing translation regressions. The safety net cannot be "introduced by the PR it is supposed to protect." That is the structural reason for the three streams; it has nothing to do with rehearsal of a dormant path.

### Option A — Big-bang: migrate all 9 sources + drop flag in one PR

**Pros:** One review cycle. One baseline diff. The "is the flag really gone" check is binary at merge time.

**Cons:** Failure mode is "the entire production ingest run silently regresses across 9 sources." 5 of the 9 sources (`himalayas`, `jooble`, `jsearch`, `the_muse`, `usajobs`) returned 0 rows in PR #364's live smoke — those zero-row results may indicate plugin-level bugs that surface only when each source is exercised individually. Wrapping that diagnosis into a single PR conflates "did the bridge wire up correctly?" with "does this plugin fetch any rows?" Rollback is `git revert` of one large PR plus a `providers.json` `.bak` restore — that works, but the blast radius is the whole nightly run for ~24h until the revert merges and deploys.

### Option B — Three streams: auto-migration safety net first, routing + shape migration second, flag removal last (RECOMMENDED)

**Pros:**
- **Stream 0 (in-memory auto-migration only):** writes legacy `job_sources` → native `plugins` shape detection + in-memory rewrite in `credentials.py:load_providers()`. Pure addition — no reader changes, no on-disk format changes, no routing changes. Does NOT write back to disk. Idempotent on already-native shape. Adds `tests/test_credentials_native_shape.py`. This is the safety net; it lands first so Stream 1's regression bisect is clean.
- **Stream 1 (all 9 sources + shape migration):** routes all remaining sources through `JobAggregatorProvider` and migrates the on-disk `providers.json` shape. The auto-migration safety net from Stream 0 is already active. The `JOB_AGGREGATOR_SOURCES` flag is updated to default to all 10 sources but is not yet deleted — it acts as a kill switch through Stream 1's bake-in window.
- **Stream 2 (flag removal):** trivial after Stream 1 lands; deletes `legacy_provider.py`, the flag constant, `LegacyInTreeProvider` branch in `ingest.py`, and associated tests. Mostly deletion plus one small rewrite and one replacement test.
- **Rollback shape is per-stream:** if Stream 1 regresses a source but Stream 2 has not yet merged, `git revert` Stream 1 alone. If Stream 0's auto-migration is the problem, `git revert` Stream 0 (Stream 1 cannot have merged yet — linear dependency). Stream 2 cannot have merged until Stream 1 is stable.
- Matches the project's actual PR cadence: PRs #358, #361, #362, #364 each addressed one or two issues at a time.

**Cons:** Three PRs instead of one means ~3× the CI time and review overhead. Mitigated by Stream 0 being ~1 file edited + 1 test file added (very fast review) and Stream 2 being nearly pure deletion.

### Recommendation

**Option B**, three sequential PRs landing on a feature branch `feat/347-aggregator-phase-b`:

- `feat/347-aggregator-phase-b` (feature branch, off `main`)
- Stream 0 PR merges into `feat/347-aggregator-phase-b`
- Stream 1 PR merges into `feat/347-aggregator-phase-b` (depends on Stream 0 merged)
- Stream 2 PR merges into `feat/347-aggregator-phase-b` (depends on Stream 1 stable)
- Feature-branch PR merges to `main` after all three streams are complete

Worktree (per CLAUDE.md): `.worktrees/feat-347-aggregator-phase-b`, created with `git worktree add` from inside the repo. No sub-worktrees per stream — both streams are sequential work in the same worktree.

---

## 3. Per-source migration sub-tasks

Each source is a checklist under its assigned stream. Per-source acceptance criteria common to all 9:

- [ ] Source's `SOURCE` constant in `job_aggregator` matches the in-tree DB `source` string (already verified for the original 5 in `tests/fixtures/db_source_strings.json`; **fixture must be refreshed** before Stream 1 to include all 10 — see §5 verification step 0).
- [ ] Per-source `JobRecord` → DB-row translation unit test added to `tests/test_aggregator_provider.py` using a captured upstream fixture.
- [ ] Live ingest smoke against `--hours 168` returns row count ≥ `docs/baselines/2026-05-06-phase-b-legacy-baseline.log` OR zero-row result documented in PR description with a linked diagnosis issue.
- [ ] DB rows after the smoke have `source = "<exact-key>"` matching the legacy `source` string for that plugin (no `(source, source_id)` UNIQUE-constraint regressions).

### Stream 0 — `credentials.py` in-memory auto-migration (PR #X0)

This stream is a pure addition: one file edited, one test file added. No reader changes, no on-disk format changes, no routing changes. Its sole purpose is to ensure the safety net is on `main` (via the feature branch) before any shape rewrite or routing change exists.

**Stream 0 file-edit checklist:**

- [ ] **Before writing the migration:** read `scripts/migrate_providers_json.py` and document in a code comment at the top of the new migration block in `credentials.py:load_providers()` which decisions are inherited from the on-disk script. The two paths must produce structurally identical output for any given input. Any divergence must be intentional and explained in the comment.
- [ ] **`credentials.py:load_providers()`** — add legacy `job_sources` → native `plugins` shape detection + in-memory rewrite. Keep the rewrite local to the loaded dict; do NOT write back to disk. Idempotent on already-native shape. The migration touches only the `job_sources` ↔ `plugins` rename; sibling top-level keys (`llm`, `provider_order`, `schema_version`, etc.) are passed through unchanged.
- [ ] **`tests/test_credentials_native_shape.py`** (new) — covers all edge cases per the table below.

**Edge-case specification for `tests/test_credentials_native_shape.py`:**

| Input shape | In-memory result | Test name |
|---|---|---|
| `{"job_sources": {...}}` only (legacy) | Migrate to `{"plugins": {...}}` in-memory; do NOT write to disk | `test_legacy_only_migrates_to_native` |
| `{"plugins": {...}}` only (native) | Return as-is; idempotent | `test_native_only_unchanged` |
| `{"job_sources": {...}, "plugins": {...}}` (both keys) | Prefer `plugins`, log a warning, drop `job_sources`; do NOT raise (file is functionally native + leftover) | `test_both_keys_prefers_plugins_with_warning` |
| `{"job_sources": {}, "plugins": {...}}` (empty legacy leftover) | Treat as native; drop empty `job_sources`; no warning | `test_empty_legacy_dropped_silently` |
| `{"schema_version": "1.0", "job_sources": {...}}` (version says native, shape says legacy) | Migrate `job_sources` → `plugins`; preserve `schema_version` | `test_versioned_legacy_migrates` |

Plus an explicit invariant: **the migration touches only the `job_sources` ↔ `plugins` rename. Sibling top-level keys (`llm`, `provider_order`, `schema_version`, etc.) are passed through unchanged.** A `test_llm_section_passthrough` test loads a fixture with both `llm` and `job_sources` keys and asserts the resulting dict has `llm` unchanged + `plugins` migrated.

**Stream 0 acceptance criteria:**

- [ ] `pytest tests/test_credentials_native_shape.py` green (all six test cases above pass).
- [ ] Load each of the five edge-case fixtures and verify behavior matches the spec in the table above.
- [ ] `credentials.py:load_providers()` migration block contains a comment documenting inherited decisions from `scripts/migrate_providers_json.py`.
- [ ] `grep -rn 'def load_providers' credentials.py` confirms the function is still a single entry point (no parallel code paths introduced).
- [ ] Legacy baseline log captured and committed — see §5 Step 0.5.

---

### Stream 1 — all 9 sources + on-disk shape migration (PR #X1)

This stream does the routing change for all 9 remaining sources AND the on-disk credential-shape rewrite. Stream 0's in-memory auto-migration safety net is already active at this point. It touches every reader of `providers["job_sources"]` (predecessor plan §2 Phase B "Files touched" — verified line numbers below against the current main). The `JOB_AGGREGATOR_SOURCES` flag default is updated to include all 10 sources but the flag is not deleted yet.

**Keyless sources (no credentials required):**

- [ ] **`himalayas`** — verified keyless. Known concern: 0 rows in PR #364 smoke. Diagnosis: run `python ingest.py --hours 168 -v` filtered to himalayas only; check upstream `pages()` generator behavior. If 0 rows is an upstream bug, file an issue against `cbeaulieu-gt/job-aggregator` (Phase E ticket #350 trigger condition); do NOT block Stream 1 on the row count if the diagnosis shows the bridge is wired correctly.
- [ ] **`jobicy`** — verified keyless (Resolved 2026-05-06: `config/providers.example.json` has no `api_key` field for jobicy). Known concern: 0 rows in PR #364 smoke. Same diagnosis approach as himalayas.
- [ ] **`remoteok`** — verified keyless. Currently fetches successfully under legacy path; routing flip should be neutral.
- [ ] **`remotive`** — verified keyless. Same as remoteok.

**Keyed sources (credentials required):**

- [ ] **`adzuna`** — keyed (`app_id`, `app_key`). `_inject_env_var_credentials()` at `ingest.py:1085–1092` writes into `providers.setdefault("job_sources", {}).setdefault("adzuna", {})`; rewrite to write into `providers["plugins"]["adzuna"]`. Cross-check `services/provider_schemas.py:163` (`(providers.get("job_sources") or {}).get("adzuna")`) and update.
- [ ] **`jooble`** — keyed (`api_key`). Known concern: 0 rows in PR #364 smoke. Diagnosis path same as himalayas; jooble's API requires a key in the request body, so a credential-shape bug would also produce 0 rows. The Stream 1 migration is therefore a load-bearing fix candidate.
- [ ] **`jsearch`** — keyed (`api_key` or RapidAPI key). Known concern: 0 rows. Same diagnosis path.
- [ ] **`the_muse`** — keyed. Known concern: 0 rows. Same diagnosis path.
- [ ] **`usajobs`** — keyed (`user_agent`, `auth_key`). Known concern: 0 rows. Same diagnosis path.

**Stream 1 file-edit checklist (verified line numbers against current main):**

- [ ] `ingest.py:1085–1092` — `_inject_env_var_credentials()` rewritten to use `plugins` shape.
- [ ] `ingest.py:1149–1174` — `_build_source_clients()` rewritten to translate the new on-disk shape (legacy `job_sources` reads removed; `plugins` reads added). Flag-handling stays in this PR; flag default updated to all 10 sources. Flag REMOVAL is Stream 2.
- [ ] `services/provider_schemas.py:163, 393` — read/write `plugins` instead of `job_sources`.
- [ ] `web/settings.py:250` — read `plugins` instead of `job_sources`.
- [ ] `credentials.py:149, 161, 231, 299, 334, 403` — load/save native shape. (The in-memory auto-migration in `load_providers()` was written in Stream 0; Stream 1 only changes the read/save shape at these call sites.)
- [ ] `job_sources/auto_register.py:131, 133, 138, 155, 161` — update or mark dead (Phase C deletes the file; if the rewrite is trivial, do it; if not, leave as legacy and let Phase C delete).
- [ ] `job_sources/aggregator_provider.py:355–358` — `_extract_plugin_credentials` no longer needed once the on-disk shape matches `plugins` directly; either delete the helper or repoint it at `providers["plugins"]`.
- [ ] `config/providers.example.json` — rewritten to native shape so fresh installs match.
- [ ] `.env.dev.example`, `.env.prod.example` — audit for any references to `job_sources` (likely none, but confirm).
- [ ] `scripts/migrate_providers_json.py` — present on `main` (Resolved 2026-05-06: `git ls-tree HEAD -- scripts/migrate_providers_json.py` returns a blob). Verify behavior; update if needed for native-shape output.
- [ ] `scripts/deploy-remote-linux.sh` — add preflight migration step + abort-on-failure per predecessor plan §2 Phase B / Risk #2.
- [ ] `tests/test_migrate_providers_json.py` — present on `main` (Resolved 2026-05-06: `git ls-tree HEAD -- tests/test_migrate_providers_json.py` returns a blob). Verify coverage; extend if needed.

**Stream 1 acceptance criteria:**

- [ ] All 9 sources route through `JobAggregatorProvider` when the flag is set to all 10 sources; live smoke run captured in PR description.
- [ ] `tests/fixtures/db_source_strings.json` refreshed to include all 10 keys (currently only `["adzuna", "arbeitnow", "jobicy", "remoteok", "remotive"]` — missing 5 keys). `tests/test_source_keys_round_trip.py` passes against the refreshed fixture.
- [ ] Existing `tests/test_aggregator_provider.py` extended with translation test cases per source (9 new or updated parametrized cases).
- [ ] Stream 0's auto-migration is exercised by Stream 1 — at least one Stream 1 acceptance test must load a legacy-shape fixture and confirm Stream 1's readers see the native shape (proving Stream 0's safety net actually catches the case Stream 1 depends on it for).
- [ ] `grep -rn 'providers\["job_sources"\]\|providers.get("job_sources")\|"job_sources"' --include='*.py' .` returns empty.
- [ ] Per-plugin `enabled` extension key preserved through migration (Decision Log #9). A unit test asserts `enabled: false` on a keyed source excludes it from `make_clients()`'s output.
- [ ] Adzuna env-var injection (`ADZUNA_APP_ID` / `ADZUNA_APP_KEY`) still works against native shape — covered by an extension to `tests/test_ingest_feature_flag.py` or a new env-injection-specific test.
- [ ] `scripts/deploy-remote-linux.sh` preflight tested against a staging copy of `providers.json` (legacy-shape input → native-shape output + `.bak` left behind; failure-mode: corrupt input → script exits non-zero, deploy aborts).
- [ ] Settings UI manual smoke: load `/settings`, verify all 10 sources render with their credential fields. (Predecessor plan Risk #1 — UI rewrite is Phase C, but Phase B's underlying dict-key rename must not break rendering.)

### Stream 2 — flag removal + `LegacyInTreeProvider` deletion (PR #X2)

This is the predecessor plan's Decision Log #11 + #12 closeout. Stream 2 is mostly deletion plus one small rewrite of `_build_source_clients()` and one replacement test. The replacement test (`tests/test_ingest_routes_all_sources_through_aggregator.py`) must explicitly enumerate which behaviors from the deleted `tests/test_ingest_feature_flag.py` carry forward and which are intentionally dropped — do not leave the assertion surface implicit.

- [ ] `ingest.py:47–57` — delete the `_JOB_AGGREGATOR_SOURCES_ENV` constant block and its docstring comment.
- [ ] `ingest.py:1099–1182` — `_build_source_clients()` collapsed: now always returns `JobAggregatorProvider(...).make_clients(...)` over all 10 sources. Drop the `LegacyInTreeProvider` branch entirely.
- [ ] `job_sources/legacy_provider.py` — deleted (`git rm`).
- [ ] `tests/test_ingest_feature_flag.py` — deleted (replaced by a smaller `tests/test_ingest_routes_all_sources_through_aggregator.py` that asserts the single-provider behavior).
- [ ] `tests/test_aggregator_provider.py:527` — comment referencing `JOB_AGGREGATOR_SOURCES=arbeitnow` updated or deleted.
- [ ] `CLAUDE.md:22–27` — the `# Phase A feature flag` block removed; replace with a one-line "Phase B complete" historical note OR delete entirely (recommend delete; predecessor plan in `docs/superpowers/plans/` carries the history).
- [ ] `scripts/verify_phase_a_pre_b.ps1` — either delete (its purpose is satisfied) or replace with `scripts/verify_phase_b.ps1`. Recommend delete; the verify script's job is one-shot pre-Phase-B sanity check, and Phase A is now history. See §5 verification severable item.
- [ ] `tests/test_verify_phase_a_pre_b_script.py` — delete alongside the script.
- [ ] `docs/superpowers/plans/2026-04-27-job-aggregator-integration.md` — leave intact (historical record; predecessor plan rule).

**Stream 2 acceptance criteria:**

- [ ] `grep -rn JOB_AGGREGATOR_SOURCES` over the repo returns empty.
- [ ] `git ls-tree HEAD -- job_sources/legacy_provider.py` returns empty.
- [ ] All 2192+ tests pass.
- [ ] Live ingest smoke with the env var **unset** (and never set) returns the same 10 sources as the Stream 1 smoke did with the env var set — proving the flag-driven path and the unified path behave identically.

---

## 4. Feature-flag removal — explicit checklist

Consolidates the deletions for cross-reference at PR-review time. All under Stream 2 unless noted.

- [ ] **`ingest.py`** — `_JOB_AGGREGATOR_SOURCES_ENV` constant + the routing branch in `_build_source_clients()` (lines 47–57 and 1129–1181 per current main).
- [ ] **`job_sources/legacy_provider.py`** — file deleted.
- [ ] **`job_sources/aggregator_provider.py`** — docstring at lines 261–264 ("Phase A: …routed through this provider when `JOB_AGGREGATOR_SOURCES=arbeitnow` is set…") updated to reflect Phase B unified routing. Lines 348–351 (the `JOB_AGGREGATOR_SOURCES` env-var docstring reference) updated.
- [ ] **`CLAUDE.md`** — the Phase A feature-flag block at lines 22–27 deleted.
- [ ] **`tests/test_ingest_feature_flag.py`** — file deleted; replaced by smaller unified-routing test.
- [ ] **`tests/test_aggregator_provider.py:527`** — comment updated.
- [ ] **`tests/test_verify_phase_a_pre_b_script.py`** — file deleted.
- [ ] **`scripts/verify_phase_a_pre_b.ps1`** — file deleted (severable; can defer to Phase D docs PR if review prefers smaller Stream 2).
- [ ] **`.env.dev.example`, `.env.prod.example`** — confirmed-no-references audit. The grep at the start of Stream 2 should turn up nothing in these files; if it does, remove.

---

## 5. Verification plan

### Per-stream verification

**Stream 0 (auto-migration):**

0.5. **Step 0.5 — Capture legacy baseline.** On a fresh checkout of `main` at the commit Stream 0 will branch from, run `python ingest.py --hours 168 -v` against the dev DB. Capture stdout to `docs/baselines/2026-05-06-phase-b-legacy-baseline.log` (use the actual capture date in the filename, not always 2026-05-06). This log is the **single source of truth for "the legacy baseline"** referenced throughout this plan. Commit the file as part of Stream 0's PR so the baseline is on `main` (via the feature branch merge) before any routing change exists.

    If a usable baseline already exists from PR #364's smoke run and was committed to `docs/baselines/`, Stream 0 may reuse it. Verify with `git ls-tree HEAD -- docs/baselines/` before assuming it exists. If no committed baseline is found, capture a fresh one per the steps above. Whichever path is chosen, the exact file path must be named explicitly and verifiable with `git ls-tree HEAD --`.

1. `pytest tests/test_credentials_native_shape.py` green (all six test cases pass).
2. Load each of the five edge-case fixtures manually and verify behavior matches the §3 Stream 0 spec table.

**Stream 1 (all sources + shape migration):**
0. **Refresh `tests/fixtures/db_source_strings.json`** to include all 10 distinct `source` strings the project tracks. Current fixture has 5 entries (`adzuna`, `arbeitnow`, `jobicy`, `remoteok`, `remotive`); missing 5 (`himalayas`, `jooble`, `jsearch`, `the_muse`, `usajobs`). Refresh from the dev DB: `psql "$env:DATABASE_URL" -c "SELECT DISTINCT source FROM jobs ORDER BY source"` and write the JSON. If the dev DB doesn't yet have rows for the missing sources, fall back to the canonical list from each plugin's `SOURCE` constant in the `job-aggregator` package.
1. `pytest tests/test_aggregator_provider.py tests/test_source_keys_round_trip.py tests/test_credentials_native_shape.py` green.
2. `$env:JOB_AGGREGATOR_SOURCES = "arbeitnow,himalayas,jobicy,remoteok,remotive,adzuna,jooble,jsearch,the_muse,usajobs"; python ingest.py --hours 168 -v` — capture stdout to a log committed to `docs/baselines/2026-05-XX-phase-b-stream1-smoke.log`. Acceptance: 0 `LISTING FAILED`, 0 `None:` source buckets, JobAggregatorProvider marker present.
3. Per-source row count ≥ `docs/baselines/2026-05-06-phase-b-legacy-baseline.log` OR zero-row sources documented with diagnosis link (see §5 Severable item — zero-row diagnosis).
4. Settings UI manual smoke: load `/settings`, verify all 10 sources render with their credential fields.
5. Local `python scripts/migrate_providers_json.py config-dev/providers.json` runs cleanly; `.bak` written; idempotent re-run is a no-op.
6. `scripts/deploy-remote-linux.sh` dry-run against a staging copy of legacy-shape `providers.json`: migrate succeeds, `.bak` left, deploy continues.

**Stream 2 (flag removal):**
1. `pytest` green.
2. Live `python ingest.py --hours 168 -v` (no env var set) returns the same 10-source result set as Stream 1's flagged run. Diff the two logs against `docs/baselines/2026-05-06-phase-b-legacy-baseline.log`; only differences should be timestamps and row counts within tolerance.
3. `grep -rn JOB_AGGREGATOR_SOURCES` returns empty.

### Severable item — verify-script tightening

The Phase A diagnosis flagged that `scripts/verify_phase_a_pre_b.ps1` Step 3 is marker-only (greps for the `JobAggregatorProvider` log line) and does not assert source-set correctness, zero LISTING FAILED, or positive row delta. Tightening the script to assert these is not a Phase B blocker: the script's job is one-shot pre-Phase-B sanity, and Stream 2 deletes it.

**Recommendation:** do not tighten the verify script. Delete it in Stream 2. The replacement validation is each stream's smoke-run log capture (committed to `docs/baselines/`) per the per-stream verification above.

If reviewer prefers to keep some form of the script for Phase C → Phase D, file a follow-up issue to write a `scripts/verify_phase_b.ps1` rather than retrofit the Phase A one. Out of scope for #347.

### Severable item — zero-row diagnosis

The 5 zero-row sources from PR #364's smoke (`himalayas`, `jooble`, `jsearch`, `the_muse`, `usajobs`) need diagnosis but **the diagnosis is not a #347 deliverable**. Phase B's job is to migrate them to the new routing path; if they returned 0 rows on the legacy path AND return 0 rows on the aggregator path, that is a pre-existing plugin-level concern, not a Phase B regression. Routing parity with the legacy baseline is the bar, not absolute row counts. `LISTING FAILED` and `None:` source buckets must be 0.

**Process:** at each stream's smoke run, if a source returns 0 rows, file a separate issue (e.g. `bug(jsearch): 0 rows on --hours 168 dev smoke`) against `cbeaulieu-gt/job-matcher-pr` and link it from the PR description as "out of scope; tracked separately." Phase B merges anyway as long as the routing change itself is neutral or positive vs. the legacy baseline.

---

## 6. Rollback plan

The three-stream split makes rollback granular. In all cases, revert the offending PR(s) with `git revert -m 1 <merge-commit>` on the feature branch, push, and re-deploy. Post-deploy `providers.json` may need restoring from a `.bak` (Stream 1 only).

| Failure mode discovered post-merge | Cheapest rollback |
|---|---|
| Stream 0 auto-migration regression discovered post-merge | `git revert` Stream 0 alone. Stream 1 cannot have merged yet (linear dependency). Behavior reverts to today's state: `credentials.load_providers()` does a plain `json.load()` with no shape detection. No data loss — no disk writes occur in Stream 0. |
| Stream 1 keyless source regresses | Revert Stream 1 PR. Stream 2 cannot have merged yet (linear dependency). No `providers.json` change remains if the `.bak` is restored. |
| Stream 1 credential-shape bug breaks an unrelated reader (settings UI, Adzuna env injection) | Revert Stream 1 PR. Restore `config/providers.json` (and prod's `/opt/job-matcher-pr/config/providers.json`) from the `.bak` file written by `scripts/migrate_providers_json.py`. Stream 2 cannot have merged. |
| Stream 1 keyed source regresses (one specific source's credential translation is wrong) | Two options: (a) revert Stream 1 entirely (see above), (b) hot-fix forward — file an issue, push a one-line fix on a fixup branch, merge. Prefer (b) if the issue is local to one source; prefer (a) if the shape rewrite itself is broken. |
| Stream 2 flag removal exposes a hidden flag-dependent code path | Revert Stream 2 PR. The flag and `LegacyInTreeProvider` come back. Re-investigate before re-attempting. Stream 1 stays merged — the unified-routing path under the env var continues to work, just driven by flag instead of unconditional. |
| Whole-Phase-B regression discovered after Stream 2 merge | Revert both stream PRs in reverse order (Stream 2 → Stream 1). Restore `providers.json` from `.bak`. Recovery time ~30 minutes. |

Rollback target: the merge commit's first parent on `main` (visible in `git log`). No special pre-merge tag is needed.

---

## 7. Risks and open questions

### Risk B-1 — 5 sources return 0 rows on the legacy path (known)

`himalayas`, `jooble`, `jsearch`, `the_muse`, `usajobs` returned 0 rows in PR #364's live smoke. This may indicate plugin-level bugs (in `job_aggregator` or its upstream dependency on this repo's existing code), expired test credentials, or upstream API changes. **Severity:** Medium. **Mitigation:** §5 severable diagnosis process — file separate issues per source rather than block #347. **Open question:** are the dev-stack credentials for `jsearch` / `usajobs` / `jooble` still valid? Verify before Stream 1's keyed-source work by loading `/settings` and checking the configured-vs-blank state of each.

### Risk B-2 — `providers.json` shape migration breaks running prod stack

If `scripts/deploy-remote-linux.sh`'s preflight does not run (e.g. someone deploys via `docker compose up -d` on the server directly), the running container loads a legacy-shape `providers.json` against a Stream-1 codebase that only reads `plugins` keys. Result: every source has empty credentials → keyed sources silently disabled → ingest run produces 0 rows. **Severity:** High. **Mitigation:** Stream 0 (which merges before Stream 1 exists) writes the in-memory auto-migration into `credentials.load_providers()`: the function detects the legacy `job_sources` shape and rewrites it in-memory before returning, without writing back to disk. Because Stream 0 is its own PR that lands first, the safety net is already active when Stream 1's shape rewrite ships — a regression bisect can distinguish "the safety net itself is broken" (Stream 0 blame) from "the shape rewrite missed a reader" (Stream 1 blame). The deploy script's preflight is defense-in-depth, not the primary safety mechanism.

### Risk B-3 — `tests/fixtures/db_source_strings.json` is incomplete

The fixture currently lists only 5 source keys (`adzuna`, `arbeitnow`, `jobicy`, `remoteok`, `remotive`); the round-trip test in `tests/test_source_keys_round_trip.py` therefore does NOT actually validate the 5 sources Phase B is most worried about (`himalayas`, `jooble`, `jsearch`, `the_muse`, `usajobs`). **Severity:** Medium. **Mitigation:** §5 verification step 0 — refresh the fixture before Stream 1 merges. This is cheap and high-value.

### Risk B-4 — Settings UI rendering breaks when `providers.json` shape changes

`web/settings.py:250` reads `providers["job_sources"]`. Stream 1's rewrite to `plugins` is mechanical, but the template (`templates/settings.html`) consumes the rendered context — a missed reference (e.g. an inline Jinja `{{ providers.job_sources.adzuna }}`) would produce a silently empty render. **Severity:** Low. **Mitigation:** Stream 1 manual smoke test (§5 step 4); add a `tests/test_settings_renders_all_sources.py` that boots the Flask app with native-shape providers and asserts the page rendering doesn't fail.

### Risk B-5 — removed by stream collapse

The original Risk B-5 concerned the env-var flag value going stale between Stream 1 and Stream 2 in the prior three-stream design. With the two-stream collapse, Stream 1 updates the flag default to all 10 sources, so the new routing path is exercised immediately after Stream 1 merges. This risk no longer applies.

### Open questions

1. **Is `jobicy` keyless or keyed?** Resolved 2026-05-06: keyless. `config/providers.example.json` has no `api_key` field for jobicy. Placed in the keyless group of Stream 1.
2. **Is `scripts/migrate_providers_json.py` already committed in `main`?** Resolved 2026-05-06: present on `main` (`git ls-tree HEAD -- scripts/migrate_providers_json.py` returns a blob). Verify behavior against the native-shape spec before Stream 1 merges; update in place if needed.
3. **Is `tests/test_migrate_providers_json.py` already committed?** Resolved 2026-05-06: present on `main` (`git ls-tree HEAD -- tests/test_migrate_providers_json.py` returns a blob). Verify coverage; extend if needed.
4. **Are dev-stack credentials for the 5 keyed zero-row sources valid?** Open — legitimate runtime question. Affects diagnosis of Risk B-1. Verify before Stream 1's keyed-source smoke run by loading `/settings` and checking configured-vs-blank state for `jooble`, `jsearch`, `the_muse`, `usajobs`.
5. **Does the in-memory auto-migration safety net in `credentials.load_providers()` exist on `main` today?** Resolved 2026-05-06: NOT present on `main`. `credentials.py:241–254` does a plain `json.load(fh)` with no shape detection. Stream 0 must write it; see Stream 0 file-edit checklist and `tests/test_credentials_native_shape.py`.

---

## 8. PR body templates

### Final primary PR body

```
Phase B job-aggregator migration: route remaining 9 sources through
JobAggregatorProvider, migrate providers.json to native shape, remove
JOB_AGGREGATOR_SOURCES feature flag.

Streams (sequential PRs merged into this feature branch):
- Stream 0 (#X0): credentials.py in-memory auto-migration safety net
- Stream 1 (#X1): all 9 sources + on-disk shape migration
- Stream 2 (#X2): JOB_AGGREGATOR_SOURCES + LegacyInTreeProvider deletion

Verification: docs/baselines/2026-05-XX-phase-b-{stream1,stream2}-smoke.log

Closes #347

🤖 Generated by Claude Code on behalf of @cbeaulieu-gt
```

**CLAUDE.md compliance notes:**
- `Closes #347` is plain text, no backticks (closing-keyword parser rule).
- Streams 0, 1, and 2 each get their own PR with a short body referencing the primary PR; stream PRs do NOT carry `Closes #347` (only the primary one does, since merging the streams into the feature branch doesn't close the issue — only the feature-branch merge to `main` does).

---

*Plan written 2026-05-06 by Claude Code (project-planner sub-agent) on behalf of @cbeaulieu-gt. No code changes have been made; no sub-issues filed; no commits.*
