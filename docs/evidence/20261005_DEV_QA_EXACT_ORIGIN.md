# AUT-1232: exact HTTPS dev QA transport

The protected saved-report invocation passed through the existing dev UI at
17:21 UTC. The latest verification is recorded separately below.
The candidate uses the Admin QA launcher's existing ephemeral loopback TLS
transport with the fixed Sales Xray dev host and edge port. Chromium supplies
its actual HTTPS Origin and stores the normal Secure host-only cookie. No
request header overrides or injected sessions are used.

## Reproduction and live proof

The parent's 16:38 UTC login/workspace 503 observation remains a recorded failure;
its cause was not inferred. A fresh Chromium reproduction at 17:04 UTC used the
previous `http://localhost:3016` invocation and API Origin override: normal
password login returned 403, canonical workspace returned 401. A fictional
sentinel probe returned `request_origin_denied`. No authenticated report read
was claimed for that invocation.

At 17:21 UTC, the checked-in candidate used the actual browser origin
`https://salesxray-dev.authorityclosers.com`, resolved privately to its temporary
TLS listener, forwarding to the unchanged edge on `127.0.0.1:3016`:

| Check                       | Result                                   |
| --------------------------- | ---------------------------------------- |
| Fictional nonexistent login | 401 `password_credentials_rejected`      |
| Existing UI password form   | 200                                      |
| Canonical workspace         | 200; person present; one workspace       |
| Session cookie              | Secure, HttpOnly, host-only, path `/`    |
| 1440x900 report route / API | 200 / 200; ready overview visible        |
| 390x844 report route / API  | 200 / 200; ready overview visible        |
| Report binding              | Exact approved submission at both widths |
| Horizontal overflow         | None at either width                     |

Only the approved fictional report
`dadaed4c-2f24-4299-b2fa-c0c47f9b374a` was read. The credential came from the
existing protected AUT-1116 handoff, into memory, then through the current UI's
password form. Browser environment excludes agent and provider credentials.
Nineteen unsupported/background requests were aborted by the fixed request
fence. Report/transcript text, speaker details, cookies and credential values
are absent from the receipt. No screenshots containing report data were saved.
Temporary browsers, profiles and TLS files were removed.

## Serving source

- Active `acdev-xray-dev.service`, PID 1035608, working directory
  `/home/acdev/src/lanes/ui/authority-closers-platform`.
- Serving checkout: clean `main`, `26a4fb55a9e9d3cb9efdec0eb7d2af8116937837`.
- Speaker component SHA-256:
  `8983c209132b4bf7adec004fcef7a1924ddffd5cf18cde22875fa381ccc05eaf`.
- QA launcher SHA-256:
  `5252660f8b96da5c445d2fd62629fad944f8d94f1ff59ef880c9edf64c965b33`.
- Unchanged edge configuration SHA-256:
  `dd441e3de5aa9bca1e81ccee9737bf9e51d16242aa83d1dad9d595b615263dc5`.
- Existing upstream Host: `salesxray-staging.authorityclosers.com`; the edge
  retains the actual dev Origin, under the existing AUT-154 studio contract.

The serving UI checkout was read only. No Caddy, service, host, account/grant,
database, origin allowlist, provider, report data or external setting changed.
This is the existing approved staging-backed dev studio QA, not independent
dev-database provisioning or a staging release repair.

## Validation and delivery

Ruff lint and formatting pass for both launchers and the new tests. The focused
test command passed **221 tests**:

```sh
.venv/bin/pytest -q tests/infra/test_dev_sales_xray_qa_transport.py tests/infra/test_dev_qa_credential_transport.py tests/unit/http/test_sales_xray_auth.py
```

Coverage includes real loopback TLS byte forwarding, correct certificate host,
wrong Host/Origin rejection without rewriting, preserved Secure cookie headers,
encoded Turbopack assets needed for form hydration, denied encoded API paths,
other-report and write fences, private credential-file metadata and browser
environment isolation. Existing Admin credential/launcher and Sales Xray origin
security contracts also pass. The existing FastAPI test-client deprecation
warning is unchanged.

Candidate debugging found missing host Chromium libraries when filtering its
environment and encoded Turbopack chunks blocked by the initial request fence.
The final invocation passes the non-secret shared-library path and only the
observed bracket/@ encodings under `/_next/static/`; API encoding stays denied.

`ac-gate check` permitted the task branch. Sensitive CTO review, CEO merge
approval, CI and released-main read-back remain required before this task is
done. Dev Environment Lead owns that final read-back. The runbook publishes the
same source-owned command and rollback; no persistent runtime rollout is needed.

## Latest verification (supersedes current-availability claim)

At 17:27 UTC, a repeat of the final candidate with the added debug-log refusal
reached the correct dev origin, but the fictional sentinel received HTTP 503.
The launcher stopped before reading any credential or attempting a real login.
This is a new observed upstream/runtime failure; its cause is not inferred.
The 17:21 successful report proof above is retained, not reclassified. Current
runtime availability and final released-source acceptance remain incomplete.

The final code also refuses `DEBUG`/`PWDEBUG` before starting Playwright, whose
API logs can include filled password text. Both negative tests pass. The final
221-test result and PR lane/file gate are green locally. Sensitive review and
CI continue; final acceptance must use a fresh successful released-main receipt,
not the earlier candidate receipt or the latest failed one.
