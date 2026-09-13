# Free Course source preparation

This packet prepares a tenant-owned Coach source for the reviewed global Free
Course. It leaves the existing global catalog, enrollments, and progress rows
unchanged. Run it only after the authenticated owner has selected the
operations tenant in Coach. Session cookies and database URLs stay in the
private operator environment and are never placed in commands, receipts, or
logs.

## Frozen source manifest

The read-only staging export was validated from the current global version:

| Field | Value |
| --- | --- |
| Operations tenant | `f5386fc3-033d-4e75-a333-7774381cb4d5` |
| Public learner tenant | `206ccee8-a246-433b-b6d3-78eb21592a5c` |
| Staging source operator | `311f4bd2-7b8b-4f45-99f0-a2aed83bc95a` (`admin@authorityclosers.com`) |
| Existing global program | `a6382ab5-63f5-562c-bfa8-1bdd944194c2` |
| Existing global version | `67e08626-9b3d-50d2-b9c1-5a44645d5114` |
| Existing global video activity | `73dfbbf7-5f2c-5e88-ad27-e5c84c65690f` |
| Reviewed content digest | `ac173fbeb705c6640ad08e5febf4c692db5d16218fd9d08ca71aac68564a0440` |
| Reviewed by | `AC-IMP-04 controlled implementation baseline` |
| Reviewed at | `2026-08-28T18:30:00Z` |
| Release | `a49e4f0c2f348bedb9c34820fb681a29ddc6d16b` |
| Seed kind | `reviewed` |

The four modules and their exact order are:

1. `SHIFT 1 — Why High-Ticket Sales Is A Completely Different Game.`
2. `SHIFT 2 — “I’ll Think About It” — What Your Prospect Is Really Telling You.`
3. `SHIFT 3 — The Call Felt Great. So Why Didn’t They Buy?`
4. `SHIFT 4 — The Story That’s Stopping You From Becoming A High-Ticket Closer.`

Module 1 contains the five required activities already present in the global
version:

| Kind | Title | Prompt |
| --- | --- | --- |
| `VIDEO` | `Watch the Module 1 shift` | `Watch the approved Module 1 content: Why High-Ticket Sales Is A Completely Different Game.` |
| `REFLECTION` | `Reflect on the shift` | `Record your reflection after watching the Module 1 content. Your draft is saved so you can leave and resume.` |
| `IMPLEMENTATION_CHALLENGE` | `Implement in a real situation` | `Complete the configured offline or real-world task, then record the evidence or reflection you can support.` |
| `REVIEW` | `Review the observed pattern` | `Capture the observed pattern after the challenge without claiming certainty beyond the evidence you recorded.` |
| `IMPROVE` | `Choose the next improvement` | `Capture one explicit behavior, correction, or next action to carry into your next attempt.` |

Modules 2–4 currently have no activities. Do not invent teaching content.
Their reviewed prerequisite edges are M2→M1, M3→M2, and M4→M3.

## Create and author the staging source

The authenticated Coach owner creates exactly one tenant draft with this
request. The active operations owner role supplies the named Studio
`catalog_read`, `catalog_write`, and `catalog_publish` permissions through the
server role projection. Only the explicit platform catalog capabilities need
the already-reviewed canonical capability grant path. The frozen idempotency
key is safe to retry if the response is lost:

```http
POST /v1/admin/studio/programs
Origin: https://coach-staging.authorityclosers.com
Idempotency-Key: 83118006-a7ee-5480-884a-f731b3f2d4e7
Content-Type: application/json

{"title":"Authority Closers Free Course — Studio Source"}
```

The staging create receipt has already returned the source program
`189cec59-e302-4fe3-8215-a34c68e394a9` and draft version
`4bdddd8a-e097-42dd-80c9-884b6482da21`. Reuse those IDs; do not submit a
second create request. Save the current version `etag`, then append the four
modules in order with the current ETag after each response:

```http
POST /v1/admin/studio/program-versions/{source_version_id}/modules
Origin: https://coach-staging.authorityclosers.com
If-Match: "program-version-{latest_64_hex}"
Idempotency-Key: {frozen_module_key}
Content-Type: application/json

{"title":"{exact_module_title}"}
```

Use these module idempotency keys in order:

| Module | Key |
| --- | --- |
| 1 | `86381e01-19b5-506c-b987-03f1d56b0c73` |
| 2 | `b973b75c-6ab8-5c46-9ca9-da07a5ab480d` |
| 3 | `19498f52-a4c3-5e84-b77d-fbb119b8b78c` |
| 4 | `173eec10-6542-50c2-97ff-6d5b8411d6c7` |

Append Module 1's five activities with the same ETag discipline. Each
response must be checked for `program.tenant_id` equal to the operations
tenant, tenant scope, the requested `resource_id`, and a new ETag.

```http
POST /v1/admin/studio/program-versions/{source_version_id}/modules/{module_id}/activities
Origin: https://coach-staging.authorityclosers.com
If-Match: "program-version-{latest_64_hex}"
Idempotency-Key: {frozen_activity_key}
Content-Type: application/json

{"kind":"{kind}","title":"{exact_title}","prompt":"{exact_prompt}","is_required":true}
```

The activity keys, in the table order above, are:

```text
2661b7af-456b-5a27-813f-114f03b62ba6
e905a110-ad64-5140-ad59-820c9e5f8a27
f8b1cea4-f707-5d67-8a6f-783d29753dd4
b083911d-432d-5522-b246-4832e86ed916
bc2c0ac8-7bec-54ff-9eda-555cab722c6e
```

The HTTP authoring surface has no prerequisite route. After all modules are
created, use the reviewed source-owned command below for each edge. It
resolves the session actor server-side, calls `AsyncCatalogApplication`'s
guarded `add_module_prerequisite`, derives a deterministic edge ID, and writes
one immutable audit receipt in the same transaction.

```text
python3 -m ac_platform.catalog.cli wire-prerequisite \
  --environment staging \
  --program-id <source_program_id> \
  --program-version-id <source_version_id> \
  --module-id <module_2_id> \
  --prerequisite-module-id <module_1_id> \
  --command-id 478ccdb0-2609-59ea-8b7a-4cb8a5549ee8 \
  --reason "Copy reviewed Free Course prerequisite graph"
```

Repeat with command IDs `f7e2ee37-7338-57d3-91cf-bfb937b69f6a` for M3→M2
and `6a9dd64a-928e-5adc-97ed-b084b576a01f` for M4→M3. The receipt includes
`program_id`, `program_version_id`, both module IDs, derived
`prerequisite_id`, `status`, and `command_id`. Replaying a command returns
`status=replayed` only when its audit payload and edge still match exactly.

## Production draft

Production already has the owned draft `a1993f11-f43d-446a-821f-550bc40b950c`
with Module 1 and its five activities. Read it first, preserve its existing
Module 1 identities, and append only the three missing modules using the same
authoring route and fresh ETag after each response. Use the frozen keys
`b8f8a4a0-dd89-5179-b39b-4c7f2e7d6285`,
`efa7e69d-4dae-5987-b230-1a0153a38150`, and
`33c7f3bd-98e8-5677-b017-621ed9059434` for Modules 2–4. Do not create a
second production source. Wire the three prerequisite edges with command IDs
`6cc5db79-425d-5605-afac-d0a19de95b13`, `f9db629e-0994-58c5-8962-d6ab166285bd`,
and `3474fbb5-a08b-55fc-97de-8daea208dd97`.

The source may remain a draft for the existing-global adoption path. The
existing global version already carries its independently reviewed provenance;
adoption does not rewrite that version or fabricate a review of the tenant
draft.

## Media and existing-global adoption

After the source has the four modules and the source VIDEO activity, run the
reviewed SSH streaming uploader against the source program. It returns the
READY source `asset_id` and `version_id`; keep those receipt values private to
the operator handoff.

Then run `adopt-existing` with the exact global IDs in the manifest. The
staging command ID is frozen so a lost response can be replayed safely:

```text
AC_ENVIRONMENT=staging AC_OPERATIONS_TENANT_ID=f5386fc3-033d-4e75-a333-7774381cb4d5 \
python3 -m ac_platform.catalog.cli adopt-existing \
  --environment staging \
  --source-program-id 189cec59-e302-4fe3-8215-a34c68e394a9 \
  --program-id a6382ab5-63f5-562c-bfa8-1bdd944194c2 \
  --program-version-id 67e08626-9b3d-50d2-b9c1-5a44645d5114 \
  --video-activity-id 73dfbbf7-5f2c-5e88-ad27-e5c84c65690f \
  --public-tenant-id 206ccee8-a246-433b-b6d3-78eb21592a5c \
  --command-id 6c0295c6-9976-5d74-933e-e420f6a40d99 \
  --reason "Adopt reviewed staging global Free Course for canonical media promotion"
```

The adoption receipt is the publication receipt required by `promote-media`
and does not change any existing global catalog, enrollment, binding, or
progress row. For staging, use this frozen promotion command ID and the
`asset_id`/`version_id` returned by the READY upload:

```text
AC_ENVIRONMENT=staging AC_OPERATIONS_TENANT_ID=f5386fc3-033d-4e75-a333-7774381cb4d5 \
python3 -m ac_platform.catalog.cli promote-media \
  --environment staging \
  --publication-command-id 6c0295c6-9976-5d74-933e-e420f6a40d99 \
  --command-id d5c94ca1-f75d-5fd5-9515-4f1692dbe121 \
  --activity-id 73dfbbf7-5f2c-5e88-ad27-e5c84c65690f \
  --source-asset-id <ready_asset_id> \
  --source-version-id <ready_version_id> \
  --media-owner-person-id 311f4bd2-7b8b-4f45-99f0-a2aed83bc95a \
  --public-tenant-id 206ccee8-a246-433b-b6d3-78eb21592a5c \
  --approval-reference AC-STAGING-FREE-COURSE-20260913
```

The production equivalents use source program
`a1993f11-f43d-446a-821f-550bc40b950c`, operations tenant
`fb594dea-fdb6-444c-a36f-1d94fbc65bbf`, public tenant
`c1d51741-6e0f-4ddc-8cc4-58856d0e778f`, and the verified production media
owner `033b7038-154a-4e5a-8a23-8d5ffeec2b4b`. Use adoption command
`13f83b37-5934-5151-9abd-7348802cce96` and promotion command
`3aa3729f-65c4-53b5-83a3-fbf1a9234d32` after the production draft has its
three missing modules and the source upload is READY.

Promotion must use the authenticated source operator as media owner. In
staging that is person `311f4bd2-7b8b-4f45-99f0-a2aed83bc95a`; the personal
email person `1379f28f-88c1-49d2-ab89-31f7ed65223e` is a separate public learner
identity and must not be relabeled or merged.
