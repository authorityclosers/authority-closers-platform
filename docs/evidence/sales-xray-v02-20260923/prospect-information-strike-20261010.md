# AUT-1677 — Prospect Information and bounded extraction

Source: final-xray-structure-2026-10-09.md, SHA-256
`a464e69123f9a649f5f038e464d6086c6d52220b09e3e50eb24b44c6769e3110`.
The earlier Word receipt records the controlled-source fetch. Authorized AC
Orchestra Pro/Chrome and its Windows skill remain unavailable on this server.
No cloud claims, staging journey or production activation are asserted here.

The Prospect detail now has the six priority sections in the owner's order.
The first stays open; the others and opportunity history are collapsed.
Contact details/tags remain supporting information. Missing qualification,
commitment owner, date, certainty and deal-action fields stay Unknown.
A budget discussed is never converted into ability/willingness to invest.
Call interpretations retain the Inferred label and source quote.

The profile_fields parser consumes AUT-1585 / PR #414's registry/read shape.
AI-heard values carry their original quote, submission and native time range.
Person values remain locked. A differing later-call candidate gets Contradiction
and cannot replace the person value. Numeric displays retain bounds, inclusive
edges, approximation, scale, currency and period, without conversions.
Observed/Unknown are explicit. The optional changed_from read extension displays
Changed only when the API supplies an earlier value, source and earlier time;
#414 currently does not emit that extension. No Changed fact is fabricated.

People can type a field value, including phone/email, and Save and lock through
#414's PUT /v1/conversation/prospects/{id}/fields with expected_revision. The
client verifies the acknowledged person lock and reads the detail again.
There is no AI-prefilled human edit, optimistic overwrite, automatic retry or
contact extraction. A stale/failed edit keeps the draft/current value and shows
Try again through the existing corner NoticeCenter; retry refreshes first.
Legacy backend responses still open, with unsupported editing hidden.
Loading uses the existing skeleton; detail read errors are small corner cards.

The separate prospect_profile.py adapter runs only after a completed, matching
C5 draft. Its policy defaults off with a zero cost cap. A quote above the cap
stops before provider dispatch; an admitted broker must enforce its accepted
maximum and output bound. One invocation makes at most one extraction request.
Strict output parsing rejects seller/unknown-role citations, foreign fields, phone/email, duplicate keys,
invalid provenance, invented quotes/times and text values absent from their
supporting quote. Missing fields are omitted. The existing #414 field registry
validates values; its append-only writer rechecks ownership, source access and
person locks. No new tables, provider route, settings, job scheduler, charge,
score, schema or runtime activation is added. Registry import is deferred while
off, so this pending dependency cannot prevent older Reports from opening.

Verification:
- 39 focused Prospect parser/read/detail/edit tests passed; app typecheck and changed-file ESLint passed; production standalone build passed.
- Shared-slot fictional browser proof at 390/1440 in both themes: six sections,
  locked value/contradiction, units/bounds, no overflow/errors/API/external calls.
- Synthetic post-C5 adapter tests: off/non-customer/source/cost/response bounds,
  one request/write, unchanged C5; zero real provider requests.

Fictional browser page: http://127.0.0.1:3037/review-fixture/prospects.
Screenshots and proof: /home/acdev/strikes/1677/shots/prospect-information.
Hosted dev serves ui/main and has not been deployed from this strike.

Remaining dependency boundary:
PR #414 is OPEN at 59b55dcd80b64021904eb72c817d4841f1883e3d. Its migration,
prospect fields/models/store/library and HTTP files are owned by sx-prospects.
Do not duplicate or edit them while that PR is open. Inspected alternatives:
its current main predecessor has no detected origin/profile-field storage;
#414's record_detected requires an already-linked prospect; its confirm_link
only links a selected existing prospect; and current reads/edits scope to the
person who owns the prospect. Therefore automatic Detected creation, one-tap
confirmation, persisted Changed history and organisation-wide sharing cannot
be honestly activated by this standalone frontend/adapter slice.
After #414 merges, re-run the gate, integrate creation/confirmation/team reads
in that store/HTTP scope, and wire the separate extraction step with Strike C's
worker owner. Reuse the registry, append-only rows and source/privacy fences;
never auto-merge or widen source access merely because prospects are shared.
Staging calls were not read/changed: authorized retained-corpus Report proof is
in report-pillars-screen-20261010.md. New profile extraction is tested with
synthetic data only until the dependency/provider gates are integrated.

The actual unmerged #414 prospect_fields.py was loaded read-only in an offline
compatibility check: all 12 extraction keys are present, contacts are excluded,
and a synthetic source-bound main_pain value validates. No dependency files
were copied into this branch and no database/provider was touched by that check.

The existing manual call create/link control remains collapsed in Where the Deal
Stands, with the library empty-state instructions updated to that destination.
This preserves an authorized way to create/link a prospect while auto-detection
is blocked; it does not auto-confirm or merge a person. Unknown prospect roles
skip extraction before broker dispatch. Caller-confirmed speaker IDs or existing
C5 role labels bind every extracted citation; other speakers are context only.

The local compiled API/PG/browser journey failed twice at the source-upload
response wait (test line 573), before entering the Report. Both sanitized
receipts are retained in the strike folder. No upload/auth/worker files were
changed to repair this unrelated local harness limitation. CI reached the
Report/relogin journey and exposed two old Moments tab selectors; both were
updated to Moments That Mattered. Latest CI still needs to verify that repair.
The final opt-in corpus rerun passed: all 13 retained C5 outputs open.

Final frontend rerun after restoring the collapsed manual link control: 118
studio/pillar/Prospects-screen tests passed; changed-file ESLint passed.

Source-semantic audit: C5 prospect_tasks does not establish agreement. The
transport now keeps those as optional task mentions and leaves prospect
commitments empty/Unknown. Seller tasks retain the promise meaning explicitly
defined in ADR 0044. Existing report-story/1 responses without prospect_tasks
remain accepted. The separate profile adapter final focused run passed 19 tests;
ruff and strict module mypy passed.

Final source-semantic regression checks: 28 focused Python tests (19 profile +
9 story) and 20 frontend story/pillar/screen tests pass; app typecheck passes.

CI run 38037596629 passes the compiled acquisition/browser journey, frontend
validation and Python gates at 29ca3e6. Its Python formatter found one long
Moments selector; the correction preserves the exact Python AST. Changed-file
format/lint checks are repeated before pushing it.

Dependency update: PR #414 merged at 2026-10-10 08:13:43 UTC as 4885aaff4bb84b0699cbb030c2bbfed835fddd3f.
The persistence dependency is now available. Continue detected creation,
confirmation, history and team integration from that merged implementation;
the earlier OPEN dependency receipt records the situation at inspection time.
