# Learning event envelope implementation evidence

Status: bounded, additive, dormant validated projection scaffold; no deployment
or production-state change.

## Worktree and source baseline

- Worktree: `D:\Projects\authority-closers-platform-learning-event-spine`
- Branch: `codex/learning-event-spine`
- Base: `origin/main` at `e8c2780`
- No commit, push, deployment, secret, or external provider activation was
  performed.

## Controlled-source decisions

The implementation was reviewed against the exact-ID controlled source
manifest in
`docs/workflows/learner-product-v1/06-screen-family-v0.1-alpha/01-research-journeys/source-manifest.csv`.
The required source-order documents and the first-slice supporting documents
were fetched by their registered Drive IDs before editing, including:

- Master Index `1gC6BdFZ2LfjrpjM-qPKcX1qWMTUBSAXo3b-AlaOYqus`;
- BRD `1HEp7QN4u3c_636uACznnkruYHhGYHAJWXH7Dlfjybpk`;
- AC-IMP-00 `10tKbAIJWONFNTzK2-NHffy4h1wKgoQP7VdJH_K2eR-A`;
- AC-IMP-01 `1JVnCjDdE79YseM-1PuhvW00xcoicwmhoHtUvEuKKrdU`;
- AC-IMP-03 `1ncsRMiMMiQ39tCn7dV3vpqwUnirY06BgSuVdm_BuIFo`;
- AC-IMP-04 `1gQnsY1JjphpmOmfyCRZkfI-p0TWZjF1PkY1xF744Gnc`;
- AC-IMP-05 `1Vvf1wCA_JjrJQwhkTsgyDM_9179G4M899pWWc3-UdXw`;
- PRD `1vZGxiP5GRA7He0gA7oF6hmTeHqoEZUIJko_QBUtDW_k`;
- IA `1VLJTswU2sqlimfoSIROVvlJ9Z6ue-6Dd45oEcu1ddhs`;
- UX Research `1M_IlSgZwWfHVk1IU3JBzY-EhT3RIfXO07WII8MbwxPM`;
- UX States `10HzU7kLk78WBHd_Y23jYaP0rIaScq7gW27e5D7D-08E`;
- UI System `1y7yCqro9ABW8Yn61ZVmnLV8eGlelcq3BisCDTx40SsI`;
- SRS `1qE_ASXOBN-AAuIglfs4-5Fi_HN3x-jDItBYdb95Ou2g`;
- Data/Tenancy `1SUxNYTu30NXwBEbk7os1OBVn4H5qBky-LnzLuOvwaYw`;
- API/MCP `1kWawS57AGVv7jT5Kp2V0Mk8kK0B6BwPzlG6KiAOtpt0`;
- Security `1rFTiq7BI4dpLLMIDacC8qMhpAbAmOct8W_I65Ydqbmw`;
- Admin `12-VjN02jx8M7S8wJrZLcl4OwLcXIFGXKu74wxdJrWuY`;
- Telemetry `1ggdrD_ldZL3ItJsAMONq_ygQFjbR6dOURpeHGXd4M4I`;
- DevOps/SRE `1r1P2XdYSY8XhcgLR6icYqhlN1vEbqKagj8Rb16JpcJs`;
- QA/Release `1DUx9JIHNC1KCR62Qso6KTFPoBxmfhU6GSuNqSl87hBg`;
- ADR/Risk `1cNE-8DB0iX28U5IR_StkO-JGE2TPG-pbKn6LQ-bZSaY`.

The controlled event contract names `event_id`, `event_name`, `event_version`,
`occurred_at`, `tenant_id`, `actor_id`, `subject_id`, `trace_id`,
`release_sha`, and a versioned payload. The code therefore does not introduce
a separate `correlation_id`: the controlled event contract authorizes
`trace_id`, while the existing request ID remains the integration correlation
carrier. No field or event meaning is inferred from an event payload.

The controlled API catalogue authorizes the learning event names in
`LEARNING_EVENT_VERSIONS`, all at version `1.0`. The catalogue does not define
per-event payload keys, so every current learning payload allowlist is empty;
accepting domain fields remains a promotion gate. Payment, audit, unknown, and
version-drifted events are rejected.

## Delivered files

- `packages/python/ac_platform/kernel/events.py` adds a private factory for a
  bounded immutable `ValidatedLearningEventProjection` of an existing
  tenant-scoped `DOMAIN_FACT` event. The construction path is private to keep
  this scaffold dormant; it validates the shape of an integration context that
  must eventually carry the repository's authenticated `ActorContext`,
  membership, request trace, clock, and configured/baked release identity.
  These Python objects do not establish authorization.
- `tests/unit/kernel/test_learning_event_envelope.py` covers the projection
  construction path, membership/tenant/subject validation, controlled event
  registry, release/trace/clock validation, payload allowlists and sensitive
  data rejection, bounded JSON copying, cycles, immutability,
  standard/Pydantic serialization, and unchanged base-event compatibility.
- This evidence record documents the controlled-source mapping and remaining
  gates.

The projection validates a supplied tenant/membership context, request trace,
clock, and configured full lowercase release SHA (with a baked SHA match in
staging/production). It copies the existing event ID, name, and occurrence
time, checks the event tenant against the supplied membership, and derives
actor/subject IDs from the supplied self context. Payloads are plain bounded
JSON only, and current event schemas fail closed with no payload keys until the
controlled sources authorize them. It serializes the exact controlled
projection shape without adding learning meaning. Audit events, payment
events, tenantless events, unknown events, and cross-subject contexts are
rejected.

This is not an authorization or security boundary: Python in-process dataclass
constructors, private names, and validation wrappers can be bypassed by code
running in the same process. The scaffold MUST NOT be used as telemetry
authority or wired to producers, routes, outbox/export, or analytics until a
reviewed external HTTP/application boundary supplies the repository's
authenticated `ActorContext` and membership plus the baked `ReleaseIdentity`.

## Verification

```text
uv run pytest tests/unit/kernel/test_events.py tests/unit/kernel/test_learning_event_envelope.py tests/unit/outbox/test_jobs.py -q
49 passed

uv run pytest tests/unit/kernel tests/unit/outbox tests/unit/telemetry -q
68 passed

uv run pytest -q
960 passed, 130 skipped, 1 warning

uv run ruff check packages/python/ac_platform/kernel/events.py tests/unit/kernel/test_learning_event_envelope.py
All checks passed

uv run ruff check packages/python tests
All checks passed

uv run mypy packages/python/ac_platform/kernel/events.py
Success: no issues found in 1 source file

uv run mypy packages/python/ac_platform
Success: no issues found in 113 source files
```

## Explicit boundaries and remaining gates

- Existing outbox payloads, routes, dedupe behavior, and audit storage remain
  unchanged; no migration or history rewrite was introduced.
- The projection is not a canonical progress, mastery, score, streak,
  leaderboard, recommendation, entitlement, payment, or access model.
- No client-facing ingestion route, analytics read model, exporter, worker,
  consent policy, or retention policy was activated.
- Before any use, the owning event producer must integrate at an external
  HTTP/application boundary and supply the repository-authenticated
  `ActorContext`/membership and baked `ReleaseIdentity`; QA must add integration
  coverage for the selected outbox/export persistence path, tenant-negative
  cases, retry/replay behavior, privacy scanning, release identity, and
  operational recovery. Those are promotion gates, not inferred by this
  scaffold.

Payload handling is fail-closed: only bounded plain JSON values are copied and
frozen; bytes, sets, custom objects, non-finite numbers, cycles, oversized
values, sensitive fields, and sensitive string values are rejected. No
automatic redaction is claimed because no controlled learning event currently
authorizes payload keys; a future payload schema must be explicitly reviewed
and allowlisted before acceptance.
