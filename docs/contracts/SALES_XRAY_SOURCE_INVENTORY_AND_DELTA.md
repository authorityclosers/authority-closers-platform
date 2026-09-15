# Sales Xray — source inventory and contract delta

2026-09-13. User-directed standalone AC conversation analysis; product name
Dipak's Sales Xray. Coordinator integrates domain/auth/migrations. This inventory
precedes implementation and is not a release approval.

## Inspected sources

- Supplied AC Conversation Lab v0.3 ZIP SHA256
  `c0d85e7400d02f23af2e86f8a27bc81bfe6824588548e18c5834cafc4ad835a4`.
  START_HERE, RELEASE_STATUS, KNOWN_LIMITS, AGENTS, implementation plan and architecture read first.
- Native AudioAtlas source expected SHA256
  `40b8b05256986da5eb5d49c3b3cb48c52d511117ecf2e59d56849457cb12fae3`;
  preserve bytes and MIT notice. SignalLab has distinct windows/clocks; no implicit substitution.
- Current saved platform main: `65b1f36c2507fba706eecee4e565158cc7492baa`.
- Release owner's inspected candidate: `7d3aadb0c09056f42e04dae1d8359a2bd137f420`.
  Sales Xray isolated AC worktree starts here; its scoped result will join the existing release.
- UI candidate inspected: `fba251a6186362291b0e67de4f59fdd3857e5a2b`.
  Both referenced live tasks read and contacted. Release owner controls deployment;
  UI owner controls current policy/auth/UI edits. This lane does not replace the LMS.
- Current infrastructure authority: platform `infra/vps-foundation` per ADR-026;
  application manifests under `infra/application`. Historical infra is evidence.
- Exact Drive IDs from DRIVE_CONTROLLED_SOURCE_MANIFEST.csv fetched in order:
  Master Index, BRD, IMP-00,01,03,04,05; then PRD, IA, UX Research/States,
  UI System, SRS, Data/Tenancy, API/MCP, Security, QA, DevOps, Admin, Telemetry,
  ADR/Risk; assurance UXA-01, SVAL-01 and GOV-AUD-001. Retrieval cache/metadata
  resides outside source control in the release-transfer directory.
- Package receipts report 93 software tests, but are historical evidence;
  real browser/network, provider, human-quality and KVM4 load proofs are absent.

## Contract delta (ADR: standalone client, shared AC domain API)

Add bounded `ac_platform.conversation_intelligence`, separate standalone client,
and thin presentation entry adapters for LMS/free course/website. AC canonical
person/session/membership remain authoritative. Do not create parallel identities,
SQLite runtime, public local-demo service, or payment-derived access.

| Boundary | Existing foundation / change |
| --- | --- |
| Identity | Existing session and active server-selected membership; never client tenant selection in payload |
| Recordings/runs | Owner+tenant composite lineage, immutable revisions, purpose/permission references; guessed IDs denied |
| Checkpoints | C0-C6 manifests; C1 measurements and C2 transcript independent; profile/judge rerun only invalidates C5/C6 |
| Evidence | Literal transcript and exact source-clock spans; style-neutral facts separate from draft coaching |
| Jobs | Existing PostgreSQL durable jobs, transactional outbox, lease/recovery hold; separate bounded CPU/inference worker |
| Storage | Existing media transport currently fails closed; recording storage needs verified private transport and deletion proof |
| Minutes/budget | Enrollment access is not a minute ledger; explicit auditable grant/reserve/settle/release, no invented default grant |
| Provider | External secret reference only; separate broker, exact input/vendor/privacy authorization plus quote/reservation; unknown outcome held for reconciliation |
| Review | Dipak contextual/sales and Suyash measurements/attribution; server-bound assignments; immutable proposals after recorded cursor |
| Promotion | Reproduction fixture + development/calibration tests + approved evidence; holdout sealed; no thumbs-down training |
| Scoring | Declared 100 / actual 95 preserved; numeric publication disabled pending authorized resolution and scientific gates |
| Release | Existing immutable release pipeline; actual browser/network, auth/IDOR, storage/deletion, capacity, canary/rollback evidence |

## Authorization delta

Self: upload intent, list own recordings, own run/checkpoint/report, quote/run,
delete own source and descendants. Assigned reviewer: exact run/revision and
assigned lane only. Technical/contextual adjudication are distinct capabilities.
Privileged grants/promotion require explicit capability, reason and audit.
Provider callbacks cannot grant minutes, publish reports or create learning progress.
Anonymous clients may view a clearly labelled synthetic example only.

Real supplied recording is authorized for local testing in this user request.
External processing, calibration/training and public sharing are separate gates.
No paid execution or credit purchase occurs during the offline slice. Normal
paid pilot cap INR1500; INR2000 requires a new explicit owner approval above it.
Subdomain selection is delegated by the user; exact target must be recorded and
verified with the current infrastructure owner before routing. Apex remains unchanged.

## Initial unresolved activation evidence

Fresh instantaneous VPS headroom is being collected separately; it is not a load test.
Provider account/terms/actual cost, recording-specific third-party/privacy permission,
approved retention/deletion policy and reviewer identity mappings are not established
by the package. These block their capabilities, not deterministic local implementation.
