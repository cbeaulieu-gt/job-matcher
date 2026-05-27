# Repo Consolidation Plan — `glitchwerks/job-matcher-pr` → `glitchwerks/job-matcher`

## Context

Tracks issue **#375**: consolidate the private canonical repo (`glitchwerks/job-matcher-pr`)
into the public repo (`glitchwerks/job-matcher`) and archive the private one.

**Topology at planning time** (router recon, 2026-05-27):

- `glitchwerks/job-matcher-pr` — PRIVATE, canonical. 98 commits ahead of public main;
  diff +16175 / -3723 across 97 files. Major work landed: services/web refactor
  (Phases 0–6, issues #313–#335), rubric eval comparison (#274), Phase A aggregator
  (PRs #346, #351), Stream 0 credentials auto-migration (PRs #366, #367),
  deploy-sync fix (PR #373 / issue #374).
- `glitchwerks/job-matcher` — PUBLIC. Originally `cbeaulieu-gt/job-matcher`; transferred
  into the `glitchwerks` org on 2026-05-27 via
  `gh api repos/cbeaulieu-gt/job-matcher/transfer -X POST -f new_owner=glitchwerks`.
  Verified by `gh repo view glitchwerks/job-matcher --json owner,visibility` →
  `{"owner":{"login":"glitchwerks"},"visibility":"PUBLIC"}`. GitHub auto-creates a
  permanent redirect from the old `cbeaulieu-gt/job-matcher` URL.
  Transfer documented in glitchwerks/job-matcher-pr#375 comment-4558806027.
  3 commits ahead of merge base `f74e6d5`; all three are logical duplicates of fixes
  already on private under different SHAs / PR numbers (public #352 / #354 ≈ private
  #356 / #369). A force push will not lose net content.
- Merge base: `f74e6d5`.
- Local workstation clone: `I:\career\job-matcher-pr`. `origin` = private; a temporary
  `public` remote (`https://github.com/glitchwerks/job-matcher.git`) was added during
  recon and is removed in Phase 8.

**Direction (already chosen by user, do not revisit):** force-push private main onto
public main; archive `glitchwerks/job-matcher-pr` after the new public main is verified
and a release is tagged.

**Same-org simplification.** Because the destination is now `glitchwerks/job-matcher`
(same org as the source), several pre-flight concerns from the original plan are resolved:
- Cross-owner reusable workflow access (formerly Phase 1 step 1) — no longer a concern;
  the public repo is in the same org.
- GHCR namespace — stays `glitchwerks`; the existing `glitchwerks/job-matcher-pr` image
  proves the org can push there.
- Org-level secrets (`APP_ID`, `APP_PRIVATE_KEY`) — already inherited by same-org repos;
  now a quick sanity check rather than a blocker.
- All GitHub/GHCR ref rewrites drop only the `-pr` suffix; the `glitchwerks` org prefix
  is unchanged.

**Wiki status** (verified 2026-05-27):

Both repos have their wikis enabled (`hasWikiEnabled: true`, confirmed via
`gh repo view glitchwerks/job-matcher-pr --json hasWikiEnabled` and
`gh repo view glitchwerks/job-matcher --json hasWikiEnabled`). Each wiki contains
the same 9 files: `Configuring-Your-Profile.md`, `Getting-Started.md`, `Home.md`,
`Job-Sources.md`, `LLM-Provider-Setup.md`, `Plugin-Development.md`,
`Troubleshooting.md`, `Tuning-Your-Search.md`, and `Understanding-Scores.md`.

Private wiki HEAD: `2d29ea2` (`git -C .tmp/private-wiki log -1`).
Public wiki HEAD: `69e62eb` (`git -C .tmp/public-wiki log -1`).

The public wiki history is exactly the private wiki history plus one additional
commit on top: `69e62eb chore(mirror): rewrite private-repo URLs for public wiki`.
This is the URL-rewrite step that `publish.yml` ran on its last successful
execution — every `glitchwerks/job-matcher-pr` link was already rewritten to
`glitchwerks/job-matcher` in the public wiki. Private wiki HEAD `2d29ea2` is
fully reflected in the public wiki history; there are no unmirrored private-wiki
commits.

**Conclusion:** the wiki is already migrated. No new wiki action is required by
this consolidation. After Phase 7 archives the private repo, the private wiki
remains accessible read-only at `glitchwerks/job-matcher-pr/wiki/*`; the public
wiki at `glitchwerks/job-matcher/wiki/*` is the canonical home for ongoing edits.

**Citations for self-references being rewritten** (see Phase 2 for the rewrite list):

- `.github/workflows/docker-smoke.yml:39` — `tags: ghcr.io/glitchwerks/job-matcher-pr:latest`
- `.github/workflows/docker-smoke.yml:48` — `docker run --rm ghcr.io/glitchwerks/job-matcher-pr:latest`
- `.github/workflows/publish.yml:1-100` — the entire private→public mirror workflow;
  obsolete after cutover.
- `.github/workflows/deploy.yml:51,62,63,253,254,265,266,267` — image refs of the form
  `ghcr.io/${{ github.repository_owner }}/job-matcher-pr:<tag>`; the org template stays,
  only the `-pr` suffix is dropped from the image name.
- `docker-compose.dev.yml:40` — `image: ghcr.io/glitchwerks/job-matcher-pr:${APP_VERSION:-latest}`
- `docker-compose.prod.yml:29` — `image: ghcr.io/glitchwerks/job-matcher-pr:latest`
  (this is what live prod pulls).
- `README.md:443` — `sudo git clone https://github.com/glitchwerks/job-matcher-pr.git /opt/job-matcher-pr`
- `docs/DESIGN.md:597` — image ref in `web` container description.
- `docs/DESIGN.md:621` — image ref in Image Publishing section.
- `docs/DOCKER.md:45` — `sudo git clone https://github.com/glitchwerks/job-matcher-pr.git /opt/job-matcher-pr`
- `docs/DOCKER.md:98,103,268,305` — `ghcr.io/.../job-matcher-pr:<tag>` doc refs.

**Citations for refs that stay as-is** (shared workflows repo, NOT the repo being archived):

- `.github/workflows/claude-pr-review.yml:9` — `uses: glitchwerks/github-actions/.github/workflows/claude-pr-review.yml@v2`
- `.github/workflows/lint-failure.yml:54` — same `glitchwerks/github-actions` shared workflows repo.
- `.github/workflows/tag-claude.yml:11` — same.

These are reusable workflows hosted in a separate `glitchwerks/github-actions` repo
that is **not** being archived. They remain on the same org boundary and require no
access changes.

---

## Phase 1 — Pre-flight verification

**Goal:** prove the new public-side environment can take over before any destructive
action is taken.

**Entry criteria:** none — this phase is read-only.

**Tasks:**

1. **Confirm GHCR push permission for `glitchwerks` namespace.** The `deploy-prod`
   workflow needs to push to `ghcr.io/glitchwerks/job-matcher`. Because the existing
   `glitchwerks/job-matcher-pr` image is already in this namespace and the workflows
   operate under the same org, GHCR perms are expected to work without any policy
   change. Verify the GHA `GITHUB_TOKEN` has `packages: write` in the public repo's
   workflow definition, and that the new package name `job-matcher` (without `-pr`) is
   not blocked by any namespace policy. A successful deploy run after Phase 2 merges is
   sufficient confirmation.
2. **Note GitHub Releases on the private repo.** The tag refs (`v1.0.0`, `v1.1.0`,
   `v1.2.0`, `v1.2.1`) already exist on the public repo with identical SHAs and
   **will survive the force push** — all four tagged commits are ancestors of
   `origin/main`. What does not survive are the GitHub Releases (the notes and asset
   wrappers around each tag): those remain visible only on the archived private repo
   and are accepted as historical-only. No backfill of Release notes onto the public
   Releases tab is planned. Run `gh release list --repo glitchwerks/job-matcher-pr`
   and save the output for your own records; no action is required from it.
3. **Confirm secrets parity.** Any secret the workflows on private depend on
   (anything referenced as `${{ secrets.* }}` in `.github/workflows/`) must also
   exist on `glitchwerks/job-matcher` before Phase 4, or the first CI run after
   cutover will fail. Org-level secrets (`APP_ID`, `APP_PRIVATE_KEY`) are already
   inherited by same-org repos, so the main concern is repo-level secrets. Enumerate:
   `gh secret list --repo glitchwerks/job-matcher-pr` and
   `gh secret list --repo glitchwerks/job-matcher`, diff, copy any missing repo-level
   secrets to public. `PUBLIC_REPO_PAT` (consumed only by the now-obsolete
   `publish.yml`) does not need to migrate.

**Exit criteria:**
- GHCR namespace write confirmed (or noted as deferred to post-Phase-2 deploy run).
- Secret diff resolved.

**Risk if skipped:** the first CI run fails due to a missing repo-level secret.

---

## Phase 2 — Rewrite self-references on private's main

**Goal:** every file that names `glitchwerks/job-matcher-pr` (GitHub or GHCR ref) is
updated to `glitchwerks/job-matcher` (drop the `-pr` suffix) *before* the history is
pushed to public. The `glitchwerks` org prefix is unchanged throughout.
Reusable-workflow refs to `glitchwerks/github-actions` stay untouched.

**Entry criteria:** Phase 1 complete.

**Approach:** do the rewrite as a single dedicated commit on a short-lived branch
off `origin/main`, merge that branch into `main` via PR on the private repo, and
then push to public in Phase 4. Reasons:
- Keeps the rewrite reviewable (one commit, clean diff).
- Goes through normal CI on the private repo before the force push.
- Avoids history surgery — the rewrite becomes a normal commit at the tip of main.

**Branch name suggestion:** `repo-consolidation-refs-375`.

**Edits required** (citations in Context section):

| File | Line(s) | From | To |
|---|---|---|---|
| `.github/workflows/docker-smoke.yml` | 39, 48 | `ghcr.io/glitchwerks/job-matcher-pr` | `ghcr.io/glitchwerks/job-matcher` |
| `.github/workflows/publish.yml` | 1–100 | (entire file) | **DELETE the file** — the private→public mirror is obsolete once public is the canonical repo. Wiki mirror is no longer needed because the public wiki is already in sync with private's HEAD plus the URL-rewrite step (verified — see "Wiki status" in the Context section); deleting `publish.yml` does not orphan wiki content. |
| `.github/workflows/deploy.yml` | 51, 62, 63, 253, 254, 265, 266, 267 | `ghcr.io/${{ github.repository_owner }}/job-matcher-pr:<tag>` | `ghcr.io/${{ github.repository_owner }}/job-matcher:<tag>` — drop `-pr` from the image name suffix only; the `${{ github.repository_owner }}` template stays and resolves to `glitchwerks` post-cutover. |
| `docker-compose.dev.yml` | 40 | `ghcr.io/glitchwerks/job-matcher-pr:${APP_VERSION:-latest}` | `ghcr.io/glitchwerks/job-matcher:${APP_VERSION:-latest}` |
| `docker-compose.prod.yml` | 29 | `ghcr.io/glitchwerks/job-matcher-pr:latest` | `ghcr.io/glitchwerks/job-matcher:latest` |
| `README.md` | 443 | `https://github.com/glitchwerks/job-matcher-pr.git` | `https://github.com/glitchwerks/job-matcher.git` |
| `docs/DESIGN.md` | 597 | `ghcr.io/glitchwerks/job-matcher-pr` | `ghcr.io/glitchwerks/job-matcher` |
| `docs/DESIGN.md` | 621 | `ghcr.io/glitchwerks/job-matcher-pr` | `ghcr.io/glitchwerks/job-matcher` |
| `docs/DOCKER.md` | 45 | `https://github.com/glitchwerks/job-matcher-pr.git` | `https://github.com/glitchwerks/job-matcher.git` |
| `docs/DOCKER.md` | 98, 103, 268, 305 | `ghcr.io/.../job-matcher-pr:<tag>` | `ghcr.io/.../job-matcher:<tag>` — drop `-pr` from image name. |

**Verification before commit:**

```powershell
# Should produce no hits outside migration docs and lock files.
Select-String -Path . -Pattern 'job-matcher-pr' -Recurse `
  | Where-Object { $_.Path -notmatch '(REPO_CONSOLIDATION_PLAN|CHANGELOG|\.lock|node_modules)' }
# Reusable-workflow refs should still be present and unchanged.
Select-String -Path . -Pattern 'glitchwerks/github-actions' -Recurse
```

The first command's only remaining hits should be in lock files, historical CHANGELOGs,
or docs describing the migration itself (including this plan file). If it surfaces a
code or workflow file outside that list, stop and add it to the rewrite table.

**Local-path strings that stay:** `/opt/job-matcher-pr`, the Docker Compose project names
`job-matcher-pr-dev` / `job-matcher-pr-prod`, and the workstation path
`I:\career\job-matcher-pr` are **VM/local-filesystem identifiers**, not GitHub refs.
Renaming them is a separate, larger change (touches `scripts/deploy-remote-linux.sh`,
`scripts/docker-setup.sh`, the prod server's directory layout, and every reference in
the CLAUDE.md). Out of scope for #375 — log a follow-up issue if desired but do not
bundle.

**Exit criteria:**
- Branch merged to private `main`.
- Private `docker-smoke.yml` CI passes on the new commit (this exercises the new GHCR
  image tag in a build-only context — it does not push).
- `publish.yml` is deleted; no scheduled run will fire after deletion.

---

## Phase 3 — GHCR image cutover

**Goal:** push a `ghcr.io/glitchwerks/job-matcher:latest` (and a versioned tag) image
**before** the prod VM is repointed in Phase 5. Without this, the moment
`docker-compose.prod.yml` is updated on the VM and the stack is restarted, the pull
will 404 and prod will go down.

**Entry criteria:** Phase 2 merged to private main.

**Ordering rationale:** the deploy workflow that publishes the image already exists in
`.github/workflows/` and is wired to push on merge to main (the team's normal flow).
By rewriting the image name in Phase 2 and merging there, the next normal CI run after
that merge produces the first `ghcr.io/glitchwerks/job-matcher` image. So:

- If the deploy workflow runs on merge to `main` of the private repo, Phase 2's merge
  is already producing the new image — verify the image exists in the `glitchwerks`
  GHCR namespace before continuing.
- If the deploy workflow runs only on the public repo's main, then Phase 3 cannot
  complete until after Phase 4, and Phase 5 cannot start until Phase 3. State this
  dependency explicitly in your tracking and adjust ordering: 1 → 2 → 4 → 3 → 5.

**Tasks:**
1. **Verify the image exists.**
   `gh api /orgs/glitchwerks/packages/container/job-matcher/versions`
   or check the Packages tab on the public repo. Look for `:latest` and at least one
   versioned tag.
2. **Pull-test from the workstation** before touching prod:
   `docker pull ghcr.io/glitchwerks/job-matcher:latest`. Confirm the digest.
3. **Cross-check digest against the captured rollback anchor.** If the same Dockerfile
   built two different digests across workflows, investigate before continuing.

**Exit criteria:** the new image is pullable from an authenticated client AND the
digest is recorded for Phase 5 verification.

---

## Phase 4 — History push

**Goal:** force-push private `main` → public `main` so the public repo becomes the
canonical history.

**Entry criteria:**
- Phase 1, 2 complete.
- Phase 3 complete (image exists) OR explicit acceptance that Phase 5 is blocked
  until after this phase produces the first image build on public.
- **Note:** Phase 6 (issue/PR migration via `gh api`) does not need to precede the
  force push — private issues remain accessible via the web UI until Phase 7 flips the
  archive bit. Phase 6 just needs to complete before Phase 7.

**Tasks:**

1. From the workstation clone at `I:\career\job-matcher-pr`:
   ```powershell
   git fetch origin
   git fetch public
   git checkout main
   git reset --hard origin/main     # ensure local main matches the post-Phase-2 tip
   git push public main --force
   ```
   The `public` remote should already point at `https://github.com/glitchwerks/job-matcher.git`
   (added during recon; verified in Phase 8 cleanup).

   **Tag push is not required.** Public and private already share identical tag SHAs
   (`v1.0.0`, `v1.1.0`, `v1.2.0`, `v1.2.1`), verified by comparing
   `git ls-remote --tags origin` against `git ls-remote --tags public` and confirming
   all four tagged commits are ancestors of `origin/main` via
   `git merge-base --is-ancestor <tag-sha> origin/main`. Because the force push
   preserves every commit that these tags already point at, the existing public tag
   refs remain valid and reachable from the new main — no rewrite occurs, no
   `--force` flag is needed for tags. After the push, re-verify with:
   ```powershell
   git ls-remote --tags public
   ```
   and confirm all four tag SHAs still match `git ls-remote --tags origin`.
   The Phase-4 consolidation release (step 2 below) is the durable public anchor
   for the cutover point itself.
2. **Create a new release on public** marking the consolidation point. Suggested:
   `v<next>` with body referencing #375. This is the durable rollback anchor for
   future "what was public main before consolidation" questions.
3. **Disable / archive any GHA workflows on public that don't belong post-cutover**
   — most notably, if the public repo had its own `publish.yml` mirror or a stale
   `deploy-*.yml`, remove it now.

**Exit criteria:**
- `git ls-remote public main` returns the same SHA as `git rev-parse origin/main`.
- New release tagged on public.
- Public repo CI passes on the post-push main.

---

## Phase 5 — Live deployment cutover

**Goal:** roll the prod VM onto the new compose file (which references the new image
name) without unplanned downtime.

**Entry criteria:**
- Phase 3 verified — `ghcr.io/glitchwerks/job-matcher:latest` is pullable.
- Phase 4 complete.

**Tasks:**

1. **Push the new compose + env config** with `scripts/deploy-remote-linux.sh`. This
   script (per the project CLAUDE.md "Deployment" section) pushes compose files,
   scripts, config examples, and live `.env.prod` / `.env.dev` with overwrite
   confirmation. Confirm in the prompt that it overwrites the compose files —
   that's the point of this run.
2. **On the prod VM:**
   ```bash
   cd /opt/job-matcher-pr
   docker compose -p job-matcher-pr-prod --env-file .env.prod -f docker-compose.prod.yml pull web
   docker compose -p job-matcher-pr-prod --env-file .env.prod -f docker-compose.prod.yml up -d
   ```
3. **Verify:**
   - `docker compose -p job-matcher-pr-prod ps` shows `web` as `running (healthy)`.
   - `docker inspect --format '{{index .RepoDigests 0}}' ghcr.io/glitchwerks/job-matcher:latest`
     matches the digest recorded in Phase 3.
   - HTTP smoke: `curl -sS -o /dev/null -w '%{http_code}\n' http://localhost:5001/feed`
     returns `200`.
   - Tail logs for 5 minutes: `docker compose -p job-matcher-pr-prod logs -f --since 5m web`
     — no `ImagePullBackOff`, no startup exceptions.

**Rollback:** If cutover breaks something, redeploy by editing `docker-compose.prod.yml` on the VM back to the prior image reference and `docker compose ... up -d`. The user has accepted that there is no preserved digest anchor — `ghcr.io/glitchwerks/job-matcher-pr:latest` remains pullable from the archived repo as long as it hasn't been deleted, and rebuild-from-source is an acceptable recovery if the image is gone. Prod has no external consumers; downtime during recovery is not a concern.

**Exit criteria:** prod healthy, smoke passes, logs clean.

---

## Phase 6 — Issue / PR history migration

**Goal:** migrate closed issues and PRs (with their comments) from `glitchwerks/job-matcher-pr`
to `glitchwerks/job-matcher` via `gh api` before the private repo is archived.
Open issues do not need to migrate — there are very few, and issue #375 itself stays
on the private repo as the historical record of the migration and is closed there when
the work completes.

**Entry criteria:** Phase 4 complete (public repo exists in final state before new
issues are created against it).

**Known fidelity limitations** (accept before starting):
- Migrated issues and PRs will appear on the public repo as new issues, authored by
  the migration runner (your GitHub identity) with the migration timestamp — not the
  original author or date.
- Issue numbers will not match the private originals (the public repo already has
  closed issues; the next created issue will be #N+1, not the private number).
  Every `closes #N` reference in private commit messages becomes a stale reference
  regardless — that is an accepted cost of migrating rather than leaving the private
  repo as a read-only reference.
- PR reviews and inline code comments are not migrated — they remain on the private
  repo's archived web UI.

**Tasks:**

1. **Enumerate closed issues on private.**
   ```bash
   gh issue list --repo glitchwerks/job-matcher-pr --state closed --json number,title,body,labels,comments --limit 200 > /tmp/private-issues.json
   ```
   Check the count: `jq length /tmp/private-issues.json`. If over 200, increase `--limit`.

2. **Enumerate closed PRs on private.**
   ```bash
   gh pr list --repo glitchwerks/job-matcher-pr --state closed --json number,title,body,labels,comments --limit 200 > /tmp/private-prs.json
   ```

3. **Create the `migrated-from-private` label on the public repo** (for filtering).
   ```bash
   gh label create migrated-from-private --repo glitchwerks/job-matcher --color "0075ca" --description "Migrated from glitchwerks/job-matcher-pr"
   ```

4. **Post each closed issue onto public.** For each item in `/tmp/private-issues.json`,
   create an issue on `glitchwerks/job-matcher` whose body begins with a header line:
   ```
   > Migrated from glitchwerks/job-matcher-pr#<original_number>
   ```
   followed by the original body, and apply the `migrated-from-private` label. Then
   post each original comment as a follow-up comment on the new issue. Close the issue
   after all comments are posted (to preserve the closed state).

   Scripted with `gh api`:
   ```bash
   # For each issue (pseudocode — implement as a script or jq+bash loop):
   NEW_URL=$(gh api repos/glitchwerks/job-matcher/issues \
     -f title="<original_title>" \
     -f body="> Migrated from glitchwerks/job-matcher-pr#<N>\n\n<original_body>" \
     -f "labels[]=migrated-from-private" \
     --jq '.html_url')
   # Post each comment:
   gh api repos/glitchwerks/job-matcher/issues/<new_number>/comments -f body="<comment_body>"
   # Close:
   gh api repos/glitchwerks/job-matcher/issues/<new_number> -X PATCH -f state=closed
   ```

5. **Post each closed PR onto public** using the same pattern — create as a regular
   issue (GitHub's API does not support creating historical PRs), prepend the migration
   header, apply the label, post comments, close. This reflects the discussion history;
   the diff is already in the commit history after the force push.

6. **Verify migration completeness.**
   ```bash
   gh issue list --repo glitchwerks/job-matcher --label migrated-from-private --state closed --limit 300 | wc -l
   ```
   Compare the count to `jq length /tmp/private-issues.json` + `jq length /tmp/private-prs.json`.

**Exit criteria:**
- All closed private issues and PRs recreated on public with migration headers and
  `migrated-from-private` label.
- Comment threads reproduced on each migrated item.
- Migration counts match.

---

## Phase 7 — Archive `glitchwerks/job-matcher-pr`

**Goal:** flip the archive bit on the private repo so no further commits, issues, or
PRs can be created against it.

**Entry criteria:**
- Phase 6 complete (closed issues and PRs migrated).
- Phase 5 complete and confirmed working with a single smoke test (HTTP 200 from `/feed`).
- Public repo has a release tagged (Phase 4 step 2).

**Tasks:**
1. On `glitchwerks/job-matcher-pr`, Settings → Danger Zone → Archive this repository.
   After archiving, the private wiki remains accessible read-only at
   `glitchwerks/job-matcher-pr/wiki/*`; the public wiki at
   `glitchwerks/job-matcher/wiki/*` is the canonical home for ongoing edits.
2. Update the archived repo's description to point at the public successor — GitHub
   shows the description prominently on archived repos. Suggested:
   `Archived. Consolidated into glitchwerks/job-matcher 2026-MM-DD (see #375).`
3. Update CLAUDE.md (both global and project) to reflect that
   `glitchwerks/job-matcher` is now canonical, and that any reference to
   `glitchwerks/job-matcher-pr` in memory files / commit messages is historical.

**Exit criteria:** archived; description updated; CLAUDE.md updated.

---

## Phase 8 — Cleanup

**Goal:** remove migration scaffolding from the workstation and any temporary remotes.

**Tasks:**

1. **Repoint workstation `origin` to the public repo.** The current `origin` points at
   the private `glitchwerks/job-matcher-pr`; after archiving, it should point at
   `glitchwerks/job-matcher`:
   ```powershell
   git -C I:\career\job-matcher-pr remote remove public
   git -C I:\career\job-matcher-pr remote rename origin private-old
   git -C I:\career\job-matcher-pr remote add origin https://github.com/glitchwerks/job-matcher.git
   git -C I:\career\job-matcher-pr remote remove private-old
   git -C I:\career\job-matcher-pr fetch origin
   git -C I:\career\job-matcher-pr branch --set-upstream-to=origin/main main
   ```
   Or simpler: delete the worktree and re-clone from the public URL into a new path.
2. **Branch hygiene.** Run the local `clean-gone` skill (hyphen, per CLAUDE.md
   "Worktrees" section) to remove any branches whose remote ref dangles after the
   origin URL change. **Note:** `clean-gone` is not designed for an origin-URL swap
   — if it flags too many branches as `[gone]`, abandon it and prune manually.
3. **Delete `.tmp/`** if any scratch files from the migration landed there
   (per `~/.claude/standards/scratch-files.md`).
4. **Delete this plan file** per the global CLAUDE.md "Lifecycle: delete plan files
   when done" rule, after extracting durable info into either issue #375's closing
   comment or a memory file. The plan's purpose ends when #375 closes.

**Exit criteria:**
- Workstation `origin` points at `https://github.com/glitchwerks/job-matcher.git`.
- No stale remotes, no `.tmp/` artifacts, this plan file deleted.

---

## Risks & mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| GHCR image not pushed before VM repoint | Medium | High (prod down) | Phase 3 verification gate; Phase 5 entry criteria explicit |
| Force-push loses public-only fixes | Low | Low | Recon confirmed all 3 public-ahead commits are duplicates |
| Rollback impossible after archive | Low | Low | Accepted by user — prod has no external consumers and is rebuildable from source. |
| Cross-repo issue links break | Medium | Low–Med | Phase 6 migrates closed issues/PRs with `migrated-from-private` label; commit-message `closes #N` refs become stale but that is an accepted cost |
| Tag SHA rewrite confuses anyone with the old tag pulled | Low | Low | One-time announcement; archived-repo description points at successor |

---

## Definition of Done

- Public repo `glitchwerks/job-matcher` `main` matches the post-Phase-2 private
  `main` SHA.
- A release is tagged on public marking the consolidation (Phase 4).
- Prod VM is running off `ghcr.io/glitchwerks/job-matcher:<tag>` and HTTP 200 from `/feed`.
- Closed issues and PRs from private have been migrated to public with the
  `migrated-from-private` label (Phase 6).
- Private repo is archived (Phase 7); its description points at the public successor.
- Workstation `origin` points at `https://github.com/glitchwerks/job-matcher.git`.
- Issue #375 is closed with a brief summary linking the final release.
- This plan file is deleted (per global CLAUDE.md lifecycle rule), with any durable
  notes lifted into the issue closing comment.

---

## Revision log

| Date | Change |
|---|---|
| 2026-05-27 | Initial plan drafted (router recon + doc-writer sub-agent). |
| 2026-05-27 | Open Questions resolved by user: Phase 6 rewritten as programmatic `gh api` migration; GitHub Releases accepted as historical-only (no replay); prod cutover timing requires no special coordination; downstream consumer updates not needed (portfolio links already point at public). |
| 2026-05-27 | Phase 4 step 1 revised: tag push is not required — public and private share identical tag SHAs and all four tagged commits are ancestors of `origin/main` (verified via `git merge-base --is-ancestor`). Phase 1 step 4 tightened: tag refs survive the force push; only GitHub Release notes/assets are historical-only. |
| 2026-05-27 | Removed rollback-anchor scaffolding (Phase 1 step 3, Phase 5 rollback procedure, Phase 7 24h window). User confirmed prod is a fresh slate — no external consumers, rebuildable from source if needed. |
| 2026-05-27 | Wiki status verified and documented in Context section — both wikis have 9 matching files; public wiki = private wiki + URL-rewrite commit (`69e62eb`); no migration action required. Phase 2 `publish.yml` row annotated to note wiki mirror is already complete. Phase 7 task 1 annotated with post-archive wiki accessibility note. |
| 2026-05-27 | Destination repo changed from `cbeaulieu-gt/job-matcher` to `glitchwerks/job-matcher`. `cbeaulieu-gt/job-matcher` was transferred into the `glitchwerks` org via `gh api repos/cbeaulieu-gt/job-matcher/transfer -X POST -f new_owner=glitchwerks`; verified by `gh repo view glitchwerks/job-matcher --json owner,visibility`; documented in #375 comment-4558806027. Same-org transfer removes the cross-owner reusable workflow access concern (Phase 1 step 1 dropped), keeps the GHCR namespace as `glitchwerks` throughout (no namespace switch), and reduces all ref rewrites to a `-pr` suffix drop with the `glitchwerks` org prefix unchanged. Phase 2 rewrite table extended to include `deploy.yml` lines 51, 62, 63, 253, 254, 265, 266, 267 (dynamic `${{ github.repository_owner }}/job-matcher-pr` image name suffix) and `docs/DOCKER.md` lines 98, 103, 268, 305. Phase 3 verification command updated to `gh api /orgs/glitchwerks/packages/container/job-matcher/versions`. Phase 5 verify/rollback image refs updated to `ghcr.io/glitchwerks/job-matcher`. Phase 6 migration target updated to `glitchwerks/job-matcher`. Phase 7 archived-repo description updated. Phase 8 `origin` re-point target updated. "Reusable workflow access denied post-cutover" risk row removed from Risks table. |
