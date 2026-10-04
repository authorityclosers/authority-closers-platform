# AUT-1109: explicit prospect storage contract

Source: `d5af14fc105a1e3539e3e9ba7fc058fc10eb8c44` (latest main at gate admission).
Branch: `task/sx-prospects/1109-prospect-membership`.
Authority: CEO decision on AUT-1109, comment
`a1c8be90-3a00-44b0-8b37-3f712a6d98fb`, 4 October 2026.
The settled contract supersedes the previous identity/access question.

This is one storage foundation change. Its model, migration, reader, audited
transitions, erasure hook, backup catalogue and tests are inseparable; the
300-line target is exceeded to deliver the card's required proof. Public
list/detail endpoints remain AUT-1068; public write admission, idempotency and
match suggestions remain AUT-1069. There is no UI, report, provider activation,
backfill, billing, production or staging change.

## Persisted contract

`ConversationProspect` in `conversation_prospects` has a new UUID `id`,
`tenant_id`, `display_name`, `created_by_person_id`, `owner_person_id`,
`created_at`, `updated_at`, and `revision` (initially 1). The tenant is
`tenants.id`, including personal tenants. Names are person-entered, trimmed,
bounded to 160 characters and non-unique. A name or report hypothesis is never
an identity key. IDs have no reuse path.

`ConversationProspectMembership` in `conversation_prospect_memberships` has
`id`, `tenant_id`, `prospect_id`, `submission_id`, `linked_by_person_id`,
`created_at`, `ended_at`, `ended_reason`, and `ended_by_person_id`.
`submission_id` is the exact tenant-scoped Calls key in
`conversation_guest_submissions`, which references the recording used by
canonical source erasure. Composite foreign keys enforce tenant alignment for
prospects, submissions and people. Tenant deletion uses RESTRICT.

A partial unique index permits one active membership per tenant/submission.
The PostgreSQL trigger prevents membership deletion, changing its identity or
original attribution, reactivating it, or changing it after ending. Its only
update is a first terminal transition. New links append new UUID rows; reasons
are `unlinked`, `superseded` and `source_erasure`. Audit events retain IDs and
reason codes, never prospect names, audio, transcript or hypotheses.

## Reader and write ports for AUT-1068 / AUT-1069

Import `ProspectStore` from
`ac_platform.conversation_intelligence.prospect_store`; construct it with the
existing runtime's `GuestOwnership` and use a caller-owned `db.begin()`
transaction. Pass a current `ActorContext`; the store rechecks session, person,
tenant and membership authority rather than trusting hydrated roles.

- `await store.queries(actor)` returns `ProspectQueries.prospects` and
  `.memberships`, typed SQLAlchemy selects for API pagination and aggregates.
  Add the API's bounded limit and deterministic ordering before execution.
- `.prospects` includes rows created/owned by the reader or with a visible
  active call. It exposes no prospect from another tenant.
- `.memberships` is always filtered through `_account_library_query(actor, now)`:
  direct/claimed calls, retained permission, available recording and canary
  exclusion. `every_owner` is resolved by `organisation_call_reader`, never a
  caller-supplied flag. Only existing organisation owners/admins widen reads.
  Counts and call-derived fields must come from this select, not the raw table.
- `await store.read(actor, prospect_id)` returns the authorized prospect or
  `ConversationNotFound`. Creator/owner name-only records survive invisible or
  erased calls.
- `await store.read_memberships(actor, prospect_id, limit=100)` returns only
  authorized active memberships, ordered by descending membership creation
  time and UUID, bounded to 1–100 rows. Hidden/foreign memberships return none.
- `await store.create_from_call(actor, submission_id, display_name=...)`
  creates one fresh stable reference and initial membership. Already-linked
  calls conflict. There is no name lookup or implicit merge.
- `await store.confirm_link(actor, submission_id, prospect_id,
  expected_membership_id=...)` requires an authorized prospect and the actor's
  own direct/claimed retained call. `None` expects no active membership;
  replacing a membership requires its UUID. A retry targeting the already
  active prospect returns that membership without new audit/events.
- `await store.unlink(actor, submission_id, expected_membership_id=...)`
  ends that exact membership; stale IDs conflict. Organisation read authority
  does not grant writes to other people's calls.

Writes hold the canonical recording lock and recheck source ownership and
retention after acquisition. The partial unique index additionally prevents
duplicate active links. The storage port has no HTTP exposure. AUT-1069 must
provide its public request admission and idempotency envelope.

## Lifecycle and backup parity

Recording `deleting`/`deleted` state, revoked permission and expired retention
remove memberships from all reads immediately. `finish_erasure` calls
`end_prospect_memberships_for_recording` under its existing recording/lease
fences. It ends every active membership for every submission referencing that
recording, with a system audit event. Repeated erasure adds no duplicate ending.
The person-entered prospect name remains until later explicit audited settings
deletion. Membership and audit history remain intact.

Migration `20261004_0074` follows `20261003_0073` and is forward-only. Backup,
restore-proof and application restore-drill agree on `ac-postgres-parity-v45`,
130 critical tables, including both new tables. Historical mappings remain
unchanged. These checks validate migration identity and table row-count parity;
they do not prove a deployed full database restore or every column value.

## Verification

- Five disposable PostgreSQL cases pass: stable references/duplicate names,
  explicit creation and linking, deterministic bounded reads, creator/owner
  and shared-call visibility, direct/claimed ownership, cross-person/workspace
  denial, live organisation role narrowing, database history/uniqueness guards,
  concurrent link serialization and stale conflict, explicit deletion and
  retention erasure with an intact audit chain.
- The migration matches canonical model metadata without drift on populated
  disposable PostgreSQL.
- Backup catalogue and populated parity checks cover all three consumers,
  complete proof, missing tables, wrong counts and extra tables. Root-owned
  metadata boundary checks belong to the control-plane CI job; no installed
  host backup tools were changed.
- Changed-area regressions, Ruff format/check and mypy results are recorded in
  the PR and issue handoff.
- Fictional dev: applied `uv run alembic upgrade head` using the task-authorized
  `~/.config/acdev/database.env` (`AC_ENVIRONMENT=local`, loopback database).
  Read-back confirms head `20261004_0074`, both tables empty (no backfill),
  the partial unique/read indexes and the history trigger.
- Dev URL: <https://salesxray-dev.authorityclosers.com/calls>. Unauthenticated
  baseline returns 302; authenticated browser verification is not claimed.
  This card adds storage only. The dependent API journey remains unavailable
  until AUT-1068 integrates the reader after merge.

## Reproduce

With an explicit disposable loopback `AC_CONVERSATION_POSTGRES_TEST_URL`:

```sh
uv run pytest -q tests/database/test_prospect_store_postgresql.py tests/infra/test_prospect_backup_parity.py tests/database/test_model_registry.py
uv run ruff format --check packages/python tests
uv run ruff check packages/python tests
uv run mypy packages/python
```

The fictional creation/link fixtures live in
`tests/database/test_prospect_store_postgresql.py` and use canonical acquisition
storage with fictional measured one-second WAV data. They make no external
provider calls or persistent dev data changes. The same-tenant shared fixture
bootstraps an explicit person-attributed membership to test readers, not a
matching or identity heuristic.

After merge and dev source availability, hand this exact model/reader contract
to AUT-1068, which stays dependent on this implementation until then.
