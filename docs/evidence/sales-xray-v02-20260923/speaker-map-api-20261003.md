# AUT-311 S3: private speaker-map API

Source: AUT-311 plan rev 3, AUT-317 card and ADR 0042. The latest lane gate
started `task/sales-xray/311-speaker-map-api` from main `8b07d119`, after
PR #248 merged. This bounded slice exposes only the two speaker-map routes;
its 686 added lines comprise 184 implementation, 453 tests and 49 evidence lines.
The two-line storage restriction follows the CTO's explicit S3 review direction.
Report input/basis, model naming, web wiring and two-channel work remain later slices.

- GET requires a signed-in claimed-call owner, uses the account profile and
  server C2 projection, and returns the exact v1 keys. Missing C2 is unavailable
  with no speakers. Ownership and corrupt/stale C2 failures stay errors.
- PUT uses the same owner transactions, recording lock and scope recheck as
  S2b, existing strong revision ETags, JSON only, an 8 KiB bound and a five-second
  deadline. Owner/tenant/unclaimed/guest denials become 404; unsafe origins stay 403. User-supplied names, roles, extra fields and transcript/revision fences are
  validated. Unattributed speech must have role `other` and no name. Rename
  errors use speaker wording and the 80-character limit.
- Current user choices supersede predictions. Old-transcript choices are ignored
  while their ETag still fences the next append. Identical retries remain no-ops.
  Each new revision has one revision-only audit event. Report basis remains null.

Checks on the dev host, using fictional data and disposable loopback schemas:

- Predictor, store, service, call-name, learner-acquisition and summary unit suites:
  **167 passed**. New HTTP suite: **3 passed** (real cookies/transactions/ownership,
  simultaneous conflicting saves, current/default/renamed/swapped roles, stale
  transcript recovery, exact JSON key sets, exact 8 KiB acceptance, 413/415/422,
  five-second timeout and client disconnect). Speaker and call-label PostgreSQL
  regressions: **12 passed**, including actual lock waits and rollback/erasure proof.
- The HTTP proof uses a fictional C2 at the existing authorized renderer boundary;
  the missing-transcript case uses the real renderer. No provider or real call is
  accessed. Full row snapshots of every other `conversation_*` table stay equal
  across the successful and rejected writes: no task, plan, report, minutes,
  payment or usage change. Three revisions produce exactly three content-free audits.
- Ruff format/check, mypy, Prettier (Markdown) and `git diff --check` pass.

Dev check: https://salesxray-dev.authorityclosers.com (healthy redirect); API
`/health/ready` is 200 with the configured host. Its running process currently
returns 404 for the new route; live authenticated route verification is outstanding.
No systemd, staging, production or deployment change was performed.

Once the normal dev API lifecycle loads this head, sign in with a fictional
account and claimed call. GET `…/submissions/{id}/speaker-map` before C2 (200,
unavailable, empty speakers), then with C2 (predicted, profile-aware names).
PUT the complete speaker list and current transcript revision with the GET ETag;
check confirmation, rename and a changed `you`, then GET again. Repeat identical
content with the old ETag (200/no-op), send changed content with it (409), and
check another account/guest (404). Reports/usage must stay unchanged. No new UI
behavior is claimed; report/model wiring is S4/S5.
