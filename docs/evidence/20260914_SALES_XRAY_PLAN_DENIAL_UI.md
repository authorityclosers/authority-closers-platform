# Sales Xray plan-denial recovery

An owned call could load successfully while accepting its analysis plan returned
403 because a prior provider allowance was already used. The page incorrectly
described every 403 as a session problem and offered sign-in recovery.

The acquisition client now distinguishes 401 session recovery from 403 access
or approval recovery. For plan and quote endpoints, it translates only the exact
known allowance-denial detail into controlled user copy. Unknown JSON, HTML,
arrays and provider details produce a generic approval message. Other 403s use
generic permission copy. The error alert offers Sign in only for 401.

The page retains the uploaded call, its private audio source, saved selector,
quota and plan. Checking progress does not accept a plan, repeat an upload or
start another provider request. A fresh plan still requires an explicit action
and the existing consent flow. No API, approval, budget or runtime state changed.

## Validation performed locally

Base: `0847db5d3ca1ed825b68c226713d0f52d11683b1`.
Node 24.19.0; pnpm 11.19.0; Windows.

- `pnpm --filter @ac/sales-xray-web test`: **145 passed, 17 files**, exit 0.
  Includes three mounted-page regressions for a known plan 403, unknown plan 403
  and plan 401 after a successful owned upload. Nine transport cases verify
  exact allowlisting, endpoint scope, malformed-body handling and request flags.
- `pnpm --filter @ac/sales-xray-web typecheck`: exit 0.
- `pnpm --filter @ac/sales-xray-web lint`: exit 0, zero warnings.
- `git diff --check`: exit 0.

Receipts are outside Git in
`D:/AC-authority-closers-release-audit/plan-denial-ui-20260914/`:

| Receipt              | SHA-256                                                          |
| -------------------- | ---------------------------------------------------------------- |
| ui-tests-node24.xml  | 213e6195c739844a6b847aa8514a5ff538aafaf1d2fdecdb107313d1a19a6dc2 |
| ui-tests-node24.log  | 3cc045f069a9363fb8547784f03c3a40628be9e738a6e61445441c9f6422dbf6 |
| typecheck-node24.log | 5a3973f79ed9becd5f23c4feff467513814de7ea381d75a4d2e339aa8b8edca9 |
| lint-node24.log      | 9f55fa4f442193f038d9ed374e8109193ef8f404f0e87c8a57c77a8f64a3aa40 |

An initial local run also passed under Node 22.17.0 but emitted the repository's
unsupported-engine warning. The receipts above are the subsequent supported
Node 24 run. These are fixture tests, not new external provider calls or proof
that this leaf is deployed. The release coordinator owns combined CI, deployment
and the continuing real-recording browser test.
