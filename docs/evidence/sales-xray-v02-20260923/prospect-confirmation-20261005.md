# AUT-1069 prospect suggestion and confirmation API

Source pin: `ce753781ba69f9b2e74b9300619473173bab2be1`; branch `task/sx-prospects/1069-prospect-confirmation`.

Scope decision: retain one feature card for the API, source/privacy projection, confirmation control and integration proof; these acceptance checks exceed the 300-line target without introducing a second feature. The spec permits this feature control in the sx-prospects checkout. No schema change is required.

All endpoints require a signed-in session on the configured Sales Xray host and its currently selected, served workspace. Request data cannot select a person or workspace. GET responses and errors are private/no-store and vary by Cookie. Writes require an allowed same-surface Origin and a bounded application/json body. An organisation-wide reader cannot link another person's call or prospect.

## Requests

- `GET /v1/conversation/prospects/calls/{submission_id}/suggestions?offset=0`: bounded scan of 100 retained, authorised, own call memberships in newest receipt order; `next_offset` permits older history. Fixed batch-query count; no per-prospect reads.
- `POST /v1/conversation/prospects/calls/{submission_id}/create`: `{ "display_name": "Mehta Example" }`. Returns 201 with a new stable prospect UUID and first audited membership. Already-linked calls return 409 without creating a second prospect. Names remain person-entered and non-unique.
- `POST /v1/conversation/prospects/calls/{submission_id}/confirm`: `{ "prospect_id": "22222222-2222-4222-8222-222222222222", "expected_membership_id": null }`. The expected membership field is required. Null means no active link; replacing a link requires its exact UUID. Returns 200. Confirming an already-active target returns the same membership with no duplicate link or audit event. A stale competing target returns 409; replacements append a membership and supersede the prior one.

Unknown/foreign calls or prospects return 404, unserved workspace 403, absent session 401, unsupported selectors/invalid bodies 422, wrong content type 415, over 2048 bytes 413. Creation and confirmation run inside the authenticated transaction and the store's recording/identity fences. Existing source erasure and retention rules apply.

## Final JSON shape and fictional example

This is an illustrative fictional response, not live customer data. `previous_call_at` is the stored acquisition receipt timestamp, not an inferred conversation date. Company/industry/team_size/role are literal source-supported details. Suggestions compare matching keys and case/whitespace-normalized text; the value must occur in its transcript quote on a prospect-attributed segment. No name lookup, identity inference, confidence, score or voice processing runs. An empty or unavailable source produces an empty suggestions array.

```json
{
  "schema": "ac.sales-xray.prospect-link/1",
  "submission_id": "11111111-1111-4111-8111-111111111111",
  "membership": null,
  "suggestions": [
    {
      "prospect_id": "22222222-2222-4222-8222-222222222222",
      "name": "Mehta Example",
      "previous_call_at": "2026-09-28T10:00:00+00:00",
      "kind": "shared_stated_details",
      "confirmed": false,
      "details": [
        {
          "key": "company",
          "text": "Fictional Studio",
          "current": {
            "submission_id": "11111111-1111-4111-8111-111111111111",
            "snapshot_id": "44444444-4444-4444-8444-444444444444",
            "snapshot_kind": "c5_checkpoint",
            "source_revision": 1,
            "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "run_id": null,
            "transcript_revision": "fictional-second-call",
            "evidence": [
              {
                "segment_id": "s1",
                "quote": "I run Fictional Studio.",
                "start_ms": 0,
                "end_ms": 900
              }
            ]
          },
          "previous": {
            "submission_id": "55555555-5555-4555-8555-555555555555",
            "snapshot_id": "66666666-6666-4666-8666-666666666666",
            "snapshot_kind": "retained_c5",
            "source_revision": 1,
            "source_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "run_id": "77777777-7777-4777-8777-777777777777",
            "transcript_revision": "fictional-first-call",
            "evidence": [
              {
                "segment_id": "s3",
                "quote": "I run Fictional Studio.",
                "start_ms": 2000,
                "end_ms": 2900
              }
            ]
          }
        }
      ]
    }
  ],
  "next_offset": null
}
```

Successful confirmation (creation has the same shape and status 201):

```json
{
  "schema": "ac.sales-xray.prospect-link/1",
  "submission_id": "11111111-1111-4111-8111-111111111111",
  "membership": {
    "membership_id": "33333333-3333-4333-8333-333333333333",
    "prospect_id": "22222222-2222-4222-8222-222222222222"
  }
}
```

## UI and verification

The existing standalone report displays a Prospect history control only after session/workspace admission. Matching quotes link to both calls; Confirm writes only after a click. A successful write links to `/prospects/{UUID}`. The create form handles the first call. Context changes unmount/abort prior requests; conflicts require reload.

Initial six fictional PostgreSQL cases and six control tests pass. Full Python Ruff and mypy checks, app lint/typecheck and changed-file Prettier pass. Query instrumentation observes exactly 46 SQL statements for empty, one-candidate and two-candidate histories, including authentication and retention fences. Final regression/CI results are recorded on [PR #364](https://github.com/authorityclosers/authority-closers-platform/pull/364) and the owning issue; authenticated runtime acceptance remains Root-owned.

Dev baseline: `/prospects` redirects to sign-in (302); unauthenticated loopback API check for the new suggestions route returns 404, so no live backend or authenticated visual acceptance is claimed. After governed merge and normal delivery, Root uses the fictional [AUT-1116](/AUT/issues/AUT-1116) accounts on dev, then staging: create/confirm through the app path, verify the list/detail call/report links, and verify a second per-task account receives 404 for that prospect UUID. Phone/laptop checks remain Root's live follow-through on [AUT-1219](/AUT/issues/AUT-1219). [AUT-313](/AUT/issues/AUT-313) remains gated.
