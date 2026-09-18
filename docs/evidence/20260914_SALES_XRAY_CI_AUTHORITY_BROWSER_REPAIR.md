# Sales Xray CI authority and browser repair

Base: `82cbe661f1b79db45ded5df6967fe3eba7d22cd4`. Application CI
`34841623899` failed. This leaf repairs three failing test cases without changing
product behavior or adding network-error exceptions.

The authenticated intake test now checks the existing HTTP contract: a source
larger than 32 MiB is rejected with 422 and a `source_bytes` schema error. Its
separate existing-recording capacity assertion remains 409, with no extra
recording and no broker invocation.

Saving a provider draft is not activation. The authority test now proves both an
existing quote and a newly issued quote retain the approved configuration after
a draft is saved. The existing quote can queue one task. Removing its route from
the current approval then denies another start. Expired and unavailable approval
bundles also deny issuance. The one prior task/acceptance remains unchanged, and
the synthetic broker has not been invoked.

The standalone browser fixture now installs the real execution-control routes
with its disposable operations tenant, matching current application composition.
It requires an actual availability response containing only `paused: false` with
`Cache-Control: no-store`. Previously the fixture omitted that endpoint. The
network-failure assertion and existing navigation-cancellation classification
are unchanged; no blanket availability cancellation exception was added.

## Executed evidence

External receipt: `D:/AC-authority-closers-release-audit/sales-xray-ci-authority-browser-fix-20260914.json`.

- Before repair: both authority failures reproduced in disposable PostgreSQL.
- Final authority rerun: **2 passed**, 26.45 seconds.
- Real Chromium → loopback HTTP → disposable PostgreSQL: **1 passed**, 41.48 seconds.
  The receipt records 15 checks, three successful availability reads and no
  unexpected request failures or external requests. It verifies login, workspace
  selection, private saved-report loading, audio playback/seek, measurements,
  sales factors, transcript, unauthorized workspace denial and logout denial.
- Next static export built successfully. The verified native AudioAtlas binary
  and manifest were reused; no compiler/provenance override was introduced.
- Both changed test files passed Ruff lint/format and Git whitespace checks.

JUnit and the browser network receipt are hashed in the external receipt. The
intermediate rerun's one error-message mismatch is retained, then corrected.
The browser file received a formatting-only change after its passing run.

This is local synthetic-account and pre-imported-report evidence. It does not
prove fresh provider analysis, Linux CI, staging, production, or paid execution.
No provider request, deployment, secret change, or purchase occurred in this leaf.
