# Retained held-call recovery

Base: `fc7dc8687ba137f8bab35a99f9734db84093a460`.

A retained call with completed local checks and transcription could reload into
`held` with no visible continuation action: polling cleared the error, stopped,
and never reached automatic quoting. The existing error-panel fresh-plan action
was therefore unreachable in this ordinary paused state.

The paused panel now offers **Review a new analysis plan** only when the latest
C2 stage is completed, local checks are completed, and the submission is held.
It uses the existing owner-authorized quote endpoint and confirmation panel.
The displayed provider/privacy/cost plan must be explicitly accepted before a
start. An older completed C2 does not qualify when a newer C2 is uncertain.
The existing operation lock prevents duplicate requests. All fresh-plan entry
points respect the current service pause.

## Source and contract delta

- `apps/sales-xray-web/app/acquisition-studio.tsx`: eligibility and action only.
- `apps/sales-xray-web/app/acquisition-studio.test.tsx`: six new recovery cases,
  with existing failed-local-check and uncertain-transcription assertions kept.
- No API, identity, database, worker, provider, quota, cache or contract changes.
- No source reset, session recreation, upload, automatic retry, budget release,
  or manually modified hosted browser state.

The browser preserves the same submission and private source URL. Actual C2
reuse, authorization and budget settlement remain server responsibilities;
frontend tests do not independently prove provider cache reuse.

## Local validation

Commands ran from the owned worktree using Node 24 and pnpm 11.19.0:

| Command | Actual result |
| --- | --- |
| `pnpm --filter @ac/sales-xray-web exec vitest run app/acquisition-studio.test.tsx -t 'reloaded held call' --reporter=verbose` before implementation | 3 failed because the recovery action was absent; 21 deselected |
| `pnpm --filter @ac/sales-xray-web exec vitest run app/acquisition-studio.test.tsx --reporter=verbose` after implementation | 27 passed |
| `pnpm --filter @ac/sales-xray-web test` | 156 passed in 18 files |
| `pnpm --filter @ac/sales-xray-web lint` | Exit 0, zero warnings |
| `pnpm --filter @ac/sales-xray-web typecheck` | Exit 0 |
| `pnpm --filter @ac/sales-xray-web build` | Exit 0, five static application routes generated |
| `pnpm exec prettier --check apps/sales-xray-web/app/acquisition-studio.tsx apps/sales-xray-web/app/acquisition-studio.test.tsx` | Exit 0 |
| `git diff --check` | Exit 0 |

The six new cases cover explicit acceptance after reload; denied quote with
unchanged source/allowance; service pause; later uncertain C2; missing C2; and
active processing. The acceptance case also checks no automatic POST, same-tick
double click, exact plan ID/fingerprint/privacy acceptance, retained submission,
and absence of source PUT or new-session POST.

An initial after-change test run had two passes and one test-harness failure:
the allowance selector incorrectly searched paragraphs instead of the rendered
span. The corrected test asserts the known allowance before comparing it after
denial. No product behavior was weakened to make this pass.

## Real browser, synthetic API

Isolated Chromium 145.0.7632.6 exercised the optimized build on loopback port
3028, at 1440×960 and 390×844. Four cases (desktop confirmation, mobile
confirmation, quote denial, global pause) passed **33 checks**. There were no
page errors, unexpected API/external requests, or failed static HTTP responses.
Desktop/mobile held and quote screenshots were captured and visually inspected.
The isolated server was stopped after testing; the separate Luna preview on
port 3016 remained available (HTTP 200).

The browser used synthetic API route responses and a synthetic selector seeded
only in disposable browser contexts. No real accounts, audio or providers were
used. This is UI/browser evidence, not live API, C2 reuse, or release proof.
The first browser attempt correctly rejected an invalid synthetic quote (wrong
cost label and only two stages). The second stopped on a strict selector that
also matched Next's route announcer. Both failed receipts remain beside the
final passing run; only the fixture and test selector changed.

## Receipt locations and hashes

Local audit directory: `D:/AC-authority-closers-release-audit/`.

| Relative receipt path | SHA-256 |
| --- | --- |
| `peer-held-recovery-before.log` | `10238d6e1428d7afe06ed002f3ff313348b798f7e0c948210c98579320899d47` |
| `peer-held-recovery-acquisition-pass.log` | `8732903eeb1a669a0375147b38aeed164c4b6381355c47660c430e6a7182f5ff` |
| `peer-held-recovery-web-suite.log` | `75f6f89994978f7a75ef723889f0291d6716b7e741d265378f3a8bb124eb5ee2` |
| `peer-held-recovery-lint.log` | `9f55fa4f442193f038d9ed374e8109193ef8f404f0e87c8a57c77a8f64a3aa40` |
| `peer-held-recovery-typecheck.log` | `5a3973f79ed9becd5f23c4feff467513814de7ea381d75a4d2e339aa8b8edca9` |
| `peer-held-recovery-build.log` | `6cdb835d3c4cd76ad8258dc0bc5a18e85f5456f9ba7f5ff0667a68f4b5112c17` |
| `peer-held-recovery-format.log` | `f20510a9da4717c51c4cffee6d0dd88d6c9a723d0a83711d01216f5b48961283` |
| `peer-held-recovery-browser-20260914/verified/receipt-153225.json` | `7d8701c6eed7dcf91f2f333c0a4624b548bec0877a6ebc21e6d6f26072a4d5dd` |

Browser harness:
`D:/AC-authority-closers-release-audit/peer-held-recovery-browser-20260914.py`.

## Integration and remaining checks

Local diff review checked current stage selection, operation locking, consent
binding, unchanged source ownership, pause handling, and the absence of automatic
provider execution. The release coordinator must review and integrate this
small patch into its next candidate, run CI, and exercise the actual retained
call after staging deployment. Production deployment and report verification
are not claimed by this evidence. The 95/100 scoring discrepancy remains held.
