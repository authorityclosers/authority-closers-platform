# Sales Xray deterministic evidence, checkpoint and review kernel

2026-09-13. Isolated implementation evidence, not provider activation or release approval.

## Sources and authority

Read repository AGENTS.md and `docs/contracts/SALES_XRAY_SOURCE_INVENTORY_AND_DELTA.md`.
Inspected the supplied lab's context-engine brief, algorithms, calibration protocol,
checkpoint architecture, core/context/policy/store implementations and their tests.
Consulted coordinator-fetched exact-source AC-SVAL-01 and AC-GOV-AUD-001 caches.
Old lab receipts and model-generated designs remain evidence; the current user mandate,
controlled gates and current AC identity/PostgreSQL foundations remain authoritative.

The source `config/dipak_profile.json` is copied without revision into
`packages/python/ac_platform/conversation_intelligence/profiles/dipak_draft.json`.
Its SHA256 is `095f3c5f09d8e23111f23bf685b40d9cc75ad39c42b8d9cce02344c453154479`.
Declared total 100, literal source weights totaling 95 and the draft criteria remain
unchanged. No missing five points, normalization, default competency threshold or
official autonomous score was invented.

## Implemented

- `checkpoints.py`: immutable source/tenant binding; C0-C6 input and output identities;
  exact same-source parents; deterministic cache keys; explicit replicas; immutable
  conflict check; descendant invalidation. C1 measurement and C2 transcript are parallel
  branches. Profile/judge changes affect C5/C6 only. Acoustic/window profile changes
  affect C1 and descendants but preserve C2. Configuration complexity is bounded.
- `context.py`: strict literal character, source revision, speaker and clock checks.
  Segment quotes retain whole-segment timing. Finer timing requires explicit provider,
  alignment, human or synthetic-fixture word support; interpolation is rejected.
  Prefix-time observations cannot use future evidence. Unknowns, contradictory
  observations, duplicate-evidence suppression and explicit forward supersession are
  retained. Supersession preserves prior observations and requires an adjudication
  reference. No hidden motivations or emotion inference is implemented.
- Safe bounded `all`, `any`, `not`, `slot_equals` applicability with three-valued
  unknown propagation. Profile projection cannot mutate facts and always withholds
  numeric publication, including when an input profile claims approval.
- Evidence packets keep required quotes, context references and counterevidence
  together. A mandatory set that exceeds the budget fails closed. Coverage and
  omissions are explicit. Budget is total UTF-8 JSON bytes, **not provider tokens**.
- `review.py`: exact run/transcript/measurement/profile revision binding; server-loaded
  reviewer assignments; separate sales and signal responsibilities; immutable
  proposals; ordered hash-chained review import strictly after a recorded tenant/feed
  cursor; idempotency conflict detection; permission-bound reproduction manifests.
- Development/calibration selection accepts metadata only and rejects holdout content,
  holdout selection, recording and participant leakage across partitions. Promotion
  eligibility requires approved frozen gates, exact candidate-bound passing receipts,
  zero unresolved severe unsupported allegations, sealed-holdout attestation, explicit
  candidate/receipt approval and rollback evidence. The returned receipt does not
  deploy, train, change labels or enable numeric scoring.

## Tested here

Final post-format invocation, one process, 49 passed in 0.35 seconds; exit code 0:

```powershell
$env:PYTHONPATH='D:/Projects/authority-closers-platform-sales-xray/packages/python'
& 'D:/Projects/authority-closers-platform/.venv/Scripts/python.exe' -m pytest `
  tests/unit/conversation_intelligence/test_checkpoints.py `
  tests/unit/conversation_intelligence/test_context.py `
  tests/unit/conversation_intelligence/test_review.py `
  --junitxml='D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/evidence-context.xml'
```

Scoped Ruff passed for these three modules and three test files. Scoped mypy with
`--follow-imports=silent` passed for these three source modules. No full-repository
typecheck or browser/provider test is claimed by this lane. An initial typecheck found
four local typing issues; they were fixed before the final passing checks and pytest run.

Receipts under `D:/Projects/authority-closers-release-transfer/2026-09-13-sales-xray/receipts/`:

| Receipt | SHA256 |
| --- | --- |
| `evidence-context.xml` | `e2c7443d0f323ca7346f30ae029ef932fe6de8096c19beaa8243242eef4de182` |
| `evidence-context.stdout.txt` | `0720de320d563056d0538a16078abc7f37b9b70e7aa5de312c9e8cb4f7b65274` |
| `evidence-context.ruff.txt` | `a4443afdcfb6d7363adb285762515ccf7cf50473b1a05c20c1a50f6bed4d26b0` |
| `evidence-context.mypy.txt` | `281a094c39385b4d7b53e5db635f52158036861433c2a4975b9039e77a627a24` |

Tests cover cache isolation, profile/ASR invariance, distinct acoustic profiles,
source-parent mismatch, immutable output conflict, forged quotes/revisions/timebases,
unsupported finer timestamps, malformed future observations, duplicate evidence,
conflicts and supersession, DSL complexity and unknowns, profile invariance, 95/100
withholding, mandatory packet overflow, reviewer spoofing/lane mixing, stale reviews,
cursor replay/tampering, proposal-only feedback, sealed holdout/leakage and failed or
stale promotion receipts. Synthetic cases establish software invariants only.

## Coordinator integration contracts and remaining activation gates

Hash possession is not authorization. Authorize source and all parents before cache
lookups, and call `assert_same_artifact` under a persistence unique-key lock. Persist
review proposals and the resulting cursor in one AC PostgreSQL transaction. No SQLite
demo store was copied. Server-load the actor identity, assignment, immutable run binding,
approved gate and approval record; never construct trusted assignments from request
display names. Map actual Dipak/Suyash identities through existing AC identity policy.
The canonical package lane values are `sales` and `signal`; clients may display clearer
labels through explicit adapters.

Transcript shape: source binding fields `tenant_id`, `recording_id`, `source_sha256`,
`source_revision`; `revision`, `timebase_id`, `duration_ms`, and literal `segments`.
An evidence span repeats source binding and timebase plus `transcript_revision`,
`segment_id`, `speaker_id`, character bounds, quote, millisecond bounds and timing scope.
Only internally reduced context should reach the packet compiler; external callers
submit observations for validation rather than supplying their own resolved fact state.
Evidence references and adjudication/permission references must resolve through
tenant-authorized platform storage. Reference validation does not prove semantics.

Review bindings are `RunBinding(tenant_id, run_id, run_revision, transcript_revision,
measurement_revision, profile_revision)`. Approved frozen gate thresholds are supplied
externally; this kernel does not choose scientific floors. Receipt references and
holdout attestations must be verified by the release coordinator, not trusted as
client-provided booleans. No live review system was available to this lane, so no
latest reviewer feedback import is claimed.

Provider-tested: no. Staged: no. Production-published: no. This lane contains no paid
transport, credentials, external recording processing, raw real-call fixtures, model
retraining or product activation. Real-data consent/retention/provider permissions,
reviewer identity assignment, verified evaluation data and AC-SVAL/weight approval
remain separate activation requirements owned by the coordinator.
