# Server-saved prospect fields — r13 Card A (AUT-1585)

Migration `20261009_0079` follows companion-device `20261008_0078` (PR #410,
merged as `baed1ce`). Revision 0079 is reserved on AUT-1585 after verifying that
main and open PRs have no competing revision/catalogue change. It adds the append-only
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

All three catalogues map 0079 to `ac-postgres-parity-v50`, 138 unique tables,
including the four companion-device tables and new field history table. The
0078/v49 mapping and all earlier mappings remain unchanged.
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

## Integrated baseline and live verification limit (9 October)

Updated this task branch from `origin/main` after PR #410 merged; resolved the
three catalogue conflicts by retaining companion-device v49 and appending fields
v50. The tags populated-upgrade regression keeps main's historical guest mapping;
the fields test also uses historical 0077 columns, then upgrades through 0078 to 0079. No historical migration or parity mapping is rewritten.

Read-only preview inspection: both lane loopback endpoints (`3040`, `3050`) are
unreachable. The installed lane edge configuration still directs `/v1/*` to
staging. Public dev `/prospects` returns 302 to sign-in. Loopback API `8100` with
Host `localhost` reports `ce753781ba69f9b2e74b9300619473173bab2be1`, not this task.
No lane service, upstream, host setting or shared dev/staging data was changed.
Authenticated deployed API/browser verification remains a release/runtime check;
the disposable PostgreSQL/HTTP proof does not claim it.

Dev API check after migration: create/link a fictional prospect, PUT Business and
City, GET its detail from a second session in the same workspace and confirm the
same `profile_fields` values and person/date metadata. Unset fields must be
explicit unknown. The editing widgets and their phone/laptop presentation belong
to Cards B/C; they are outside this backend card.
