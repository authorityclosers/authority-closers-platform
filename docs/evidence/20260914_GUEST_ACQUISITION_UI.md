# Guest acquisition UI — 14 September 2026

The standalone `/` route now runs the private upload-to-overview journey. It
reuses the reviewed Dipak overview, factors, transcript, brand and report styles.
The English shell keeps native mixed-script evidence intact. This packet also
adds exact local-run status and repairs an exhausted-allowance retry: only the
existing owned submission with the same source hash may repeat at zero balance.

Base: backend `4cc3cca0d6228d79beac41b0181cecf425ff3fce` and root-owned optional
account session leaf `484d300b6f23b51a63293430c60291dc9dc4ad0e` (locally applied
as `eafeaa4`). No identity/migration/provider-policy authority is added here.

## Tested here

- **107 UI tests passed**, no failures, in 5.73 seconds with one test worker.
  Includes the actual page mount, both explicit consents, idempotent retry,
  v2 source/transcript/quotation validation, mixed-script display, explicit
  post-login claim, deletion and retrying a failed widget without reloading.
- **Five PostgreSQL/HTTP tests and one compiled browser test passed** in
  **86.39 seconds**. Fresh disposable loopback PostgreSQL; no skipped cases.
- The browser loaded actual production-build Next assets, then used real TCP
  AC HTTP routes and HttpOnly cookies. **Zero AC API responses intercepted.**
  Native C1 inspection, worker scheduling, canonical C6 publication, ledger and
  account ownership were exercised. Provider responses and the native socket
  transport were explicit synthetic/local adapters; three synthetic broker
  calls and zero external provider calls occurred.
- Confirmed source upload, server duration/usage, separate provider-plan consent,
  source-bound fourteen-point overview, private byte-range playback, reload
  without retranscription, real account-cookie discovery, explicit claim,
  stranger denial and canonical deletion acceptance.
- Checked actual desktop and 390-pixel phone screenshots. The phone document
  has no horizontal overflow; report tabs retain their intentional horizontal
  navigation. A printable PDF was generated. Screenshots show a minimal
  synthetic report; they are not a real-call quality benchmark. The desktop
  entry capture records the initial file-limit loading state.
- Production Next build completed; tested build ID
  `gnMRJ4xfCU_P-m9Hh3p7i`. TypeScript, ESLint, scoped mypy and Ruff receipts are
  included. The two Python consumers pass strict mypy.

Portable evidence: `guest-acquisition-ui-20260914/receipt-index.json`.
External visual outputs:
`D:/AC-authority-closers-release-audit/guest-browser-20260914-visible/browser/`.
The artifact index records their exact sizes and hashes.

## Failures retained and resolved

The initial full UI run overlapped the production build and four tests exceeded
their existing five-second timeout. Running the unchanged assertions with one
test worker passed all 106 then-existing tests. The additional widget-retry test
brings the final passing count to 107. Test timeouts were not raised.

The first browser harness used subprocesses on psycopg's Windows selector loop,
which does not support them. Playwright now uses the platform loop in a separate
thread; all database/worker/server operations stay on the original selector loop.
A subsequent navigation waited for generic network-idle and timed out after the
real entry/policy/session responses had arrived. The harness now waits for the
document and asserts visible actionable UI states. Both failed receipts remain
in the external audit directory; neither was counted as browser success.

## Release boundary

Implemented and tested locally; no staging or production publication is claimed
by this receipt. Root release owns immutable images, current provider authority,
managed Turnstile values, actual socket/mount configuration, headroom, exact-host
tests and promotion. The local browser used synthetic challenge verification;
hosted verification must exercise the real widget and isolated helper. No paid
call, user credential access, source transfer, DNS or VPS mutation occurred in
this UI packet. Existing numeric-publication and human-adjudication limits remain.
