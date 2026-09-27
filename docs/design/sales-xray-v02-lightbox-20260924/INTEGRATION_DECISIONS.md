# Lightbox integration decisions — 25 September 2026

The supplied design package is an input, not authority to change account, billing, privacy or release rules. These decisions reconcile it with the owner's direct requests and the current source. Preserve the original package unchanged for comparison.

## Source and ownership

- Tested starting revision: `b9031db471f6f0659adb5873cb9c3efc819536f0` on `codex/sales-xray-v02-integration-20260924`.
- UI worktree: `codex/sales-xray-lightbox-ui-20260925`. Only this worktree receives Lightbox edits.
- Claude Code implements one bounded phase at a time using verified `claude-opus-5-5`, effort `xhigh`. Codex reviews source, runs commands/tests and commits accepted phases. The source runner is retained for reference; it is not executed unchanged. Broad shell allowances are unnecessary: the implementation session receives repository file tools without shell, browser, MCP, server or provider access.
- R2, off-host backup and disk work belong to the owner's other Claude task. Do not investigate or change them here. Deployment uses the existing release process and its verified prerequisites; the design handoff's host observations are dated claims, not current release evidence.
- Baseline local tests passed: 457 web tests, app typecheck/lint/format/build, 24 auth/profile PostgreSQL tests and the compiled account-required browser journey (24 assertions, no provider calls). This establishes a starting point, not acceptance of the new UI or production quality.

## Product decisions

1. **Keep both report modes.** Lightbox reading is the default. Retain an accessible, polished tabbed/app view with the same facts, playback and supported deep links. Do not remove `view=reading|tabs`; keep old section aliases. The user explicitly requested both modes.
2. **First use is quiet.** Show the primary upload action, compact file limits/privacy and optional sample link. Do not render empty Calls/Activity tables, checklists or a sample insight sidebar. Returning users may see actual recent calls, with loading/error distinguished from an empty account.
3. **Account first.** Selection and preview can remain local, but upload/analysis require the existing verified-account, profile and consent gates. Preserve the selected file through sign-in. Legacy guest report compatibility is not permission to restore public guest processing.
4. **Let people navigate.** A held call remains in Calls. New analysis opens clean intake. A minimized upload/processing indicator must persist across client navigation before claiming background continuity. Never perform a full navigation during a live browser upload or say it is safe to close until the server has durably accepted the upload and dispatch.
5. **Show measured progress.** Upload percentages may use actual acknowledged byte transfer events, labelled uploading until server confirmation. Analysis stages come from the service. A decorative Lens loop is activity, not percent completion. No invented ETA, analysis percentage or measured waveform.
6. **Recovery copy follows capability.** Do not promise automatic retries, provider reconciliation, a support alert or no double charge merely because an error code matches a family. Offer only existing server-authorized recovery actions. Preserve valid saved work; unknown upload outcomes need status reconciliation before claiming nothing was saved. Retry polling is distinct from retrying paid analysis.
7. **Evidence stays visible.** Do not truncate the key takeaway, finding explanation or primary quote with ellipses. Compact transport labels may truncate with an accessible full name. Use a clear speaker label only when supported; otherwise explicitly identify it as uncertain. Do not turn seller examples into prospect figures.
8. **No lost report data.** Map all fourteen Dipak overview points and the actual eight dimension IDs to chapters. Preserve all observations sharing a clip, original language/script, source integrity, disclosure, retained/legacy reports and account permissions. Show word highlighting only when real word timestamps exist; otherwise synchronize segments.
9. **Useful Settings stay.** Do not remove working profile, local Test mode or settings controls. Remove empty placeholders only. Keep the shared learner/AC identity and existing avatar/auth behavior.
10. **Minimal chrome.** Compact transparent header and account control; no large greeting banner, slogans or persistent help cards. Essential actions must remain visible at 375×667 and keyboard/200% zoom; long reports intentionally scroll.
11. **Titles and names.** Display the existing persisted call title/filename. Add renaming only if an existing authorized persistence endpoint supports it; never create a pretend local-only rename. Use “The prospect” as the section title and show evidenced names inside the private report with attribution. Do not put names in URLs.
12. **Theme and samples.** Preserve dark tokens, but expose a toggle only after the whole relevant surface passes contrast/visual checks. Samples are explicitly fictional and opt-in; real recent content replaces empty or unsolicited sample panels.

## Phase gates

P0 produces a source-linked implementation plan and data mapping only. P1 covers reusable primitives/fonts/shell; P2 intake/confirm/upload; P3 processing/recovery; P4 report/player; P5 library/auth/profile; P6 responsive/keyboard/performance and compiled journey proof. One phase per invocation, followed by source review and appropriate tests. Codex handles dependency changes and lockfile, test execution and commits. Report inability honestly; do not delete or weaken tests, invent successful execution, use external URLs, or edit backend/infra/CI.

Visual references are the supplied boards. Any deviation must cite a user requirement or current contract and be recorded. Token contrast and fonts must be verified rather than copied on trust. No phase is “live” until the same reviewed artifact set is deployed and verified through the normal release path.
