# Operations-only empty-environment bootstrap

## Scope

The reviewed tenant-only CLI breaks the empty-production tenant prerequisite
cycle without reopening Admin/Coach registration or inventing verified identity.
It adds only `BootstrapApplication.bootstrap_operations_tenant` and the
`python -m ac_platform.bootstrap --operations-only` adapter. Existing owner and
public-learner service paths are unchanged. No schema migration is added.

Required intent: `--command-id` (stable UUID), `--operator-reference`, `--reason`,
`--tenant-slug`, and `--tenant-name`. Operator/change references and reasons must
be non-secret. Production additionally retains `--environment production
--allow-production`, valid deployment settings, explicit database configuration,
and the baked immutable release check. Modes are mutually exclusive; an identity
email is refused in operations-only mode.

The command writes only the named active `Tenant`, one canonical immutable
`AuditEvent`, and its normal `AuditChainHead`. Its audit ID is the command ID;
the payload pins the normalized operator reference, slug, name and schema
version, with the reason in the existing audit field. It never creates or
changes a person, verification, provider identity, membership, role, capability,
session, consent, eligibility or enrollment.

A transaction-scoped PostgreSQL advisory fence precedes history/tenant reads.
Exact intent replays validate the same still-active tenant and return
`replayed=true` without another audit. Changed intent, another command (including
another slug), an unrelated event-ID collision, inactive/renamed/missing scope,
or a mismatched configured operations UUID fail closed. Existing exact matching
tenants may be validated and audited once; no lifecycle or configuration repair
is performed. Tenant and audit commit together before the CLI prints the safe
`{tenant_id, tenant_created, replayed}` summary.

## Verification

- `uv run pytest -q tests/unit/bootstrap`: **59 passed**, including 36 real
  in-memory SQLite relational cases and 9 new CLI cases plus legacy regressions.
- Relational tests enforce foreign keys and real caller-owned transactions;
  count every canonical table; verify the real audit chain; test exact replay,
  input/conflict/lifecycle/configuration denial, immutable audit, and rollback
  after the real audit and chain-head append. Only the explicitly labeled
  missing-tenant corrupt-restore test disables foreign keys.
- CLI tests verify production acknowledgement, explicit intent, exclusive
  modes, no identity input, no other bootstrap service invocation, and no
  success summary or raw native error after commit failure.
- Focused Ruff lint/format, bootstrap mypy, and `git diff --check`: passed.
- The opt-in PostgreSQL file collects **3 cases**: actual observed blocked-lock
  replay/conflicting-intent races and rollback after real audit append. Its
  fixture permits only the explicit managed loopback owner test target and
  migrates/drops a fresh `ops_bootstrap_<32hex>` schema. The implementation agent
  initially collected these cases without executing them. The parent subsequently
  ran the actual PostgreSQL cases together with the unit suite: **62 passed
  (3 PostgreSQL + 59 unit), 24.62 s**. This used disposable isolated schemas,
  not an operational tenant bootstrap. Independent source review found no
  Critical/Important issue; a separate unit-only rerun passed all 59 cases.

No operational database, runtime, account, secret configuration, external
provider, browser or remote state was changed by this implementation. An empty
held three-app installation is not a completed production launch. Production
consent, normal verified registration, explicitly approved owner/admin and Coach
provisioning, approved content, email activation, and media/practice activation
remain separate boundaries; this command grants none of them.
