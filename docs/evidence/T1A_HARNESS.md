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

Initial verification on 2026-10-01 at `057f279`: **45 tests passed**; targeted Ruff lint
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

## Review correction: observed catalogue evidence

The [changes-requested review](/AUT/issues/AUT-655#comment-a2ab508f-23b8-43b6-97aa-0a0d5ff0e07d)
identified a false pass when an active, priced catalogue disagreed with stale
pre-sale copy and the local `purchase_enabled: false` pin. Two fake-browser
regressions reproduced **0 instead of 2** on the submitted implementation,
including a buyable plan after a nonbuyable plan; both now exit 2.

Every observed `/v1/plans` response is checked before forwarding it to the page.
A browser pass requires at least one valid catalogue response. C1 §5 permits
404 without a problem body, 501, and a complete C1 409 `not_on_sale` problem;
other errors and malformed problems refuse with 2. A 404 problem body is refused
even if incorrectly labelled `application/json`.

Reader format choice: the source pins per-plan sale fields but no envelope, so
this bounded reader accepts a nonempty JSON list or a sole `items` list. Every
item must have explicit `status` and `prices`; public status is `coming_soon` or
`active`. `coming_soon` must hide prices. A non-null price object must have exactly
the four AUT-418 minor-unit fields, each null or a nonnegative strict integer.
Any `active` item with non-null prices refuses with 2, including all-null price
values, regardless of UI controls or QA's pin. Unrelated plan metadata is unused.
Empty, absent, non-JSON, malformed or unknown-shape catalogue evidence cannot
produce `plans_pre_sale` in `covered_steps`. Response bodies stay runtime-only.

Correction verification on 2026-10-01: **87 tests passed**; targeted Ruff lint and
format checks passed; the default dry-run exited 0 for `fixture_manifest` only;
`git diff --check` passed. Added tests cover API/UI disagreement, missing or
malformed catalogue data, and permitted/refused unavailable responses. Changes
remain in the four allowed files, with no dependency or environment change.
No authenticated dev run, deployed release proof or full journey verdict is
claimed. The existing CTO review and CEO approval still precede merge; QA then
verifies the runner's availability on dev through the authorized fictional setup.
