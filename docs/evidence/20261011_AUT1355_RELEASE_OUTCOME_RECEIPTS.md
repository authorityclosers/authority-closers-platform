# AUT-1355: executed outcome journey and exact release CI timing

The compiled account journey passed in release PRs #468 and #469 and their main
runs. Its exact tested source saves a fictional Lost outcome through the actual
HTTP API, reloads the page, and checks the saved status, attribution and reason
in Report, Document and the downloaded Word file. This is executed integration
evidence from GitHub artifacts, rather than an assertion-source-only claim.
No application suite, build or dependency install ran locally for this analysis.

## Tested source and browser artifacts

| Release/run                                                                                                       | API head SHA                               | Actual tested source SHA                   | Browser artifact ID |
| ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------ | ------------------------------------------ | ------------------: |
| [#468 PR, 38175011583](https://github.com/authorityclosers/authority-closers-platform/actions/runs/38175011583)   | `11f52399085d6f2df074d51a8c1b79e4fc2a24a4` | `e81871b70d3bc33bd614f9b7050db987ef70946b` |         11716115369 |
| [#468 main, 38176600054](https://github.com/authorityclosers/authority-closers-platform/actions/runs/38176600054) | `fa846dc1264130e295eccc13daf6164c673c8a8a` | `fa846dc1264130e295eccc13daf6164c673c8a8a` |         11716152809 |
| [#469 PR, 38180369767](https://github.com/authorityclosers/authority-closers-platform/actions/runs/38180369767)   | `133af617e7f115c18898f101a133dc9c13185edb` | `7f6fd297ac8026c3a2d4e6c138057148ae2ce3d4` |         11717880109 |
| [#469 main, 38181177711](https://github.com/authorityclosers/authority-closers-platform/actions/runs/38181177711) | `70000783a9bbe7f9b21523f978f04a7d3084a83e` | `70000783a9bbe7f9b21523f978f04a7d3084a83e` |         11718436002 |

Each downloaded artifact contains `proof.json`,
`sales-xray-acquisition-browser-receipt.json` and
`acquisition-browser.junit.xml`. Each has exactly one passing named case, zero
skips, failures and errors, a nonempty compiled build ID, zero page errors,
zero API response interceptions and zero real provider network calls.
The JUnit case is
`tests.e2e.test_sales_xray_acquisition_browser.test_compiled_account_required_upload_profile_otp_report_relogin_and_deletion`.

All four job records explicitly show the production standalone build, required
browser journey and sanitized artifact upload completed successfully. Case wall
times in table order are 97.069, 90.430, 98.672 and 96.799 seconds. The final
local receipt retains each step's number, timestamps and conclusion, the job URL,
compiled build ID, GitHub artifact identity/digest and all three file hashes.

The test file SHA-256 is
`82b4f7db4a602e3e62afc77355cfd79190ece770d2a2068a14ae03ce2517de86`;
the browser wrapper SHA-256 is
`df0139c1ffd6379e322c8abe6318238971ebcbac28ac889cdd9a419140bf510a`.
These exact bytes match all four tested sources and the observed workbench.
PR source was verified against GitHub tree/blob identities; main source was
read from its exact local Git object. PR heads, tested merge commits and final
release merge commits are retained separately, with no interchange of SHAs.

The unconditional outcome block at test lines 929–1012 checks a PUT response
status of 200, a full browser reload, the Report's 1.1 and 6.1 status and
attribution, Document 1.1 and 6.1, and Word 1.1 status, attribution and reason.
The marker is inside the browser function's ordinary async context, with no
conditional ancestor or exception handler suppressing its failures. The browser
function is awaited, and the outer exercise is run by the passing named case.

**Receipt limit:** the wrapper uploads 24 original required assertion labels.
It omits `outcome_persisted_report_document_word` from its sanitized receipt;
raw `browser-network.json` and the downloaded Word file are not uploaded.
The outcome execution conclusion therefore combines the passing exact-source
JUnit case with the unconditional source block. It is not a claim that the
uploaded artifact explicitly contains that outcome marker or individual PUT
request path. No new artifact or historical test result was fabricated.

This is synthetic compiled integration using a disposable loopback API and
PostgreSQL database. Native socket, challenge and provider adapters are declared
synthetic. It does not establish signed-in staging/production persistence,
actual provider/native acceptance, or a usable existing QA session.

## Completed shard timing and refreshed table

Both release PRs and both main sources contain the refreshed duration table,
SHA-256 `6ddd63623b7b35f27da8f59cbe485e261bcaa899c404da9fde26278088d1a4f1`,
measured from `a775389cd07e554fa3b6c979e45f8454f49e7d3d`.
All eight setup/scheduling inputs byte-match the workbench and the corresponding
release merge: application workflow, shard runner, duration reader/table,
exclusions, conftest and both database fixture infrastructure files.
Every selected shard manifest attests those exact table bytes. The existing
duration reader validates complete unique discovery/scheduling and no
required-runtime environment skips. The table and implementation stay unchanged.

| Run                   | Job max/mean | Pytest max/mean | Job target <=1.15 | Pytest target <=1.15 |
| --------------------- | -----------: | --------------: | ----------------- | -------------------- |
| #468 PR 38175011583   |     1.065367 |        1.065976 | Pass              | Pass                 |
| #468 main 38176600054 |     1.081617 |        1.076658 | Pass              | Pass                 |
| #469 PR 38180369767   |     1.140081 |        1.163447 | Pass              | Above target         |
| #469 main 38181177711 |     1.155591 |        1.150149 | Above target      | Above target         |

These are completed shard job and JUnit wall times, not estimated table loads
or a controlled overall speedup. The exact <=1.15 bound is evaluated before
rounding; #469 main's pytest ratio is above it even though three-decimal display
would round to 1.150. The target is not consistently met across the four runs.

#468 PR used attempt 1 for shards 0–2 and successful attempt 2 for shard 3.
Its earlier shard-3 receipt reports exit 1 and one failure and remains retained.
It is explicitly superseded for timing; this is not a first-attempt pass claim.

**Count limit:** each run's suite summaries report 19,018 tests, while its XML
contains 19,006 testcase elements. All four runs have a difference of 12 in
shard 1, with cause unconfirmed. Skipped elements match their summary counts:
4,333 on #468 PR/main and 4,329 on #469 PR/main. Selected receipts have zero
failure/error elements and counts. Earlier evidence's 19,018 is a suite-summary
count, not proof of 19,018 represented or executed cases. This analysis retains
both counts and makes no all-cases-executed claim; it does not change a gate.

At capture, all ten application validation jobs are green in each run. #469
main is still packaging images, so its whole workflow and ship are not yet
certified complete. Packaging is excluded from the shard measurements.
The separate production logical-backup bound and release execution remain with
the foundation/operator; neither this receipt nor green application validation
approves a policy increase, deletion or deployment.

## Reproduction and handoff

Local receipts under `/home/acdev/strikes/1355/`:

- `owner-release-evidence-20261011-final.json`: exact source comparisons, job/artifact
  identities, counts, timing, raw receipt hashes and explicit limitations.
  The initial `owner-release-evidence-20261011.json` remains retained and is
  superseded only by the added explicit build/gate/upload step attestation.
- `measure_owner_release_receipts.py`: read-only analysis of downloaded hosted
  artifacts; no local application tests, build, installs or deployed mutations.
- `release-ci-{run}-browser/`: the three actual uploaded browser receipts.
- `release-ci-{run}-shards/`: actual shard manifests/JUnit, retaining #468's
  superseded failed attempt.
- `release-ci-{run}-run.json`, `-artifacts.json` and PR tree/blob receipts:
  source and GitHub provenance used by the analyzer.

Run `python /home/acdev/strikes/1355/measure_owner_release_receipts.py` to
reproduce the analysis against these retained inputs. Evidence is handed to
E/1694 and the coordinator through their INBOX files. No new release or PR is
requested, and this receipt does not certify current workbench HEAD.
