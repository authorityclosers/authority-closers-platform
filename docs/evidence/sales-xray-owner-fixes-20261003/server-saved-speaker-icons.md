# AUT-992 E0.3a: server storage for speaker icons

Source base: `dc93ec65ab649c03fe4fc23d4af1535b68c81738`.

The existing speaker editor and Key facts still store call edits in
localStorage. Removing their captions alone would leave the requested server
persistence unfinished. This bounded prerequisite adds the icon picker’s
presentation key to the existing audited speaker revisions; the next web slice
can move names, roles and icons together to the server.

## Behavior

- PUT speaker-map accepts an optional `icon`: null or a lowercase slug of
  1–64 characters. Explicit null clears it; an older client omitting the field
  preserves the latest same-transcript choice.
- The existing append-only revisions, ownership, transcript fences, stale-write
  conflicts, 50-revision limit, content-free audit and erasure paths apply.
- GET projects icons from the current user revision. Unattributed speech,
  stale revisions and prediction/model/channel sources cannot add user icons.
- Icon-only changes leave the report’s map hash and names-free role snapshot
  unchanged. Existing responses without icons retain their shape and hashes.
- This uses the existing JSON column; no migration or runtime data change.

## Verification

- Focused speaker prediction/store/service, private HTTP/PostgreSQL, frozen
  roles and dispatch suites: **185 passed**.
- Final changed-area rerun after adding explicit-clear/history assertions:
  **113 passed**. It proves server round-trip through a second client,
  explicit clearing in a superseding revision, retained prior icon choices,
  omission-compatible retries, invalid values and stale-write refusal.
- `uv run ruff format --check packages/python tests`: passed (934 files).
- `uv run ruff check packages/python tests`: passed.
- `uv run mypy packages/python`: passed (392 source files).
- Latest-main gate: this sales-xray branch may be worked on.

## Dev check after merge

At <https://salesxray-dev.authorityclosers.com>, use a fictional claimed call
and its existing signed-in session. GET
`/v1/conversation/acquisition/submissions/{id}/speaker-map` and keep its ETag.
PUT the same full speaker list and transcript revision with one `icon` set to
`carpentry`, echoing the ETag as `If-Match`. GET from a second signed-in browser
and verify the key. Clear with explicit null and the new ETag; confirm that
icon-only changes keep `map_revision` unchanged. An old ETag on a different
choice must return 409. Repeat on staging after the release train deploys.

The running dev API advertises speaker-map in OpenAPI (HTTP 200 with the
configured Host). Authenticated dev icon writes and staging remain unverified.
Public dev redirects to sign-in. No runtime restart, provider call or real
recording was used. The phone image is a **current dev baseline**, not a
post-change screenshot: this PR changes no screen.

- [390 px dev baseline](saved-edits-dev-baseline-390.png)
- [Browser receipt](saved-edits-dev-baseline-receipt.json)

That read-back found `lucide-book-open` on the header and More menu Transcript
controls, with zero horizontal overflow. PR #268 is merged at `b3d96c1`, but
the active dev UI checkout has not yet exposed its FileText change. The owning
UI task must preserve its current work when bringing in merged main changes.

## Remaining E0.3 work

1. Wire the existing speaker editor and live labels to server reads and
   confirmations, following ADR 0042 N8; remove the device caption only with
   that wiring. Preserve the existing picker and save-failure behavior.
2. Reuse [AUT-430](/AUT/issues/AUT-430) for append-only call facts and
   [AUT-431](/AUT/issues/AUT-431) for the facts API. Their existing cards also
   cover task ticks and the required confirmation/draft provenance. These are
   currently queued in backlog; the Chief of Staff owns admission.
3. Wire Key facts and promise ticks to that API, then remove the remaining
   device caption. Local browser preferences are separate from call edits.

Keep AUT-992 open for these steps and the later ordered owner fixes. PR #268
is merged; its visibility on the active dev UI checkout needs a separate
read-back from its merge status. This evidence makes no claim that the full
saved-on-device requirement is complete.
