# AUT-1677 — retained Report, Story and server prospect facts

Owner correction: 10 October 2026, 15:58 IST. Keep the existing Report and defaults; add Story and enrich existing sections. Binding specification: `final-xray-structure-2026-10-09.md`, SHA256 `a464e69123f9a649f5f038e464d6086c6d52220b09e3e50eb24b44c6769e3110`. Controlled-source fetch receipt remains `report-pillars-word-20261010.md`.

## Result

- Reading, Tabs and Document retain their supplied sections. Overview, Skills and Next-call plan gain collapsed call-level detail; no existing section is replaced.
- Story renders the six pillars in order through `OperationalPanel`, the same shared surface used by Coaching. It uses the retained validated C5 report and canonical story projection when available. Missing outcome, phases, next step, skills or source quotes remain explicit gaps.
- Each authenticated person/workspace remembers their chosen view on this browser. Explicit bound report URLs take priority. With no preference, the existing desktop Tabs / narrow Reading default applies. Presentation preferences are the only newly persisted browser values.
- All eight call skill rows have a `/coaching?focus=<canonical-domain>` link. No practice plan, longitudinal score or generated coaching is introduced into Report.
- Prospect fields use the existing Pulse-derived `InlineEdit`: click, edit the current value, Enter or blur saves; Escape cancels. Human locks and source quotes/times remain visible. Exact field API receipts and expected revisions are checked.
- Key facts read the linked server Prospect's Information and use the same field API. Legacy device facts are ignored; they are neither silently promoted nor deleted. GETs do not create or merge identities. A missing link/service leaves the Report usable with a corner retry. Acknowledged writes followed by failed reads are reported as saved, with stale edit controls withheld.
- Prospect linking and facts use flat rows, avoiding nested prospect cards.
- Existing server speaker predictions now surface their detected names/roles and a one-tap confirmation when complete. Confirmed/channel roles remain distinct from predictions; the audited speaker-map API records the person's confirmation. Unknown roles retain the existing editor.

## Verification

- Six focused frontend files: 88 tests pass (Report view/navigation/preferences, pillars, inline Prospect edits, linked server facts, detection controls and speaker confirmations).
- Approved local corpus: all 13 retained C5 reports still open offline; three corpus calls without C5 remain gaps. Combined corpus/pillar/withholding checks: 11 tests pass. No provider request or private words were exported.
- Changed-file ESLint and app typecheck pass.
- Bounded temporary Next preview and Chromium run through `ac-heavy`, then stop. At 390 and 1440 pixels, light and dark: six Story sections, eight collapsed skills, source selection, coaching link, legacy view switching; six Prospect sections, lock/contradiction and qualification gaps. No overflow, page errors or external requests. Prospect fixture makes no API requests.
- Fictional browser receipts/screenshots remain outside Git at `/home/acdev/strikes/1677/shots/report-story-current` and `/home/acdev/strikes/1677/shots/prospects-current`. Phone light and desktop dark Story screenshots were inspected.
- Acquisition browser selectors retain the original Moments tab, matching the owner's correction. Full compiled journey remains a CI check, not a claimed local proof for this head.
- Restored PostgreSQL detection/team tests and backend lint/type checks are recorded in `prospect-detection-team-20261010.md` and the strike notes.

## Boundaries still awaiting integration

This change does not claim universal post-C5 scheduling, hosted provider activation, instant server-loaded saved calls, or a Companies identity/list. Detailed Root/Strike A/Strike C handoffs are in `/home/acdev/strikes/1677/NOTES.md`. C5 candidates remain behind AC-SVAL gates. Company schema needs the shared migration slot. Hosted authenticated proof is unavailable behind Cloudflare Access; local fictional/corpus proof is not deployed evidence.

## Server-fact refresh follow-up

Key facts immediately withhold the old prospect's values and edit controls when a link-change/refresh event occurs; the refreshed link and profile must be read before edits return. The stale-link regression passes. Loading uses the same six-field grid rather than a short block, with 32/44 px placeholders and confirmation controls. Transcript-search gaps say no supported mention was found; they do not claim that an undetected price, time or number was never spoken. Fourteen focused facts/profile tests, typecheck, changed-file ESLint and the repeated 390/1440 light/dark browser proofs pass. The temporary preview was stopped.
