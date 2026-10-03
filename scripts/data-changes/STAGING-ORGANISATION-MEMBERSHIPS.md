# Staging organisation membership tool — AUT-931

`staging-organisation-memberships.py` previews an exact approved target list and
applies eligible memberships through `OrganisationService` in one transaction.
It creates no people or tenants. It accepts staging only and requires injected
runtime Settings, both protected tenant IDs, and a matching baked release SHA.
Reference arguments record the existing approval; they do not grant permission.

Root is the named operator for AUT-440. Before applying, Root checks the exact
approved target list, confirms no release is running, previews it, and takes the
separately required staging snapshot through the existing backup procedure.
The builder runs fictional tests only; this card applies no environment data.

## Run the reviewed script with the deployed API

The Python image packages the service but does not copy `scripts/`. From a
trusted repository checkout, stream the script at the **deployed release SHA**
to the running staging API's Python interpreter. No server file edit, image
rebuild or credential argument is needed. Root supplies the existing staging
container ID and reads its release marker first:

```sh
docker exec "$staging_api_container" python -c \
  'from ac_platform.application.release_identity import read_baked_release_id; print(read_baked_release_id())'
```

Set `membership_release` to that full SHA, after this PR has merged and the
normal release train has shipped it. All example target addresses below are
fictional; replace them only with AUT-440's explicitly approved targets. UUID
targets use `--target <person-id>` instead. Missing people are skipped; do not
substitute another person or infer other staff from a domain.

```sh
set -o pipefail
membership_args=(
  --environment staging
  --tenant-id 69340372-2ad6-4e08-a61e-43b11cc97801
  --target dipak@example.test --target suyash@example.test
  --role admin
  --approver owner-approval-reference
  --issue-reference AUT-440 --operator-reference root-operator
  --run-reference 01010101-0101-4101-8101-010101010101
  --command-id 02020202-0202-4202-8202-020202020202
  --command-id 03030303-0303-4303-8303-030303030303
)
git show "$membership_release:scripts/data-changes/staging-organisation-memberships.py" |
  docker exec -i "$staging_api_container" python - "${membership_args[@]}"
```

Generate and retain real run/command UUIDs for the operational run. Each
`--command-id` pairs with `--target` in order. Approver, issue and operator
references contain 1–64 letters, digits, underscores, dots, colons or hyphens;
use IDs rather than personal addresses. Preview JSON contains masked targets,
resolved person IDs, current `before`, proposed `after`, status, command IDs,
release and attribution. Exit 2 is a refusal/failure without committed batch
changes; raw settings/DB exceptions are never printed.

After checking the preview and recording the snapshot receipt, run the **same
arguments** with `--apply`:

```sh
git show "$membership_release:scripts/data-changes/staging-organisation-memberships.py" |
  docker exec -i "$staging_api_container" python - "${membership_args[@]}" --apply
docker exec "$staging_api_container" python -m ac_platform.organisations list-members \
  --environment staging --tenant-id 69340372-2ad6-4e08-a61e-43b11cc97801
```

Apply re-resolves active verified people under locks and preserves the sole
owner. A missing, inactive or unverified person is reported as skipped. An
owner target, protected tenant, ambiguous person, duplicate target/command,
invalid organisation or command-attribution conflict refuses the batch.
Post the masked preview/apply/read-back, approver reference, operational run ID,
release SHA and snapshot receipt on AUT-440. Do not post full emails or secrets.
Sales Xray activation and minute grants stay outside this command.

## Replay and JSON example

Applied commands append `organisation.member_added` audit events with existing
before/after payloads, command UUIDs and operator intent. The audit reason is
JSON containing `tool`, `environment`, `approver`, `issue`, `operator` and `run`.
Reusing a command with changed attribution or target/role is refused. A matching
replay reports current state and writes nothing, even if the member was changed
later; a new approval/command is needed for another change. A fresh command for
an already-correct active membership also writes nothing. A skipped command has
no recorded effect; Root must reconfirm eligibility and approval before retrying
it after the person exists or becomes verified.

One fictional preview target:

```json
{
  "target": "d***@example.test",
  "person_id": "04040404-0404-4404-8404-040404040404",
  "command_id": "02020202-0202-4202-8202-020202020202",
  "status": "eligible",
  "before": null,
  "after": {"role": "admin", "status": "active"}
}
```

## Implementation evidence

Source base: `0200927a22b9d139e4defe50390c4debf7648331`.
Scope: this script/document and their two focused test files only. No services,
HTTP routes, migrations, billing, secrets, deployment or environment data change.
Focused tests use fictional local PostgreSQL records in a migrated temporary
schema, including read-only preview, attributable audit and chain integrity,
replay, concurrency, full batch rollback, reactivation, eligibility changes,
protected/invalid targets and output containment. Reproduced on 3 Oct 2026:

| Command | Result |
| --- | --- |
| `uv run ruff format --check packages/python tests` | Passed, 923 files |
| `uv run ruff check packages/python tests` | Passed |
| `uv run mypy packages/python` | Passed, 388 source files |
| `uv run pytest tests/unit/organisations tests/integration/test_organisation_membership_data_change_postgresql.py -q -x --tb=short` | 51 passed, 25.39 s |
| `uv run ruff format --check scripts/data-changes/staging-organisation-memberships.py` | Passed |
| `uv run ruff check scripts/data-changes/staging-organisation-memberships.py` | Passed |
| `uv run mypy --follow-imports=silent scripts/data-changes/staging-organisation-memberships.py` | Passed |
| `git diff --check` | Passed |
| `ac-gate check` | Passed |

CI, CTO review, CEO approval, merge and dev/staging release verification remain
separate delivery gates. No staging/production database command was run.
