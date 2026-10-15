# AUT-1741 item 1: schema publication source handoff

Continuation baseline: 3f3093b1be3a7a11595687414f8f39085560a2c5.
Architecture: AUT-1741 decision 83bcefc8-8d1b-49f6-8099-77ca165fb682.
Transport: AUT-1816 decision 67ffb4e6-bd71-4a9e-8dcb-cae2ea60d4ac.
Staging-size transport: AUT-1985 CTO decision document `decision`
(revision 46a7c5ea-f7f2-4dd3-85d6-b05e361ad45d), superseding the dispatch-input
payload of AUT-1816; every other guarantee is unchanged.
Acceptance: AUT-1818. The immutable source commit is linked from the task.

## Interface

The dedicated workflow and helper accept exactly schema.dump and manifest.json,
independent manifest SHA, full admitted main SHA, fictional/staging mode, UUID
hex request, and a fresh Root included-allowance receipt. Both sides reuse the
existing checksum, format, freshness, baseline and PostgreSQL TOC APIs. They
inspect TOC with the pinned image; submitted schema SQL is never executed.
Full backup tools and the existing schema APIs remain unchanged.

ZIP reads reject duplicate, extra, missing, empty, directory, traversal, link,
encrypted, unsupported, corrupt and inflated entries. The pair never travels in
a dispatch input (GitHub caps all inputs at 65,535 characters together). The
operator creates one unreachable git blob in this repository holding the
hardened ZIP; the dispatch carries only the blob's git SHA and the ZIP SHA-256.
The publisher run fetches that blob by SHA from the fixed repository with its
read-only token, streams it under the pair bound (32 MiB + 8 KiB + 64 KiB ZIP
margin, within GitHub's 100 MB blob read bound), and verifies both hashes before
the unchanged ZIP, manifest, baseline, freshness and TOC checks. No ref, branch,
tag, commit, release or package is created; the blob is never deleted by us and
GitHub collects unreachable objects on its own schedule. The repository is
public, so a blob readable by SHA exposes exactly what the published artifact
already exposes: schema-only content with no secrets or customer rows. Payloads
use private stdin, private 0600 scratch files and the Actions event file, never
shell interpolation, argv or output. Errors suppress inputs, API diagnostics and
credentials.

Event, workflow and checkout SHA must equal the independent main pin; reruns
fail. Dispatch requires existing admin/maintainer access and the numeric Root
operator ID must equal the authenticated sender. No role or token is installed.
Only independent artifact download returns a usable receipt: workflow path/ID,
source SHA, run/attempt, request, mode, artifact ID and both file checksums.
The exact two-file root and equality to original bytes must pass first.

Publication is serialized, immutable, retained one day and limited to four live
schema artifacts/128 MiB uncompressed. Prior artifacts conservatively reserve
their maximum pair size; the candidate reserves its actual uncompressed size.
A fourth maximum-sized pair can therefore be refused. The existing complete
repository inventory reader charges all artifacts, including expired ones,
against the admitted pool and reserves 32 MiB + 8 KiB for the next upload.
No deletion, reclaim, overwrite, pool/settings change or pointer write exists.

Root supplies actual included-storage headroom and remaining included minutes
from its existing governed account read-back. The receipt expires in 15 minutes
and binds source/request/operator/mode. Unknown/exhausted allowance fails closed.
The repository pool variable alone never proves included allowance. Root must
reserve headroom for concurrent uploads in other workflows; Actions rechecks
repository inventory under the publisher serial lock. No paid fallback exists.

## Root invocation after normal sensitive source activation

Use AUT-63's existing governed operator path, existing GitHub identity, reviewed
main source and locked tooling. The operator supplies private, run-owned
PAPERCLIP_RUN_SCRATCH_DIR. Keep that scratch available through read-back within
the governed run; do not copy request contents into Git, logs or task text.
Stop if existing tooling, access or included-account read-back is unavailable.

Read and compare to the independently approved merged source:

    gh api repos/authorityclosers/authority-closers-platform/commits/main --jq .sha
    gh api repos/authorityclosers/authority-closers-platform/actions/workflows/migration-schema-publish.yml --jq '{id,path,state}'
    git rev-parse HEAD
    gh api user --jq '{id,login}'
    gh api repos/authorityclosers/authority-closers-platform/actions/variables/AC_RELEASE_ARTIFACT_POOL_BYTES --jq .value

Set SCHEMA_PUBLISHER_SHA to the admitted full main SHA, SCHEMA_OPERATOR_ID to
the verified GitHub numeric ID and SCHEMA_MODE to fictional. Generate a new
request and fictional pair:

    SCHEMA_REQUEST_ID="$(python3 -c 'from uuid import uuid4; print(uuid4().hex)')"
    export SCHEMA_REQUEST_ID
    uv run --frozen python scripts/ops/publish_migration_schema.py fictional-fixture --output "$PAPERCLIP_RUN_SCRATCH_DIR/fictional-pair"

The fixture uses only a random disposable localhost database. A fictional row
is inserted and excluded from the schema dump. Its manifest follows the existing
staging-format contract, while the fictional artifact mode/name distinguishes
this proof from staging evidence. Never install its ID as a staging pointer.
Set SCHEMA_PAIR_DIR to that pair. For a subsequent separately admitted staging
publication, set mode to staging and use the existing exporter instead:

    uv run --frozen python scripts/ops/export_migration_schema.py --output "$PAPERCLIP_RUN_SCRATCH_DIR/staging-pair"
    uv run --frozen python scripts/ops/export_migration_schema.py --output "$PAPERCLIP_RUN_SCRATCH_DIR/staging-pair" --apply

Root records its fresh included-account receipt on AUT-63 and sets
SCHEMA_INCLUDED_STORAGE_HEADROOM_BYTES, SCHEMA_INCLUDED_MINUTES_REMAINING and
SCHEMA_REPOSITORY_POOL_BYTES only from those read-backs.
SCHEMA_ADMISSION_RECEIPT is AUT-63/<receipt UUID>. Unknown values mean stop.
Create the private admission file and calculate the independent manifest hash:

    export SCHEMA_PAIR_DIR SCHEMA_MODE SCHEMA_PUBLISHER_SHA SCHEMA_OPERATOR_ID
    export SCHEMA_INCLUDED_STORAGE_HEADROOM_BYTES SCHEMA_INCLUDED_MINUTES_REMAINING
    export SCHEMA_REPOSITORY_POOL_BYTES SCHEMA_ADMISSION_RECEIPT
    python3 - <<'PY'
    import hashlib, json, os
    from datetime import UTC, datetime
    from pathlib import Path
    value = {
        "schema": "ac.schema_publication_admission/1",
        "repository": "authorityclosers/authority-closers-platform",
        "publisher_sha": os.environ["SCHEMA_PUBLISHER_SHA"],
        "request_id": os.environ["SCHEMA_REQUEST_ID"],
        "mode": os.environ["SCHEMA_MODE"],
        "operator_id": int(os.environ["SCHEMA_OPERATOR_ID"]),
        "admitted_at": datetime.now(UTC).isoformat(),
        "included_storage_headroom_bytes": int(os.environ["SCHEMA_INCLUDED_STORAGE_HEADROOM_BYTES"]),
        "included_minutes_remaining": int(os.environ["SCHEMA_INCLUDED_MINUTES_REMAINING"]),
        "repository_pool_bytes": int(os.environ["SCHEMA_REPOSITORY_POOL_BYTES"]),
        "evidence_ref": os.environ["SCHEMA_ADMISSION_RECEIPT"],
    }
    path = Path(os.environ["PAPERCLIP_RUN_SCRATCH_DIR"]) / "schema-admission.json"
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(value, stream)
    print(hashlib.sha256((Path(os.environ["SCHEMA_PAIR_DIR"]) / "manifest.json").read_bytes()).hexdigest())
    PY

Set SCHEMA_MANIFEST_SHA256 to that independent hash. Validate/pack without
mutation, then dispatch the saved private request once:

    uv run --frozen python scripts/ops/publish_migration_schema.py pack --pair-dir "$SCHEMA_PAIR_DIR" --manifest-sha256 "$SCHEMA_MANIFEST_SHA256" --publisher-sha "$SCHEMA_PUBLISHER_SHA" --mode "$SCHEMA_MODE" --request-id "$SCHEMA_REQUEST_ID" --admission-file "$PAPERCLIP_RUN_SCRATCH_DIR/schema-admission.json"
    uv run --frozen python scripts/ops/publish_migration_schema.py dispatch --request-id "$SCHEMA_REQUEST_ID"

Both commands revalidate custody, allowance, pool and source. Main moving
requires source readmission. Request, ZIP and state files are 0600 in a 0700
UUID directory. The `pack` command writes nothing to GitHub. The `dispatch`
command first creates the content-addressed blob (idempotent: identical bytes
give the identical SHA; a repeat creates nothing new), reads it back by SHA and
compares every byte to the local ZIP, then persists a marker before the sole
non-idempotent mutation, so ambiguous dispatch failure cannot be replayed. A
blob failure stops before the marker and the dispatch; re-run `dispatch`. If
GitHub collects the blob before the run fetches it, the run fails closed with
pointers unchanged; pack a fresh request. Inspect the existing run instead of
retrying a dispatch.
Obtain the candidate run ID from Actions without a polling timer:

    gh api 'repos/authorityclosers/authority-closers-platform/actions/workflows/migration-schema-publish.yml/runs?event=workflow_dispatch&branch=main&per_page=10' --jq '.workflow_runs[] | {id,head_sha,run_attempt,status,conclusion}'

After success, set SCHEMA_SOURCE_RUN_ID to its exact ID:

    uv run --frozen python scripts/ops/publish_migration_schema.py read-back --request-id "$SCHEMA_REQUEST_ID" --pair-dir "$SCHEMA_PAIR_DIR" --run-id "$SCHEMA_SOURCE_RUN_ID"

Only this command returns a usable receipt. It downloads by immutable ID,
proves both original files, and repeats run/expiry checks. Record it on the
existing output card, including request/source/run/attempt/workflow identity
and both hashes. Actual fictional proof is required; PR fixtures do not supply
it. On rejected read-back, record the candidate ID from the run summary:

    uv run --frozen python scripts/ops/publish_migration_schema.py reject --request-id "$SCHEMA_REQUEST_ID" --candidate-artifact-id "$SCHEMA_CANDIDATE_ARTIFACT_ID"

This records only the rejected identity in private scratch. Keep existing
pointers unchanged and let the candidate expire. Any earlier deletion requires
exact governed approval. Staging pointer installation remains separately owned
by Root on AUT-1815 through AUT-63 after a verified staging-mode receipt.

## Verification and remaining evidence

    uv run --frozen ruff check scripts/ops/publish_migration_schema.py tests/infra/test_migration_schema_publication.py
    uv run --frozen ruff format --check scripts/ops/publish_migration_schema.py tests/infra/test_migration_schema_publication.py
    uv run --frozen pytest -q tests/infra/test_migration_schema_publication.py tests/infra/test_migration_schema_gate.py tests/infra/test_postgres_schema_export.py tests/infra/test_artifact_inventory.py
    pnpm exec prettier --check .github/workflows/migration-schema-publish.yml .github/workflows/migration-safety.yml docs/evidence/aut-1741-schema-publication.md
    ac-gate check

The AUT-1985 scoped receipt is 114 passed, four Docker cases skipped, over the
publication and gate files. Four Docker cases require the migration-safety CI
job, which sets AC_REQUIRE_SCHEMA_GATE_DOCKER_TEST=1 so they cannot skip. The
real PostgreSQL case proves schema transport and rejects a full backup before
any restore. The bound case packs a 32 MiB fictional dump, proves it fits the
blob transport while every dispatch input stays under 4 KiB, and proves the git
blob SHA against `git hash-object`. Creating a blob at the bound is not proven
against GitHub; the first real proof is the 826 KB staging pair on AUT-1815.
Existing exporter/migration test files remain unchanged.

PR #450 merged as 0c8344d7e1259884dd714b666be9f6869c73bef6; its fictional
publication and independent byte read-back succeeded on AUT-1815 (run
38777061562, artifact 11993778137) before the real staging pair exceeded the
dispatch input bound. The AUT-1985 transport change is CTO-authored, so the CEO
is its backup reviewer and approver. Actual fictional and staging publication
through the blob transport remain unproven until Root resumes AUT-1815 on the
merged source. No dispatch, blob, settings/pointer change, merge, deployment,
staging or production access occurred in this change. Items 2–4 and overall
delivery remain open.

Reference contracts:
[blob create/read, 100 MB read bound and raw media type](https://docs.github.com/en/rest/git/blobs),
[dispatch branch/tag semantics](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event),
[workflow source contexts](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts),
[run identity fields](https://docs.github.com/en/rest/actions/workflow-runs#get-a-workflow-run),
[permission read-back](https://docs.github.com/en/rest/collaborators/collaborators#get-repository-permissions-for-a-user).
