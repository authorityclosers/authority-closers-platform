# T1a harness evidence

Assignment: [AUT-655](/AUT/issues/AUT-655), plan revision
`1a76fc06-64e3-4af9-814d-9deb3d7fb3a8`. Controlling source:
[AUT-560 plan](/AUT/issues/AUT-560#document-plan), revision
`d3daabe0-54f7-4052-bd30-83bb129ef7b7`, C1 §5–6 and K;
[AUT-604 findings](/AUT/issues/AUT-604#comment-dc234b44-fff0-4ed5-869a-2f436427c299),
source `1e784afa128f8d4629aeece5179486d423c0ec52` (the machine result's
`source_pin`, not a deployed release). Gate base:
`10e95a149e334775d5322c6dda649861aa5cd88d`.

The four-role manifest proposes fictional company plus addresses; it does not
claim they exist or that sign-in preserves aliases. Root/QA owns that later proof.
Synthetic media metadata is copied from the fictional clip's `PROVENANCE.md` and
`SHA256SUMS`. This slice neither reads nor uploads media.

## Reproduce locally

```sh
uv run pytest tests/unit/test_first_paid_user_journey.py
uv run ruff check tests/journey/first_paid_user.py tests/unit/test_first_paid_user_journey.py
uv run ruff format --check tests/journey/first_paid_user.py tests/unit/test_first_paid_user_journey.py
uv run python tests/journey/first_paid_user.py
```

Offline validation emits JSON with `covered_steps: ["fixture_manifest"]` and exits
0. Fake browser tests prove target/session rejection before launch, full plus-tag
identity checks, request containment, identity mismatch before chooser fetch,
secret redaction, exact pre-sale messages, offline enablement and exits 0/1/2.
Existing Application validation includes these tests in its Python shards and
format/lint checks; no workflow or dependency change is needed.

Implementation verification on 2026-10-01: **45 tests passed**; targeted Ruff lint
and formatting passed; default CLI exited 0 with only the offline fixture check.
The approximately 300-line target grew to 680 lines across the four allowed files:
282 runner, 312 fake tests, 16 manifest and 70 evidence before this result note.
The extra lines cover containment and redaction; no product scope was added.

## QA's bounded dev run

QA supplies an already provisioned fictional Personal session at
`~/.config/ac-qa/dev-personal.json`, or selects another file **within that
directory** using `AC_QA_SESSION_FILE`. Do not put input contents in Git, logs,
comments or evidence. This task creates no config or credential file.

Input keys: `environment` = `dev`, `origin` =
`https://salesxray-dev.authorityclosers.com`, `release_id` = QA's independently
verified full deployed SHA, `email` = manifest Personal email, `person_id` = its
provisioned UUID, `offline_enabled` = expected boolean, `purchase_enabled` =
`false`, and runtime-only Playwright `storage_state`. State has empty `origins`
and secure, unexpired, exact dev-host cookies including `__Host-ac_session`.
Release not matching this local QA pin is unknown and refused before launch.
The runner does not discover or attest the deployed SHA; QA supplies that proof.

```sh
uv run python tests/journey/first_paid_user.py --environment dev --release-id "$QA_VERIFIED_DEV_SHA" --execute
```

Only `/plans` is navigated. The runner verifies the injected person through the
existing `/v1/me/workspaces` read before fetching the chooser. Allowed reads are
that route, `/v1/plans`, `/v1/billing/offline-payment`, and Next static resources
on the exact dev origin. Redirects, writes, other account pages, provider traffic,
service workers and WebSockets are blocked. No screenshots, traces, DOM, response
bodies, session state, prices or mock orders are emitted or injected.

Exit 0 means **only the recorded checks passed**; 1 means a page assertion failed;
2 means invalid or unsupported configuration/target/session/purchase mode or a
runtime error. Offline details must agree with the observed enabled API response
and include the exact sentence “After you pay, we add your minutes.” Hidden or
disabled details fail the check when enabled; visible details fail when disabled.

No authenticated dev run or full paid journey is claimed: `/plans` is absent from
the gate base, and no fictional credential was read during implementation.
QA runs the deployed check when its session and chooser are available. Full
journeys, release verdicts, provisioning and release-train gates remain later
T1b/K work. This runner never emits `Journey passed: <env> @ <release_id>`.
