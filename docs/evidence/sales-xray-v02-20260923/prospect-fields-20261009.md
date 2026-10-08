# Server-saved prospect fields — r13 Card A (AUT-1585)

Migration `20261009_0078` follows `20261007_0077`. It adds the append-only
`conversation_prospect_field_revisions` table and the origin/confirmation/link-kind
columns needed by Card D. Existing tags, names, memberships and audit hashes are
preserved. Existing names receive a snapshot revision; this does not reconstruct
earlier labels or their history. The membership history trigger now protects
`link_kind` too. There is no business table, automatic creation or extraction.

The single registry is `conversation_intelligence/prospect_fields.py`. Text is
retained literally. Numeric values use the existing fact contract and preserve
intervals, approximation, stated scale, units and currency without conversion.
Phone and email are person-only and excluded from extractor registry output and
the public-profile projection for AI/export consumers. Report context continues
to read verified source citations, not person-entered contact values.

## API contract for Cards B/C/E

`PUT /v1/conversation/prospects/{id}/fields`, from the session's selected workspace:

```json
{
  "expected_revision": 1,
  "fields": {
    "business": { "kind": "text", "text": "Fictional Ltd" },
    "city": { "kind": "text", "text": "Jaipur" }
  }
}
```

Response schema: `ac.sales-xray.prospect-fields/1`, with `field_registry` and
`prospect`. The prospect has its shared `revision` plus `profile_fields`, a map
containing all 14 registry keys. List/detail expose the same map and registry.
The existing `fields` array remains compatible and contains additional known
person fields; `contact` and `next_step` now use stored values.

The complete fictional response is in
[`prospect-fields-example-20261009.json`](prospect-fields-example-20261009.json).
Representative entries from `prospect.profile_fields`:

```json
{
  "business": {
    "state": "known",
    "value": { "kind": "text", "text": "Fictional Ltd" },
    "basis": "person",
    "locked": true,
    "set_by": "<signed-in-person-id>",
    "set_at": "2026-10-09T00:00:00+00:00"
  },
  "industry": { "state": "unknown", "reason": "not_asked" }
}
```

Use `set_by` and `set_at` for “Set by you · date”. Missing values are explicit
unknown states. To clear a non-name field, send
`{"kind":"unknown","reason":"not_asked"}` or `not_mentioned`; this is a
person revision that prevents automation from filling the field. The name stays
a nonempty label. Omitting a field leaves its history and value unchanged.

Stale revisions return 409, including stale no-op requests. A current identical
person write is a no-op, with no audit/revision growth. Concurrent writes are
serialized on the prospect row. Audit events contain counts and revision numbers.
Foreign workspace/person writes return 404 under the existing AUT-1109 scope.

Card E can call `ProspectStore.record_detected(actor, prospect_id, submission_id=...,
fields=..., evidence=..., extractor_revision="prospect-profile/1")` inside its
transaction. Evidence is a map with one `{segment_id, quote, start_ms, end_ms}`
per supplied field. The source must be linked, owned and readable; quotes/times
are checked against retained, manifest-verified C2. This does not start providers.
Detected reads recheck call retention under source locks and apply sensitive
segment withholding. Unlinked, erased or unsupported sources disappear from the
projection while immutable revisions remain. The newest readable call supplies
an unlocked field; a person revision takes precedence regardless of later calls.
Up to five recent conflicting detections appear in `heard_differently`, each with
its source evidence. A prospect revision orders writes even at equal timestamps.

## Backup parity

All three catalogues map 0078 to `ac-postgres-parity-v49`, 134 unique tables,
including the new field history table. Historical mappings remain unchanged.
Parity proof fails closed on a missing table, changed count, extra table or
wrong migration head. This is catalogue/row-count parity, not a live restore.

## Verification

Fictional data only; no staging/production state or provider activation.

- Populated 0077 upgrade proof passed, including metadata equality, existing
  names/tags/membership preservation and unchanged audit hashes.
- 42 prospect field, tag, confirmation, report-context and historical backup
  parity checks passed. The earlier store/library suite passed 10 checks, and
  the updated name-edit concurrency/rollback check passed separately.
- 28 registry, numeric fidelity and new backup-parity checks passed.
- Required Python checks passed: Ruff format (1062 files), Ruff lint, and
  mypy (435 modules).
- PUT/detail SQL statement counts stayed at 36/23 for 1 and 20 linked calls.
  Existing list/detail reads stayed at 18/23 for 1/20/25 linked calls.
- The public dev Prospects URL returns HTTP 302 to sign-in. No authenticated
  browser or live API write was verified.

Live dev migration is blocked: the configured local database reports
`20261008_0078`, introduced by AUT-1557's companion-device PR #410, which was
not on main when this branch started. This branch's Alembic upgrade exits 255:
“Can't locate revision identified by '20261008_0078'.” Read-back confirmed the
same head and 0 prospects / 0 links. No migration was applied and no stamp or
manual data correction was made. PR #410 changes the same three backup
catalogues and occupies the shared-file slot. After it merges, resume on this
branch, update from main and allocate the next revision/parity contract before
opening this card's PR. The migration identifiers and example are therefore a
tested pre-integration contract, not a deployed claim.

Dev API check after migration: create/link a fictional prospect, PUT Business and
City, GET its detail from a second session in the same workspace and confirm the
same `profile_fields` values and person/date metadata. Unset fields must be
explicit unknown. The editing widgets and their phone/laptop presentation belong
to Cards B/C; they are outside this backend card.
