# CODEX NON-NEGOTIABLE GUARDRAILS

- Do not infer protected business semantics.
- Do not use Naya-owned repos for new AC product work.
- Do not put secrets in Git, skills, logs, chat or task text. Secrets live only
  in Infisical and the team password manager (see OWNER-APPROVED SECRETS).
- Change production DB/VPS state only as a recorded data change (see OWNER-APPROVED
  DATA CHANGES); never leave unrecorded manual state.
- Direct SQL is allowed only as an owner-approved data change: scripted, one
  transaction, backed up, verified and logged. Never ad-hoc typing into a
  production shell.
- Do not couple payment provider state directly to access.
- Do not turn analytics events into canonical progress/payment state.
- Do not overwrite audit-critical history; supersede.
- Do not create official autonomous AI scoring before AC-SVAL gates.
- Do not process real calls externally before consent/retention/provenance/provider/professional gates.
- Do not build full B2B/native/WhatsApp/voice merely because the architecture preserves those futures.
- A P0 blocks its capability, not the whole project.
- Every code change must leave tests and implementation evidence.


# DELIVERY CONSTITUTION (binding for every agent and person)

1. One task at a time per lane, for every agent, person and device. There are
   twelve lanes: `sales-xray`, `platform`, `admin`, `ui`, `devenv`, `api`
   (back-end and API work for the apps: `packages/python/**`, `db/migrations/**`,
   `tests/**`; never files under `apps/*-web/`), `billing` (the same scope,
   for the payments and billing back end only), `sx-report`, `sx-org`,
   `sx-billing`, `sx-shell` and `sx-prospects`. Each feature lane carries its
   feature's UI and API; the billing back end stays in `billing`.
   Lanes run in parallel; each holds one task. A task is one small, reviewable
   change tied to one tracked
   issue. No new task starts in a lane while that lane holds a task branch or pull
   request, or while the latest `main` build is red (only the task that fixes it
   may start, with `--fixes-red-main`). A running `main` build does not block a
   start; merges still wait for a green `main`. Pull requests may not
   change the same files, and only one at a time may change shared files
   (migrations, lockfiles, workflows, AGENTS.md, the gate). Do not widen scope or
   refactor on the side; record other findings as proposed tasks.
2. Start every task with the gate, never with raw git:
   `python scripts/ac_task.py start <lane> <issue>-<short-name>`. It refuses while
   the lane is busy and otherwise branches from the latest `main` and claims the
   task on GitHub. Without a lane, a task is exclusive: it runs only when nothing
   else is open, and nothing else starts while it is. Check with
   `python scripts/ac_task.py status` first; run `python scripts/ac_task.py check`
   before resuming work. If the gate says BUSY, stop and report. Never build on
   old, integration, release or other task branches. One checkout per lane; do not
   create extra git worktrees.
3. `main` is the only long-lived branch. A task branch lives only until its pull
   request merges or closes (GitHub then deletes it, which frees the lane); run
   `python scripts/ac_task.py done` afterwards. The `single-track` check fails a
   pull request while its lane is taken, its files overlap another open pull
   request, or both change shared files.
4. Done means: the change works on the dev environment, tests and evidence for the
   changed areas pass, the pull request against `main` explains what changed and
   how to check it on dev, and CI is green. Then stop: the CTO reviews and the CEO
   approves.
5. The CEO approves merges on the owner's behalf; the watchdog merges exactly the
   approved change, re-tested on the latest `main`. When a branch update from
   `main` is the only new commit and the pull request's own diff is unchanged,
   the approval carries over; any other change needs a new review. Billing
   settings, payment settings, purchases, secrets and data deletion still
   require the owner's explicit permission. Production data changes require the
   owner's permission, given per change or pre-approved per kind under
   OWNER-APPROVED DATA CHANGES. UI Guard may approve
   eligible UI-only merges under ADR 0041's SHA-bound scope, checks and hold
   rules; all other merges retain CTO review and CEO approval.
6. Releases move one way: merge to `main` -> CI builds images once -> staging
   deploys automatically -> the same build is promoted to production. Train
   promotions run under the owner's standing approval (ADR 0041); everything
   else is promoted by the owner from Admin -> Releases. No laptop deploys,
   no manual server edits, no rebuilds between environments.
7. Use included subscriptions only. Stop on usage limits; never fall back to API
   keys or paid credits. Agents run in parallel only as far as the server's
   headroom allows (the launcher's slots).
8. Secrets never go in git, logs, chat, task comments or pull requests. Agents
   may move them into Infisical or the team password manager as set out in
   OWNER-APPROVED SECRETS.

# DELIVERY AMENDMENT (owner order, 9 Oct 2026)

These rules supersede older delivery wording where they conflict.

- **Feature strike path:** for each owner-visible feature, the CEO saves a one-page
  `strike-brief` document with the screen, states, data, acceptance checks and
  preview URL. One Sol builder builds the API, UI and tests end to end in one
  lane checkout with that lane's live preview. One PR, about 1,500 changed lines
  at most; one CTO review. CEO approval follows only for sensitive paths
  (billing, payments, identity/auth/security/secrets, migrations, infra,
  workflows, the gate, data-change scripts, AGENTS.md, lockfiles or manifests).
  Pilots: [AUT-1579](/AUT/issues/AUT-1579) (Card C) and [AUT-1350](/AUT/issues/AUT-1350). Owner permissions in rule 5 still apply.
- **Review deadline:** a green PR gets a verdict within 60 minutes. Otherwise
  the watchdog routes it to the backup reviewer (CTO, pod lead or CEO).
  Silence is never approval; reviews and approvals remain bound to the head SHA.
- **Done means in production:** the release engine closes the task with the
  production version. A review, merge or dev preview is delivery evidence,
  not task completion.
- **Managers:** CEO and CTO are woken only for decisions and reviews. Each posts
  at most one comment per run and creates at most three new cards per day.

# PULSE MODE AND OWNER DECISIONS (owner orders, 10 Oct 2026)

These rules supersede older wording where they conflict, including rule 1's
one-small-change limit for strikes. They were recorded on [AUT-1701](/AUT/issues/AUT-1701).

- **Strikes (until 17 Oct 2026, 24:00 IST; then reviewed with the owner):** each
  owner-listed feature runs as one long direct session on the server
  (`ac-strike@<card>`), on one branch `task/<lane>/<card>-strike-<name>` with one
  open PR. The features are AUT-1663 (screens), AUT-1677 (report and prospect),
  AUT-1676 (stuck analyses and charges), AUT-1678 (coaching) and AUT-1694
  (organisations). A strike is a whole feature, not a small change, and not a
  bypass.
- **Strike merges:** the watchdog squash-merges a strike PR on green CI at most
  every 2 hours, with no review, unless it touches billing, payments, sign-in,
  database migrations, secrets, dependencies, `.github/`, `infra/` or this file.
  Staging deploys `main` automatically, and dev takes `main` every 10 minutes.
  Production promotes only on the owner's explicit "ship it".
- **Owner decisions are final and fast.** Each of these is a full sign-off for
  that PR's green head for 48 hours, and it lifts earlier CEO/CTO holds:
  - a board comment by the owner or the owner's session reading
    `Owner approved merge: PR #n` (optionally `@ <sha>`);
  - a Telegram reply `approve #n`;
  - the Telegram Approve button.

  `Owner: hold PR #n` stops it.
- **Sign-off deadline:** a green PR that needs a sign-off goes to its reviewer.
  After 30 minutes without a verdict, the watchdog sends it to the owner on
  Telegram with Approve and Hold buttons. Silence never blocks for longer.
- **Holds:**
  - Every CEO/CTO `Merge hold` names what clears it.
  - A hold expires after 4 hours unless it is renewed with new evidence.
  - A hold that would block an owner order goes to the owner the same hour, as
    one decision. Agents never contain an owner order on their own.
- **One rulebook:** an owner decision made in chat is written into this file
  within the hour, by the owner's session or the CEO. Until it lands, the
  owner's recorded order on the board binds every agent.
- **Next: machine gates ([AUT-1741](/AUT/issues/AUT-1741)).** A migration-safety
  check (upgrade and downgrade on a copy of the staging schema) and an
  authorization diff test replace human review of routine risk. When they pass,
  migrations and access-rule changes merge like ordinary changes. Only billing,
  payments, secrets and the core sign-in keep a person's sign-off. Database
  changes ship first, as tiny PRs.

# OWNER-APPROVED DATA CHANGES

Purpose: make urgent account, workspace and access changes in minutes, without
waiting for a feature release.

Allowed kinds (dev, staging, production):
- memberships and roles (owner, admin, member), ownership transfer
- permission grants and product switches per workspace (e.g. Sales Xray on)
- workspace create/rename and verified email domains
- unsticking a job or call when the app has no button for it

- permanent deletion, only as set out in OWNER-APPROVED DELETIONS

Never through this path:
- rewriting audit history (supersede instead)
- payments, billing, credit balances, plan prices
- secrets or credentials (Infisical only)
- schema changes (migrations only)

How:
1. Approval: the owner writes "approve data change: <what>, <environment>" in
   chat or on the issue. The owner may pre-approve a repeatable kind once (e.g.
   "add @authorityclosers.com staff to the AC organisation"); every run is
   still logged.
2. The change is a checked-in script in `scripts/data-changes/`: idempotent,
   dry-run by default, prints before/after, runs in one transaction, and writes
   an audit event naming the approver and the issue.
3. Production: take a database snapshot first, show the owner the dry-run,
   then apply.
4. Verify by reading back through the app or API; post before/after, run id
   and approver on the issue.
5. Within 2 working days, the same result is also covered by a migration,
   seed or Admin feature, so no environment depends on hand-made state.

Who runs it: one named operator at a time (the CTO's ops agent or the owner's
Claude session), never during a release.

# OWNER-APPROVED DELETIONS

Permanent deletion (users, calls, recordings, reports, duplicates, files) is
allowed once the owner approves that exact request:
1. The agent first shows the exact list (ids, names, environment, count) and
   what cannot be recovered.
2. The owner answers "approve delete: <that list>, <environment>" (or "go
   delete" in reply to that list). The approval covers only that list.
3. Production: take a snapshot first. Prefer the app's own delete path; use a
   `scripts/data-changes/` script only when the app has none.
4. Log what was deleted (ids and counts, never contents) on the issue, with
   the approver and time. Audit history is never deleted.

# OWNER-APPROVED SECRETS

When the owner asks, an agent may copy a password, token or API key from where
it is created (e.g. a provider console) into Infisical or the team password
manager, and read it from there to configure a service.
- Use methods that do not print the value: clipboard paste into the target
  field, `infisical secrets set` from stdin, or injection at runtime.
- Never repeat the value in chat, logs, task comments, commits, pull requests
  or screenshots shared onward.
- Record on the issue which secret name was set, in which environment, by whom
  and when; never the value.
- Staging and production keep separate secrets; never copy a production
  secret into dev.

# CODEX SOURCE FETCH ORDER

Use the CSV/JSON manifest. Fetch by exact Drive ID/URL, not filename guesses.

## Required first
1. Master Index
2. BRD
3. AC-IMP-00
4. AC-IMP-01
5. AC-IMP-03
6. AC-IMP-04
7. AC-IMP-05

## Required before first-slice code
PRD, IA, UX Research, UX States, UI System, SRS, Data/Tenancy, API/MCP, Security, QA, DevOps, Admin, Telemetry, ADR/Risk.

## Assurance as relevant
AC-UXA-01 for learner/admin/recovery/accessibility work.
AC-SVAL-01 before any scoring/evaluation work.
AC-GOV-AUD-001 before provider/store/recording/AI data activation.
Hostile audit findings are normalized into AC-IMP-03; do not invent original missing issue text.

## Raw founder evidence
Use only for context and to verify intent. Controlled docs win.

## Cloud research orchestration

For expensive, separable research or review, follow the `ac-orchestra`
skill at `C:\Users\Suyash\.codex\skills\ac-orchestra\SKILL.md`.
Codex remains the integration and release owner: pin the source revision, keep
file ownership separate, reproduce relevant claims locally, run the repository
gates, and verify the real deployed journey. Use the authorized normal ChatGPT
Pro chat in Chrome for research when available; if it is unavailable or capped,
record that limitation and continue useful local work or a bounded Luna xhigh
delegate. Never bypass service limits, silently substitute an unapproved model,
send secrets or raw customer data, or treat a cloud-chat handoff as production
evidence. A handoff is accepted only after its claims and artifacts are checked
against the repository and release controls.

For substantive Sales Xray interface design, report presentation, architecture,
and reusable SVG/component generation, continue the relevant existing AC
Orchestra Pro chat with an exact source pin and bounded deliverable. Reuse and
harvest its existing work before opening another research chat. Keep a durable
chat-to-task record and use the authorized GitHub handoff route. Codex owns
machine access, source review, integration, tests and release verification; cloud
claims never replace those checks. Record unavailable Pro access or artifacts
explicitly and keep the urgent verified repair moving.
