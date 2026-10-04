# Audited operations-owner changes (AUT-828)

Use `operations-owner.py` from a checkout with `ac_platform` installed, or the
baked package directly inside the deployed API container:

```sh
python -m ac_platform.authorization.operator_data_change --help
```

Approval references are audit facts, not permission to run a change. Root runs
an approved change as the single named operator, outside a release. Production
requires a database snapshot first and the owner's review of the dry run.
This task only builds and tests the tool with fictional data.

The container's `settings.environment` must equal `--environment`. Staging and
production also require a baked release ID; production requires
`--allow-production`, even for a preview. The tool accepts no session token and
does not override the database URL, environment, or operations tenant settings.
Use non-secret reference IDs for `--approver` and `--issue`, and a non-secret
reason of 1–500 characters. Keep the same command UUID and intent on a retry.
Use separate UUIDs for membership, first-manager, and release-grant commands.

## 1. Add the existing operations owner

The configured operations tenant must already exist and be active. Email must
resolve to exactly one active, verified person who already has a provider
identity. The command inserts only an active owner membership and its audit
event. An existing active owner is a no-op; every other membership state is
refused. It never creates a tenant/person/identity/password or selects a tenant
for a session. Admin must be signed into fresh.

Run inside the API container, with these placeholders replaced by the approved
target and attribution:

```sh
python -m ac_platform.authorization.operator_data_change add-operations-owner \
  --environment production --allow-production \
  --email '<APPROVED_TARGET_EMAIL>' \
  --command-id '<MEMBERSHIP_COMMAND_UUID>' \
  --approver '<APPROVER_REFERENCE>' --issue '<ISSUE_REFERENCE>' \
  --reason '<APPROVED_NON_SECRET_REASON>'
```

This is the dry run. Apply with the exact same command and `--apply` after the
required approval/snapshot steps. Output includes person/tenant ID prefixes,
membership before/after, `applied` or `dry_run`, `no_op`, and whether any
`CapabilityGrant` history exists. Audit ID equals the membership command ID.

## 2. Bootstrap the first manager, if needed

If capability history is absent, Root uses the existing reviewed
`python -m ac_platform.authorization first-manager` procedure. This tool
cannot mint `platform_access_manage`. Existing capability history prevents a
new bootstrap; inspect it through the existing authorization procedure.

## 3. Grant release management

The target must already be an active operations owner, verified and linked to
a provider. At least one unrevoked platform-scope `platform_access_manage`
grant must exist before this command can run. Only `platform_release_manage`
in platform scope is allowed. No membership or other capability changes.

```sh
python -m ac_platform.authorization.operator_data_change grant-platform-capability \
  --environment production --allow-production \
  --email '<APPROVED_TARGET_EMAIL>' --permission platform_release_manage \
  --command-id '<RELEASE_GRANT_COMMAND_UUID>' \
  --approver '<APPROVER_REFERENCE>' --issue '<ISSUE_REFERENCE>' \
  --reason '<APPROVED_NON_SECRET_REASON>'
```

Apply with the same command and `--apply`. The grant ID equals the command ID;
its audit is linked by `audit_event_id`. Attribution uses the subject for the
grant's required FK, with audit actor type `operator_data_change` and NULL
actor person/session. The audit includes approver, issue, environment, command
ID, subject and permission. Same-intent replay is `no_op`; conflicting intent
is refused. An existing unrevoked identical grant is `no_op` before insertion.
A revoked grant is never reactivated: replay only reports history, and a fresh
command ID can append a replacement. Output includes grant ID, permission,
status, before/after permission names and current active platform permissions.

Both commands use one caller-owned transaction and the existing capability
governance fence. Preview rolls back the whole transaction. Success output is
printed only after commit (or after preview rollback). Unknown failures print
no SQL, settings, tokens, reason values or other emails; retain the command UUID
and inspect/retry the same intent.

After application, read the result back through the app/API and log the run ID,
before/after and approver on the issue. Follow the existing data-change policy
for the migration, seed or Admin coverage within two working days. Merging this
tool does not authorize any staging or production execution.

## Fictional verification

```sh
uv run pytest tests/unit/authorization tests/integration/test_operator_data_change_postgresql.py -q
uv run ruff format --check packages/python tests scripts/data-changes/operations-owner.py
uv run ruff check packages/python tests scripts/data-changes/operations-owner.py
uv run mypy packages/python
```

PostgreSQL tests use only the injected lane-local test URL, a fresh isolated
schema, fictional `example.test` addresses, and normal migrations. They prove
concurrent replay produces one membership/grant plus its audit, and an error
after writing rolls back membership/grant/audit together. Unit tests compare
all tables to prove refusal/dry run makes no writes, and successful operations
leave sessions, identities, credentials and unrelated state unchanged.
