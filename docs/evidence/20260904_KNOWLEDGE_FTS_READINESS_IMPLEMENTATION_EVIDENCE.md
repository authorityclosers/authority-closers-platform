# Phase-2 Knowledge Snapshot FTS implementation evidence

Status: implementation evidence for an inert, read-only slice. No HTTP route,
worker, model, provider, embedding, pgvector, scoring, voice, or external
ingestion is activated by this change.

## Boundary

The migration adds tenant-owned sources, immutable source versions, immutable
chunks, purpose grants, and opaque ACL subject grants. Every queryable row
carries `tenant_id`; source/version/chunk provenance includes a locator and
SHA-256 content digest. Version status may move from `active` to
`superseded`/`withdrawn`; all other history is forward-only.

Retrieval applies tenant, active status, validity, purpose, and ACL predicates
before PostgreSQL full-text ranking. It uses the fixed `simple` configuration,
`websearch_to_tsquery`, `ts_rank_cd`, and stable version/ordinal/UUID tie
breakers in one bounded retrieval statement. Results are `FOUND`,
`NO_AUTHORIZED_EVIDENCE`, or `BELOW_THRESHOLD`. Database timeouts and other
PostgreSQL failures are normalized into typed retrieval errors after a safe
rollback boundary.

## Acceptance gates

- `top_k` is bounded to 12 and PostgreSQL `statement_timeout` is 300 ms.
- A result always carries source key, source version, locator, passage digest,
  tenant, and a deterministic retrieval fingerprint.
- No authorized rows produce `NO_AUTHORIZED_EVIDENCE`.
- Authorized rows with no lexical match or below the pinned threshold produce
  `BELOW_THRESHOLD`.
- No generated citation may bypass Phase-1 `validate_answer_grounding`.
- PostgreSQL stores only lowercase hexadecimal SHA-256 digests.
- `KNOWLEDGE_RETRIEVAL_ENABLED` remains false by default; no route references
  this package.

## Evaluation fixture

`tests/fixtures/knowledge_gold_set.jsonl` is an anonymized JSONL fixture with
answerable, abstention, tenant-boundary, and poisoned-document cases. The
pure helpers in `ac_platform.knowledge.evaluation` load the JSONL and calculate
recall, abstention accuracy, and forbidden-source leakage without logging
question or passage content. The
release-scale gate remains 250 answerable support questions, 100 abstentions,
100 tenant/ACL negatives, 100 injection cases, and 10,000 randomized negative
checks. Required targets are recall@10 >=95%, zero leakage, zero withdrawn
hits, deterministic repeated-query output, and complete provenance.

## Resource and rollback envelope

This slice adds no process or inference memory to the observed 4-vCPU/15-GiB
VPS. The PostgreSQL service remains under its existing 2-vCPU/2-GiB limit. A
staging pilot is limited to 100,000 chunks, four concurrent queries, p95
retrieval <=300 ms, p99 <=500 ms, and no product p95 regression over 10%.

The migration is forward-only. A failed gate blocks release; disabling the
future feature flag and shipping the prior image is the rollback path. No
manual production SQL recovery, destructive history rewrite, or deployment is
permitted.
