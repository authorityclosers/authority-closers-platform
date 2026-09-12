# UI recovery checkpoint — 2026-09-11

This checkpoint restores reliable local learner, Coach and Admin access and
finishes deterministic next-action guidance. It is an explicit source checkpoint
for release reconciliation, not a deployment or whole-course acceptance claim.

## Preservation and source authority

The only product implementation tree is
`C:/Users/Suyash/.codex/worktrees/d2de/authority-closers-platform`, existing branch
`codex/v02-alpha-latest-ui-20260911`, starting at
`cb8df7b44fc79144a6697a77966f4a4c6088932f`. Saved main and competing candidate trees
were not reset, switched or edited. All 1,172 original dirty/untracked files
were hashed before work; the 2026-09-11T07:18:43Z recheck found zero differences
and zero missing files. User assets, generated files and historical evidence
remain preserved.

Controlled sources were fetched by exact manifest IDs in the required order:
Master Index, BRD, AC-IMP-00/01/03/04/05, all fourteen first-slice domain sources,
and AC-UXA-01. The compact read register is in the recovery packet below.
Requirements are BRD Q037 and BR-014/015; AC-IMP-04 sections 5/10/13;
WRK-G0-006/021, WRK-G1-003; and UX-G02/04/09. Controlled sources remain
authoritative for business semantics.

## Exact checkpoint scope

The recovery packet's `ui-checkpoint-paths-20260911.json` names 46 literal paths:

- 13 next-action implementation, tests and evidence files;
- 16 coordinated Next 16.3.3 / sharp 0.35.4 dependency, privacy-policy, tests,
  authentication-boundary lint annotations and documentation files;
- 12 local startup, loopback transport, privacy, lint-repair and evidence files;
- four Studio UUID pages/tests already aligned with inspected current main;
- this superseding checkpoint evidence.

The checkpoint begins on broader Studio/UI/0029 ancestry. It cannot be described
as a 46-path release against main without comparing final bytes with the exact
release baseline. The old PR47 merge-base diff includes squash ancestry and is
not a safe copy allowlist. Release owns that reconciliation, scanner/controllers,
the prepared 0027-to-0029 rehearsal, CI, packaging and deployment.

Existing scanner/rehearsal files remain frozen under separate SHA256 manifests.
Generated Next declarations, AGENTS/CLAUDE files, user documents, local screenshots
and unrelated media fixtures are not silently staged with this checkpoint.

## Verified behavior

The managed launcher restored isolated API/PostgreSQL and sequentially started
learner 3100, Admin 3101 and Coach 3102. All login routes return 200; anonymous
`/v1/me` returns 401 with private/no-store and no Set-Cookie. All three login pages
passed keyboard email-to-password focus and 320/1440 reflow checks. Six genuine
screenshots are retained in `ui-readiness-20260911T065744Z`.

Home and course now share the canonical next-action selector. Only required,
available/in-progress, action-enabled work can be selected by modern responses;
explicit null remains null. Requiredness includes both module and activity.
Old responses retain a returned-order, action-checked fallback. The API pointer
is guidance; it grants no completion, access, score, mastery or reward.

Normal local synthetic learner login proved collection/detail pointer agreement
and keyboard continuation from both home and course to the same canonical Watch
activity. Sixteen screenshots cover home/course, 320/390/768/1440 CSS pixels, and
light/dark set through the app's Appearance control. Effective theme was asserted.
No horizontal overflow or page errors occurred. The final proof is
`next-action-browser-20260911T071420Z/proof.json`. Mobile and desktop images were
visually inspected. This checks those routes and interactions, not all WCAG
criteria or complete course delivery.

Earlier harness failures are retained and superseded: Node-side localhost API
resolution was replaced with same-origin browser fetch; a hidden desktop link
was excluded from the mobile locator; browser OS-dark preference alone correctly
left the intentional default light theme unchanged. No product code was altered
to disguise those failures.

## Executed validation

- Launcher/bootstrap tests: 32 passed.
- Focused next-action frontend tests: 157 passed across four files.
- Domain/API tests: 29 passed; actual disposable-schema PostgreSQL integration:
  two passed (31 total). The integration verifies review gating and unlock.
- Learner TypeScript, scoped ESLint, Ruff and diff whitespace checks: passed.
- Independent next-action review and rereview: no remaining P0/P1/P2 findings.

The first broader frontend invocation used the repository working directory;
1519 tests passed and nine playback cases failed resolving app-relative CSS.
That harness run is not counted as a passing suite. The corrected invocation
uses each app's package working directory and serializes suites with one worker.
Its final results follow.

### Final broader checks

- Learner: 84 files / 1,528 tests passed; full TypeScript and ESLint passed.
- Admin: 28 files / 636 tests passed; full TypeScript and ESLint passed.
- Coach: three files / 40 tests passed; full TypeScript and ESLint passed.
- Total: 115 frontend files / 2,204 tests passed, serially with one worker.
- Repository frontend Prettier check: passed.
- Local staging bridge tests: 10 passed.
- Changed learning HTTP/domain source mypy: passed, two source files.

Logs are under `ui-checkpoint-validation-20260911T072008Z` (learner and Admin
tests/types, learner lint), `ui-checkpoint-validation-20260911T072626Z` (final
Admin lint), `ui-checkpoint-validation-20260911T072638Z` (Coach tests/types), and
`ui-checkpoint-validation-20260911T073025Z` (final Coach lint).

Full lint with Next 16.3.3 found four new warnings on literal internal
`window.location.assign` calls at confirmed Admin login and Admin/Coach logout.
The existing full-document transitions are intentional across authentication
boundaries; they reconstruct document/client route state after cookies change.
Four narrowly scoped, explained ESLint annotations preserve that runtime
behavior. Server authorization remains the enforcement boundary. Independent
review found no defects in these comment-only changes.

The formatter found residual parameter-list formatting in the previously dirty
`local-api-upstream.test.ts`, after its historical unused callback removal. Before
whitespace correction, exact original bytes were archived as
`local-api-upstream.test.original-20260911.ts` in the recovery packet, with SHA256
`981819c7f4f8c0ae02b5663a3541ab9e24d11f07445cb04968c75ce09dbd95e0`.
Independent comparison confirmed only parameter-list reflow and trailing-comma
removal since that archive; the body and assertions are unchanged. This is the
single intentional original-file byte change since the zero-difference
preservation checkpoint above, and the original remains recoverable.

## Evidence, rollback and remaining gates

The compact local recovery packet is
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery`; it contains
the preservation inventory, controlled-source register, literal path allowlist,
transfer hashes, reproducible probes, JSON checks and unedited screenshots.
The active vault note is
`D:/Projects/authority-closers-engineering-vault/01-Implementation-Logs/AC-IMPLOG-2026-0911-ui-recovery-next-action.md`.
No credential values, cookie exports or customer data are included.

This source checkpoint requires release-owner reconciliation, exact CI/artifact
identity and applicable migration/backup/rollback gates before promotion.
Rollback is a reviewed revert of the isolated next-action/source commits and
redeployment through the canonical release controller; no manual SQL recovery
or history overwrite is introduced.

Scanner-dependent upload, processing/retry, private preview, publication and
authorized learner playback still require functional scanner and media proof.
Full-length/large/4K fixtures, captions and published Dipak instruction are
separate acceptance obligations. Fresh enrollment, complete learner
draft/review/retry/completion, Coach diagnostics and operational telemetry remain
bounded follow-up acceptance work. No autonomous scoring, real-call processing,
payment/access change, provider activation or production promotion occurred.
