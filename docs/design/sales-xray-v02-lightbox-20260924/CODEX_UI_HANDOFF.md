# Codex handoff — ship the Sales Xray v0.2 "Lightbox" UI (built by Claude Code, Opus 5.5) to staging and production

- **Date:** 24 September 2026 (IST night)
- **From:** Claude Code (Opus 5.5), on the founder's instruction
- **To:** the main Codex coding agent (integration and release owner)
- **Founder instruction (Suyash, 24 Sep 2026):** Codex uses **Claude Code with model `claude-opus-5-5` at effort `xhigh`**, invoked through the `claude` CLI, to implement this UI. Integrate it with the work Codex is doing now, and ship it live on **staging and then production in the next release**.
  - Record this instruction in your task record.
  - It supersedes, for this workstream only, the `AGENTS.md` guidance to route Sales Xray interface design through the AC Orchestra / ChatGPT Pro chat.
  - Codex remains source reviewer, integrator and release owner. Every `AGENTS.md` guardrail still applies.

**Package contents** (currently untracked in `D:\Projects\authority-closers-platform\docs\design\sales-xray-v02-lightbox-20260924\`):

| File | What it is |
|---|---|
| `DESIGN_SPEC.md` | Behaviour, IA, data mapping and constraints. Authoritative. |
| `CLAUDE_UI_BRIEF.md` | What Claude reads on every run: phases P0–P6, gates, report format. |
| `run-claude-ui.ps1` | The runner. Verified flags, locked-down permissions. |
| `tokens.css` | Design tokens. |
| `assets/lens/*.svg` | The six Lens character states. |
| `assets/glyphs/lightbox-glyphs.svg` | Semantic glyph sprite. |
| `assets/illustrations/*.svg` | Empty-state and offline illustrations. |
| `prototype/canvas/project/*.dc.html` | 10 visual boards, also on the canvas: https://claude.ai/artifact/5TYWjU7XhUd3gVGV2HzLKS (private to Suyash until shared). |

Bug context: `D:\Projects\authority-closers-platform\docs\evidence\sales-xray-bug-handoff-20260924\HANDOFF.md`. You are already executing it: `codex/sales-xray-v02-integration-20260924`, `codex/pr1a-provider-failure-observations`, `codex/sales-xray-pr3-b4-b5-20260924`.

---

## 0. URGENT — production safety findings from the host (read before any production release)

Observed read-only over `ssh ac` (host `ac-kvm4-prod`) at about 17:40 UTC, 24 Sep. No changes were made.

| Unit | State | Last success | Failure reason (from journal) |
|---|---|---|---|
| `ac-postgres-backup.service` | **failed** | **2026-09-10 04:54 UTC** (14 days ago) | "Logical backup failed for staging, production … Off-host upload failed; the verified local pair was retained. R2 usage or projected logical-dump storage is not safe." |
| `ac-restic-backup.service` | **failed** | **2026-09-01 02:17 UTC** (23 days ago) | "Class B operations 7000001 reach or exceed policy admission cutoff 7000000." |
| `ac-r2-usage-guard.service` | **failed** | — | (the guard itself is tripping on the same R2 Class B budget) |
| `ac-restic-restore-check.service` | **failed** | — | (restore drill cannot run without the off-host repository) |

- Disk on `/` is **85% used** (163G of 193G, 30G free).

**Meaning:**
- There has been **no off-host database backup for two weeks**. Only local verified pairs exist.
- A production release that runs migrations (v0.2 has migration 0044+) without a fresh off-host backup means no verified off-host rollback point.

### 0.1 Root cause (confirmed by Claude, 25 Sep ~00:00 IST, read-only analysis)

**Where the reads went:**
- Cloudflare R2 analytics for September show **6,998,058 `GetObject` on `authority-closers-backups-prod`**. The objects bucket shows essentially nothing.
- Daily totals grew linearly: 82,751 (1 Sep) → 248K → 414K → 579K → 720K → 909K → 1.07M → 1.23M → 1.36M (9 Sep).
- Then the guard tripped (≥ 7,000,000 cutoff) and blocked every writer.

**Why the reads grew:**
- `infra/vps-foundation/config/systemd/ac-postgres-backup.service` runs Restic every 5 minutes under `ProtectSystem=strict`, but its `ReadWritePaths` **omits `/var/cache/authority-closers-restic`**.
  - Every other Restic unit includes that path: `ac-restic-backup`, `ac-restic-restore-check`, `ac-restic-postgres-restore-proof@`.
- So Restic ran uncached and re-downloaded every snapshot and index object on every run.
- The daily `forget --keep-within 27h` + `prune` lives in `ac-restic-backup`, which was blocked from 1 Sep. Logical snapshots therefore piled up, and each uncached run got more expensive.
- The quadratic growth matches exactly: about 2,400 GETs per Restic run by 9 Sep, with 576 runs a day (288 timer runs × 2 environments).

**Secondary cause, now fixed on the host:** 3,003 failures read "migration head has no reviewed row-count parity contract". The installed `ac-postgres-backup.py` (foundation `ccc664c5`, installed 24 Sep 12:14) already covers migration heads through `20260924_0048`, and current failures are only the R2 guard. **Every future migration still needs a reviewed parity contract** in `ac-postgres-backup.py`, or logical backups stop again.

**Local backups are healthy:** 336 verified local pairs per environment, the newest within minutes (checked 18:27 UTC, 24 Sep). The gap is the off-host copy only.

### 0.2 The fix (ready for you to release)

- Branch **`claude/backup-restic-cache-20260925`**, commit **`01aaf95298081b3b9b66c0a89f01015fca7d1487`**. Parent: `ccc664c5`, the live foundation commit. Pushed to origin.
  - Adds `/var/cache/authority-closers-restic` to `ac-postgres-backup.service` `ReadWritePaths`.
  - Updates `test_timer_and_unit_are_persistent_bounded_and_hardened`.
  - Adds `test_every_restic_unit_can_write_the_shared_restic_cache`.
  - `tests/infra/test_postgres_backup.py` and `test_postgres_restore_proof.py`: 79 passed, 7 POSIX-only skipped on Windows; ruff clean. Let CI run the POSIX cases.
- **Founder decisions (25 Sep):**
  1. **Keep the R2 Class B cutoff at 7,000,000.** Do not lift the quota (runbook rule). Off-host backups resume on their own after the monthly reset at **2026-10-01 00:00 UTC**.
  2. **Codex installs the fix** in its normal release flow. Claude did not install it.

### 0.3 Required, with a hard deadline

1. **Install a foundation release containing `01aaf952` before 2026-10-01 00:00 UTC.**
   - Merge it into your integration line, or install `foundation-01aaf952…` directly; it differs from the live foundation only by this fix.
   - Use `infra/vps-foundation/runbooks/OPERATIONS.md` → "Immutable foundation release" (`git archive … -- infra/vps-foundation`, then the installer with `AC_RELEASE_ID` / `AC_RELEASE_ARCHIVE` / `AC_RELEASE_ARCHIVE_SHA256`).
   - The installer recreates the foundation Compose project (a brief edge blip) and rolls back automatically on failure.
   - **If this misses the deadline, the uncached five-minute job burns October's allowance within days, and every backup stops again.**
   - Do not work around it with host drop-ins or by editing release files: the restore drill verifies `RELEASE-FILES.sha256`.
2. **After 1 Oct 00:00 UTC**, verify recovery with the reviewed services only:
   - `ac-postgres-backup` logs `PASS … snapshot uploaded` for both environments.
   - The 02:15 UTC `ac-restic-backup` run succeeds, including `forget --keep-within 27h` + `prune` of the September backlog. Start it manually after 00:05 UTC if you want it sooner.
   - `ac-restic-restore-check` passes (or run the weekly drill manually).
   - `ac-r2-usage-guard` is green.
3. **Watch the first 24h of October** with the same GraphQL breakdown (`r2OperationsAdaptiveGroups` by `bucketName` + `actionType` + `date`). Expect Class B in the low thousands per day, not hundreds of thousands. If it grows day on day again, stop the five-minute timer and investigate before the guard trips.
4. **Disk (85%):** prune superseded release directories through your reviewed release tooling, keeping current production (`270a4b57…`), current staging (`ccc664c5…`) and the previous known-good release of each. Never delete the local logical backup ring by hand.
5. **Production release gate:** don't ship the v0.2 production release before step 2 passes, unless the founder accepts the risk in writing in the release receipt.
6. **Alerting gap:** these units failed silently for 14–23 days. Add a failure notification (e.g. `OnFailure=` to a notifier, or a daily summary to the founder) through a reviewed foundation change.

If the founder explicitly accepts deploying without a fresh off-host backup, record that acceptance in the release receipt.

---

## 1. Current state (verified 24 Sep 2026)

| Surface | Revision |
|---|---|
| Production API + Sales Xray web | `270a4b57e39646ba6b5e171614bc9ef114091d09` (#63's runtime) |
| Staging API + Sales Xray web | `ccc664c5df0808cae42a1d8f07dad7b6998c4816` ("test(learner): inspect report tabs from default reading view"), in the integration line |
| Integration branch | `codex/sales-xray-v02-integration-20260924` @ `7ff3581f` (merges v02-intake, auth-recovery, avatar-transport into the #67 stack) |
| Codex in-flight branches | `codex/pr1a-provider-failure-observations`, `codex/sales-xray-pr3-b4-b5-20260924` (both at `7ff3581f` when checked) |

Release path observed on the host:
- Compose files under `/srv/authority-closers/application/releases/<sha>/` (`compose.yaml`, `compose.filesystem-media.yaml`, `compose.sales-xray-hosted.yaml`).
- Environment in `environments/<env>.env` and `release-images.env`.
- Native activation in `/srv/authority-closers/application/operator-inputs/<env>/…`.
- Separate `ac-sales-xray-web-<env>` containers.
- Native helpers: `ac-sales-xray-native-{staging,production}.service`.

Workflows: `.github/workflows/application.yml`, `sales-xray-web-image.yml`, `sales-xray-native-image.yml`. Host scripts: `infra/application/scripts/install-application-release.sh`, `sales-xray-hosted.py`, `verify-release-archive.py`, `prepare-release-inputs.py`. **Use your existing, reviewed release procedure.** This handoff does not change it.

---

## 2. Setup

### 2.1 Branch and worktree
1. Create `codex/sales-xray-lightbox-ui-20260925` from the **current tip** of `codex/sales-xray-v02-integration-20260924`.
2. Create a dedicated worktree, e.g. `C:\Users\Suyash\.codex\worktrees\sales-xray-lightbox-ui\authority-closers-platform`.
3. Install dependencies there with the repo's normal `pnpm install`.
4. Copy the whole design package folder into the branch at the same path (`docs/design/sales-xray-v02-lightbox-20260924/`). Commit it as the first commit: `docs(sales-xray): add v0.2 Lightbox design package`.
   - This must happen first: the runner refuses to start if `CLAUDE_UI_BRIEF.md` is missing on the branch.

### 2.2 Claude Code CLI prerequisites (checked on this PC, 24 Sep)
- **Installed:** `claude` 2.1.281 at `C:\Users\Suyash\AppData\Roaming\npm\claude.ps1`.
- **Not signed in:** `claude auth status` shows `"loggedIn": false`. A headless smoke test returned "Not logged in · Please run /login".
- **The founder must sign in once** (Codex must not handle credentials). Either:
  - `claude auth login` (browser sign-in), or
  - `claude setup-token` (a long-lived token for headless use; follow its printed instructions for where to store it).
- **Verify with a tiny run** (should print `OK`):

  ```powershell
  claude -p "Reply with exactly OK" --model claude-opus-5-5 --effort xhigh --output-format json
  ```

- **Verified flags** (from `claude --help` on this PC): `--model`, `--effort low|medium|high|xhigh|max`, `-p`, `--output-format json`, `--permission-mode acceptEdits`, `--permission-prompts none`, `--allowedTools` / `--disallowedTools`, `--session-id`, `-r/--resume`, `-n/--name`, `--append-system-prompt`, `--max-budget-usd`.
- **Two things not to do:**
  - There is **no `--cwd`**. The runner `Set-Location`s into the worktree.
  - **Don't use `--bare`**: it switches auth to `ANTHROPIC_API_KEY` only and skips normal sign-in.

---

## 3. Division of labour

| Area | Owner |
|---|---|
| All `apps/sales-xray-web/**` presentation: shell, New analysis, Confirm, Uploading, Analysing, States, Report, Library, auth/profile visuals, tokens, fonts, Lens, glyphs, motion | **Claude (Opus 5.5)** via the runner |
| Frontend bug fixes U1, U3, U4, U5, U6, U8, R1–R4, R6–R8, R10, A1, A3–A9 (frontend parts) | **Claude**, folded into phases P2–P5 |
| Backend bugs B1–B8; U2 server reason codes; U7 upload limiter; R5 waveform max-pooling; R9 streaming; A2 server `returnTo` allowlist; A5 server lockout state | **Codex** (your existing bug PR plan) |
| **Rename-a-call API** (founder decision, DESIGN_SPEC §12.1): owner-authorised `PATCH` of a bounded `display_title` on the submission, returned in submission, progress and library payloads, and audited | **Codex**. Land it before Claude's P4, so the rename UI can ship. |
| Any API or contract change requested by Claude (`backend_requests` in its report) | **Codex** decides and implements |
| Review, gates, CI, integration, staging and production release, evidence receipts, ops (backups, §0) | **Codex** |

**Conflict rule:** the Lightbox branch owns `apps/sales-xray-web/app/**`. Keep backend PRs out of those files. If a backend PR must touch the frontend client (`acquisition-client.ts`), land it first, then run Claude's next phase on top.

---

## 4. The phase loop (repeat P0 → P6)

For each phase:

1. **Run it** from any directory:

   ```powershell
   pwsh -File D:\Projects\authority-closers-platform\docs\design\sales-xray-v02-lightbox-20260924\run-claude-ui.ps1 `
     -Phase P1 -Worktree C:\Users\Suyash\.codex\worktrees\sales-xray-lightbox-ui\authority-closers-platform
   ```

   - Add `-MaxBudgetUsd <n>` if the account bills per API call.
   - It prints Claude's JSON phase report and saves the full result, with `session_id`, under `$HOME\.sales-xray-lightbox-runs\`.

2. **Review:**
   - `git show --stat HEAD` and a full diff read.
   - Confirm the phase touched only allowed paths.
   - Confirm no product-truth violations: scores, synthetic waveforms, fake progress, translated quotes, italic Devanagari. Grep for them.

3. **Gates:**
   - `pnpm --filter @ac/sales-xray-web typecheck`, `lint`, `test`, `build`.
   - Push the branch (you, not Claude) and let full CI run.
   - The compiled guest upload → report → reload → claim → deletion browser gate must **run, not skip**.

4. **If anything is wrong,** resume the same Claude session with precise feedback:

   ```powershell
   pwsh -File …\run-claude-ui.ps1 -Phase P1 -Worktree <path> -Resume <session_id> -Message "Codex review: <exact issue, file:line, expected behaviour>"
   ```

5. **Backend requests** from the report: implement them in your backend PRs, then tell Claude in the next phase's `-Message` that they have landed.

6. **Accept the phase** (all gates green), then start the next phase.

**Expected phases:**

| Phase | Scope |
|---|---|
| P0 | Plan (docs only) |
| P1 | Foundations + shell |
| P2 | New analysis / Confirm / Uploading |
| P3 | Analysing + edge states |
| P4 | Report |
| P5 | Library + auth |
| P6 | QA, evidence, cleanup |

Don't let Claude batch several phases into one run. Small, reviewable diffs.

---

## 5. Integration and release

1. **Order:**
   - Backend bug PRs (B1/B2 first, then B3 budget settlement, then B4/B5) can land into the integration branch in parallel with Lightbox P0–P3.
   - Merge the Lightbox branch into the integration branch after **P4** passes CI (report complete), then again after P6.
   - Use merges, not rebases, to preserve review history. Resolve conflicts in favour of the Lightbox presentation plus the backend contract.

2. **Staging:**
   - Build the release set from the exact integration SHA through the existing workflows: application, web image, native image.
   - Install on staging with the existing host procedure.
   - Staging acceptance uses **synthetic or provenance-cleared audio only** (`AGENTS.md`):
     - Full journey, desktop and mobile: drop → confirm → uploading bar with real bytes → analysing (each stage) → report "develops" → play markers and moments → keep listening past a clip → skills expand → copy phrase → transcript sync → library → reopen.
     - Edge states: offline for 30s mid-processing (auto-resume); interrupted PUT then reload (no phantom call); over-60-minute file (precise error); paused with each failure family (copy map); needs-OK card.
     - Hindi + English and Marathi + English reports (Devanagari quotes upright, `lang` set).
     - Reduced motion; 1440×900, 1366×768, 1024×768, 390×844, 375×667.
     - Screenshots in `docs/evidence/sales-xray-lightbox-<date>/` mapped to canvas boards.

3. **Production** — only after §0 is resolved or the founder has explicitly accepted the risk:
   - Promote the **same verified artifact set** through the normal release path.
   - Run a small authorised canary: one fictional guest call and one signed-in call, confirming the report, reload and library.
   - Rollback is the previous release directory and images (`270a4b57…` is the current fallback).
   - Forward-only for data; never direct SQL.

4. **Release receipt** must list:
   - API/worker SHA, web image digest, native image digest, migrations.
   - Staging and production evidence links.
   - Backup status at release time.

---

## 6. Definition of done

- Every canvas board has a faithful implementation at desktop and mobile (DESIGN_SPEC §11).
- Frontend bugs U/R/A are fixed with tests (or deferred with a written reason). Backend bugs follow your bug plan.
- No numeric score, synthetic waveform, fake progress or translated quote anywhere.
- Lighthouse accessibility ≥ 95 on New analysis, Analysing and Report. Keyboard-only journey passes. CLS < 0.05.
- Staging and production run the Lightbox UI on the exact release SHA, with evidence captured and backups healthy at release time.

---

## 7. Do not

- Let Claude push, deploy, ssh, change backend, infra or CI, or read secrets or customer data.
  - The runner enforces this with `--permission-prompts none` plus allow/deny lists. Don't loosen it with `bypassPermissions` or `--dangerously-skip-permissions`.
- Skip or silence tests to get a phase green.
- Ship to production while off-host backups are failing without the founder's written acceptance.
- Delete any of the existing worktrees or untracked evidence folders.
