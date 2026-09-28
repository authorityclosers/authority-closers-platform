# CODEX NON-NEGOTIABLE GUARDRAILS

- Do not infer protected business semantics.
- Do not use Naya-owned repos for new AC product work.
- Do not put secrets in Git, vault, skills, logs or prompts.
- Do not make production DB/VPS manual state authoritative.
- Do not use direct SQL edits as an operational recovery path.
- Do not couple payment provider state directly to access.
- Do not turn analytics events into canonical progress/payment state.
- Do not overwrite audit-critical history; supersede.
- Do not create official autonomous AI scoring before AC-SVAL gates.
- Do not process real calls externally before consent/retention/provenance/provider/professional gates.
- Do not build full B2B/native/WhatsApp/voice merely because the architecture preserves those futures.
- A P0 blocks its capability, not the whole project.
- Every code change must leave tests and implementation evidence.


# DELIVERY CONSTITUTION (binding for every agent and person)

1. One task at a time, for the whole company: every agent, person and device.
   A task is one small, reviewable change tied to one tracked issue. No new task
   starts while any task branch or pull request is open, or while the latest
   `main` build is not green. Do not widen scope or refactor on the side; record
   other findings as proposed tasks.
2. Start every task with the gate, never with raw git:
   `python scripts/ac_task.py start <issue>-<short-name>`. It refuses while
   anything else is open and otherwise branches from the latest `main` and claims
   the task on GitHub. Check with `python scripts/ac_task.py status` first; run
   `python scripts/ac_task.py check` before resuming work. If the gate says BUSY,
   stop and report. Never build on old, integration, release or other task
   branches. Do not create extra git worktrees.
3. `main` is the only long-lived branch. A task branch lives only until its pull
   request merges or closes (GitHub then deletes it, which frees the gate); run
   `python scripts/ac_task.py done` afterwards. The `single-track` check fails any
   pull request while another one is open.
4. Done means: the change works on the dev environment, tests and evidence for the
   changed areas pass, the pull request against `main` explains what changed and
   how to check it on dev, and CI is green. Then stop and wait for the owner.
5. The owner approves by merging. Billing settings, payment settings, and
   purchases require explicit human permission.
6. Releases move one way: merge to `main` -> CI builds images once -> staging
   deploys automatically -> the owner promotes the same build to production from
   Admin -> Releases. No laptop deploys, no manual server edits, no rebuilds
   between environments.
7. Use included subscriptions only. Stop on usage limits; never fall back to API
   keys or paid credits. Only one agent runs at a time.
8. Secrets never go in git, prompts, logs, task comments or pull requests.

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
