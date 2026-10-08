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
    "business": {"kind": "text", "text": "Fictional Ltd"},
    "city": {"kind": "text", "text": "Jaipur"}
  }
}
```

Response schema: `ac.sales-xray.prospect-fields/1`, with `field_registry` and
`prospect`. The prospect has its shared `revision` plus `profile_fields`, a map
containing all 14 registry keys. List/detail expose the same map and registry.
The existing `fields` array remains compatible and contains additional known
person fields; `contact` and `next_step` now use stored values.

Representative entries from `prospect.profile_fields`:

```json
{
  "business": {
    "state": "known",
    "value": {"kind": "text", "text": "Fictional Ltd"},
    "basis": "person",
    "locked": true,
    "set_by": "<signed-in-person-id>",
    "set_at": "2026-10-09T00:00:00+00:00"
  },
  "industry": {"state": "unknown", "reason": "not_asked"}
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

Pending final test results. Fictional data only; no staging/production state or
provider activation. The public dev Prospects URL returns HTTP 302 to sign-in.

Dev API check after migration: create/link a fictional prospect, PUT Business and
City, GET its detail from a second session in the same workspace and confirm the
same `profile_fields` values and person/date metadata. Unset fields must be
explicit unknown. The editing widgets and their phone/laptop presentation belong
to Cards B/C; they are outside this backend card.
