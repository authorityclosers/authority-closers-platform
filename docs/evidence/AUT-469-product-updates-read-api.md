# AUT-469: Product update and notification reads

Implements P2 of [AUT-433](/AUT/issues/AUT-433#document-plan), under the accepted
[AUT-423 policy](/AUT/issues/AUT-423#document-plan) and ADR 0054.

## Implementation

- Sales Xray host routes: `GET /v1/updates`, `POST /v1/updates/seen`,
  `GET /v1/notifications`, and `POST /v1/notifications/read`. Each requires a
  signed-in person, without a selected-workspace or tenant restriction.
  Success, authentication, host, origin and validation responses are private
  and not cached. Both POSTs use the existing safe-origin guard.
- The highest published lineage version is visible outside development;
  development selects the newest version, marking unpublished rows as drafts.
  Audience and feature checks apply to the selected version. Registered
  organisation owner/admin memberships are checked across the person's
  workspaces; testers use the live `InternalTesterPolicy` account scope.
  The feature registry starts empty and unknown features hide notes.
- First publication orders published lineages, while first creation orders
  development drafts. `since` filters by first publication, excludes lineages
  that have never been published, and leaves the unseen badge count unchanged.
  The updates feed returns at most 100 notes.
- Append-only seen receipts use a person/lineage conflict-safe insert. Release
  entries are built from all visible notes when read, without fan-out. Event
  reads are recipient-scoped and set `read_at` only when it is null. The bell
  returns at most 50 entries, with a badge count over the full visible feed.
- CTO retention decision recorded in the privacy inventory and ADR: retain
  seen/notification rows for the person's lifetime; an approved person erasure
  must remove them in the same transaction using a future approval-scoped
  trigger bypass. This change adds no migration or erasure path. Corrected the
  inventory to migration 0075 / parity v46 and the P1 evidence to 0074→0075.

Scope adaptation: current main discovers route installers, so the small new
`http/routes/product_updates.py` adapter installs beside the existing
app-updates module instead of editing `http/app.py`. The existing optional
PostgreSQL integration file was extended. Production changes are 373 lines,
including the installer; the additional scope is tests and required evidence.

## Verification

- `uv run --frozen pytest tests/unit/http/test_app_updates.py
  tests/unit/http/test_app_composition.py tests/unit/http/test_route_registry.py
  tests/unit/product_updates tests/unit/http/test_product_updates_http.py
  tests/database/test_product_updates.py -q`: **209 passed**.
- `uv run --frozen pytest tests/integration/test_product_updates_postgresql.py -q`:
  **4 passed**, using the lane's disposable PostgreSQL database and isolated
  schemas. The real migration seeds all six notes; a new fictional person reads
  them in order through HTTP and acknowledges their release. Concurrent posts
  create one seen receipt; another session of the same person sees the result,
  while a different person retains all six unseen notes.
- `uv run --frozen ruff format --check packages/python tests`: passed.
- `uv run --frozen ruff check packages/python tests`: passed.
- `uv run --frozen mypy packages/python`: passed, 424 source files.
- Unit coverage also proves audience admission/denial, absent/stale tester
  policy, feature hiding, version selection, first-publication `since` behavior,
  validation, wrong-host refusal, safe origins, privacy headers, grouped release
  read state, unknown IDs, recipient isolation and limits without badge truncation.

All inserted people, notes, memberships and notifications are fictional. No
external provider, deployment, credential or customer-data mutation was used.

## Dev check after deployment

The unauthenticated baseline request to
`https://salesxray-dev.authorityclosers.com/v1/updates` returned HTTP 403. No
signed-in dev check is claimed. This slice does not change the web rewrite list.

After the release reaches the backend serving dev, use the staging test account
through its existing authenticated proxy: `GET /v1/updates` returns the six seed
notes for an account without seen receipts; `GET /v1/notifications` contains the
one six-note release. Mark the release read with a safe Origin, then verify a
second session of that account shows zero unseen notes. If the browser rewrite
is not yet present, use the existing authenticated QA route or complete U1's
rewrite follow-up. Merge/deployment and this authenticated check remain outside
the implementation receipt until independently verified.
