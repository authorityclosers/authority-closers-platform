# App update Notifications: v0.2 Alpha implementation evidence

## Scope and authority

User requested app-release updates in the existing Notifications tab. This slice
adds a real, authenticated learner app-update feed and read acknowledgements,
not marketing messages, push/email, course-progress alerts or fabricated history.
It does not claim that the wider v0.2 release, video, payments or adaptive Arcade
are deployed.

Implementation worktree: `C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform`.
Dirty candidate based on `7bdd069d4bf00561edcab90b1679666205708185`; this is not an
immutable release SHA. Existing changes remain preserved.

## Implemented path

- LearnerShell -> one AppUpdatesProvider -> bell badge/popover and the mounted
  NotificationsRuntime inbox. No route-level duplicate feed requests.
- Same-origin GET `/v1/me/app-updates`; bodyless POST
  `/v1/me/app-updates/{release_id}/read`. Runtime response schema validation,
  bounded ID/count/text contracts, owned links only, no automatic write on open.
- Package-owned immutable release catalogue; only available shipped entries in
  the running artifact are listed. The initial entry describes this inbox only.
  Future/draft/unknown IDs cannot acquire receipts.
- Authenticated active learner membership, exact learner surface, origin checks,
  no person/tenant selectors, and private/no-store on success and failure.
- Append-only receipt for `(tenant_id, person_id, release_id)`; migration0029,
  FK, uniqueness and ORM/database mutation guards. No analytics or localStorage
  as read-state authority.
- UI: concise version cards, highlights, feature links, App updates/Unread filters,
  explicit confirmation, loading/retry/session/permission recovery, bell focus
  restoration, theme tokens, reduced motion and 44px actions.
- Provider aborts on unmount/context replacement, rejects stale owner responses,
  coalesces focus/visible-tab refreshes, and never shows an optimistic read count.
- The optional authenticated staging development bridge permits only the exact
  new GET and bounded-slug POST methods without query selectors.

## Verification recorded so far

| Check | Result | Scope |
| --- | --- | --- |
| Backend catalogue/API/model tests | PASS: 36 | Agent-reported targeted suite after bounds and copy fixes |
| Real disposable PostgreSQL | PASS: 2 | Cross-session/person/tenant isolation; two-transaction receipt race |
| Backup/restore parity tests | PASS: 372 | 0029/parity-v9 added to all three explicit registries |
| Independent backend review | No remaining Critical/Important | Earlier missing parity and real concurrency test gaps closed |
| Frontend notification/API/static shell checks | PASS: 154 across five files | Intermediate candidate; later targeted fixes additionally tested |
| App update + bridge tests | PASS: 62 across two files | Precise route/method/selector restrictions |
| Visibility and navigation-mock regression | PASS: 12 across two files | Includes no unhandled mock errors |
| API receipt confirmation + inbox | PASS: 11 across two files | Validated confirmed read, stale owner, failure and retry |
| TypeScript, targeted ESLint, Ruff proof script | PASS before final review fixes | Rerun final candidate before acceptance |
| Managed local migration0029 | Applied by Start-LocalApi | Existing local database/UI preserved; no direct SQL |
| Normal-login browser run | Failed at new API403 | Retained below; proxy/host mismatch being corrected |
| Staging/production | NOT DEPLOYED | Exact candidate, environment configuration and release gates remain |

Failed first real-browser attempt retained at
`.tmp/local-platform/new/app-updates/20260910T101125107015Z/proof.json`.
Normal learner login and `/v1/me` succeeded; the app-update GET returned403 with
private/no-store. This is a real integration defect, not evidence of a usable
inbox. The final successful run must be appended rather than overwriting it.

## Remaining acceptance

Finish strict local proxy host resolution; rerun normal-login browser proof at
320/390/768/1440 in light/dark. Verify actual keyboard marking, bell focus and
read persistence after a fresh independent login. Inspect screenshots. Close
independent frontend review and final targeted gates. Refresh the release file
allowlist and exact-artifact release/restore evidence before staging and production
promotion; upload verified evidence to the established Drive release record.

## Final three-app frontend gates (append-only)

Final candidate checks used the exact bundled Node `v24.19.0` executable at
`C:\Users\Suyash\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe`.
No Next build ran and no application process was restarted by this validation.

From each of `apps/learner-web`, `apps/admin-web`, and `apps/coach-web`, the
following commands were run with that exact Node executable:

```powershell
node.exe .\node_modules\eslint\bin\eslint.js . --max-warnings 0
node.exe .\node_modules\typescript\bin\tsc --noEmit
node.exe .\node_modules\vitest\vitest.mjs run --passWithNoTests
```

| Final gate | Learner | Admin | Coach | Combined |
| --- | ---: | ---: | ---: | ---: |
| ESLint | PASS | PASS | PASS | 3/3 apps |
| TypeScript | PASS | PASS | PASS | 3/3 apps |
| Vitest files | 79 | 25 | 1 | 105 passed |
| Vitest tests | 1,490 | 579 | 14 | 2,083 passed |

The local learner proxy correction also passed its focused final checks:
Prettier, ESLint, TypeScript, scoped `git diff --check`, and 58/58 proxy tests.
The strict backend learner-host rule was not relaxed; the managed local proxy
verifies its package-owned learner origin, drops incoming Host/Forwarded
authority, and addresses the validated loopback API port through
`learner.localhost` so Node generates the canonical Host. The corresponding
backend surface tests passed 16/16 and prove forwarded authority alone is not
trusted.

One earlier parallel workspace lint attempt encountered a transient dependency
`lstat` error while the shared dirty worktree was active. It is superseded by
the explicit per-app ESLint runs above, all of which completed with exit code0.
The failed first browser attempt at
`.tmp/local-platform/new/app-updates/20260910T101125107015Z/proof.json` remains
retained and is not superseded until the corrected real-browser run is recorded.

## Local browser acceptance follow-up (10 September, 10:32 UTC)

The earlier proxy403 defect is fixed without relaxing the API's exact learner
host check. Only the managed local-sandbox proxy validates the package-owned
learner origin, strips incoming/forwarded authority, and addresses the validated
loopback API using that canonical learner hostname. Ordinary dev, staging and
production modes are unchanged. Proxy tests58, backend strict-host tests16,
TypeScript, ESLint and formatting passed on the final proxy candidate.

Successful normal-browser evidence:
`.tmp/local-platform/new/app-updates/20260910T103253552442Z/proof.json`.

- Actual synthetic learner login and canonical API, not fixture responses.
- Eight inspected layout states: 320/390/768/1440, light/dark, reduced-motion
  emulation. All document widths equal their viewport widths; actions44px.
- Initial unread count1. Opening/closing bell did not mark it read and restored
  focus. Keyboard Enter on Mark as read confirmed via actual POST200; the same
  control retained focus and became a Read receipt.
- Unread filter showed the confirmed empty state; a second fresh browser context
  signed in normally and still saw the server-saved Read state.
- GET and POST both200 with private/no-store. Zero JavaScript page errors.
- Root visually inspected phone-light and desktop-dark composition; theme inputs
  were controlled for layout proof, not proof of the Settings workflow or INP.

The intermediate `20260910T102755102533Z` run passed all eight layouts but stopped
because the proof's substring bell selector also matched Refresh notifications.
The selector was anchored to the bell name; no UI change was needed. Failed
records remain preserved and are superseded by the successful full run above.

Independent frontend re-review reports no remaining Critical/Important findings.
Visible-tab refresh coalescing, the navigation test mock, confirmed-receipt
validation and keyboard focus were reviewed; focused tests24, TypeScript and
ESLint passed. These results close the local inbox acceptance, not deployment.

Still outstanding: exact release packaging, staged and production environment
gates and actual deployed smoke tests. New migration0029
also requires the managed parity-v9 foundation/restore gate before promotion.

## Drive filing (10 September, 10:44 UTC)

Five representative screenshots and the successful proof JSON were uploaded and
read back from the existing Staging evidence parent. The new child is explicitly
labelled **LOCAL verified, not deployed**, not a live-release announcement:
[v0.2 Alpha Notifications evidence](https://drive.google.com/drive/folders/1R-2eoEHfpWKezZbXCY_OTCRUo2mTh2xl).
Parent and all six file IDs/names were confirmed by folder readback. Existing
release folders, sharing and prior failed local evidence were not changed.
