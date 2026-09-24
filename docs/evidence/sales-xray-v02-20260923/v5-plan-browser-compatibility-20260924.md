# V5 plan browser compatibility and auth integration

The backend's coaching-v5 plan was rejected by the browser's v1-v4 allowlist,
surfacing the generic unverified-result recovery message before processing.
The client now accepts the known v5 revision for English, Hindi/English and
Marathi/English. Unknown revisions and incomplete metadata remain rejected.
This source defect explains a reproducible failure path, not yet the separate
failed-request reference reported by the owner.

The live-review bridge now allows the exact new Google completion-check route;
the static-export callback still avoids reading request search parameters.
Callback tests require both an exact flow and a supported result, rejecting
legacy flow-only success. The recovery CTA uses theme tokens and a 44px target.

Validation on 2026-09-24:

- 108 tests passed across report-language, call-studio, acquisition-studio and
  next.config, including all three supported report languages with v4/v5.
- After integrating the phone/dialog/password checkpoint, 32 tests passed in
  account-auth, account-profile, account-profile-client, auth/complete/page and
  next.config.
- The Google, password/email identity and consent integration suites passed all
  22 tests against a fresh loopback PostgreSQL 18.6 cluster. Three test assertions
  were corrected in 4d6c4ded: query unique person_id rather than unrelated primary
  keys, compare timestamptz instants rather than timezone-formatted strings, and
  retain previous consent metadata during ordinary sign-in without accepting new
  consent. Profile existence, absent phone verification and no unintended consent
  changes remain asserted. A transient Windows resource error on an earlier run
  did not recur in the complete serial run (84.55 seconds).
- All 50 Sales Xray frontend test files passed (434 tests) with two local workers;
  typecheck and ESLint passed. An earlier unrestricted local run exhausted Windows
  resources and did not pass; reducing worker concurrency resolved that run.
- The first successor CI run found formatter differences in three integration
  tests. They were normalized with the repository Ruff formatter; assertions and
  behavior were unchanged. Full Python lint passed after formatting. CI must run
  on the resulting successor SHA before release; f7e580e9 is not deployable.
- These are local application checks. No provider request was made and no
  production or staging release was performed by these checks. Actual hosted
  login, full viewport fit and completed v5 report quality remain release checks.

The first complete CI run on f7e580e9 passed frontend validation, Python gates,
test shards 1/2 and the capacity simulation. It failed formatting (fixed in
ad8e2d50), the Google acquisition fixture's missing full acknowledgement (fixed
in 92a1403a, including rejection of the previous incomplete input), and two
browser harness assumptions (fixed in 8571e230). The password lookup now names
the input exactly instead of also matching its visibility button. File-selection
navigation waits for either the account form or the ready action before branching;
account gating and file-retention assertions remain intact. Successor CI must
execute these tests; collection and lint alone are not browser proof.

A separate read-only Luna review of the browser plan/auth/phone/callback changes
through 8571e230 found no high or medium findings. Its scope included the six
changed frontend/config files and adjacent completion authority helpers; it did
not execute tests or establish deployed behavior.

Sanitized staging correlation for the owner's failed call found one quote 422
followed by two successful 201 quotes on the same staging release. The recording
and an unaccepted Hindi/v5 plan exist, with no completed new report. The original
422 response detail was not logged, so its exact validation cause is unresolved.
The proven frontend v5 rejection is separately reproduced and fixed above.
