# Staging organisation admin — AUT-1694

This tool implements an exact owner-approved change through the deployed app's
organisation and deletion services. Claude is the designated staging operator
for the owner's request. The builder runs fictional tests only.

Before apply, confirm that no release is running, record the owner's approval
for this exact target list, preview the change, and take a fresh staging database
snapshot through the existing backup procedure. `--snapshot-reference` records
that receipt; the script does not take or independently validate the snapshot.
No approval is implied by supplying a reference. Do not use a production runtime.

The default preview runs in a PostgreSQL read-only transaction. Apply re-resolves
and fences the active organisation, sole owner, named verified operator and
targets, then commits the entire requested batch once. A refusal rolls it all
back. Success is printed only after commit; errors contain no supplied inputs,
runtime URLs, driver parameters or credentials. Output masks email targets.
Exit 2 reports a refused/rolled-back command. Exit 3 means the transaction
completed but its output stream failed; read back or replay the same retained
command IDs rather than assuming rollback or issuing new commands.

- `add-members`: email targets only; active verified people become members.
  Missing/unverified people receive durable seven-day operator invites and
  canonical invitation mail. Verified sign-in joins them through the existing
  sign-in service. Existing active members keep their current roles. Suspended
  people are skipped. Existing pending invitations keep their original policy;
  a self-serve invite continues to require explicit acceptance.
- `remove-members`: full person UUID or email; end membership, preserving the
  person, membership row and audit history. The owner cannot be targeted.
- `delete-recordings`: full recording UUID; pin the approved recording's
  original source tenant and canonical Sales Xray submission binding. The source
  may be a registered organisation or the configured Personal workspace. This
  does not allow membership changes in Personal. Call
  `ConversationApplication._request_owned_deletion`, the same internal service
  used by in-app Delete. It fences reads immediately, increments generation and
  queues `conversation.erase_local.v1`; the existing worker performs erasure.
  `deleting`/`deleted` and absent records are skipped. The result is an erasure
  request, not a claim that worker erasure has finished. It does not change usage,
  charges, credits or history. A wrong tenant fails the entire batch.

Each actual mutation appends `organisation.staging_admin_applied`, naming the
operator's real person, approver, issue, run, snapshot receipt, canonical child
command, intent and before/after. The app's existing domain audit also remains.
Keep one stable UUID per target plus one stable run UUID. Same-command replay
reports the historical `applied_result` and changes nothing, including after
membership removal or invitation acceptance. New action/target/operator/approver/
issue/run attribution under an old command is refused. Use a new approved command
for a later change. A no-op/skipped target has no new audit receipt/effect.

Run the script at the actual deployed release SHA, with staging's injected
runtime settings. The image does not copy scripts; stream the reviewed script
from that exact checkout revision to its interpreter:

```bash
set -o pipefail
docker exec "$org_admin_container" python -c \
  'from ac_platform.application.release_identity import read_baked_release_id; print(read_baked_release_id())'
org_admin_common=(
  --environment staging
  --actor-person-id "$org_admin_actor"
  --approver "$org_admin_approval"
  --issue-reference AUT-1694 --operator-reference claude-operator
  --run-reference "$org_admin_run"
)
git show "$org_admin_release:scripts/data-changes/staging-org-admin.py" |
  docker exec -i "$org_admin_container" python - add-members \
  "${org_admin_common[@]}" --tenant-id 69340372-2ad6-4e08-a61e-43b11cc97801 \
  --target goyalsurendra447@gmail.com --command-id "$surendra_command" \
  --target sc1998530@gmail.com --command-id "$shubham_command"
```

The named operator supplies their own full person UUID, the existing container,
release, recorded approval and retained run/command IDs. They must resolve the
two abbreviated member IDs from the app's member list and check names before
using their full UUIDs; the tool never guesses or matches prefixes.

```bash
git show "$org_admin_release:scripts/data-changes/staging-org-admin.py" |
  docker exec -i "$org_admin_container" python - remove-members \
  "${org_admin_common[@]}" --tenant-id 69340372-2ad6-4e08-a61e-43b11cc97801 \
  --target "$quinn_person_id" --command-id "$quinn_command" \
  --target "$alpha_learner_person_id" --command-id "$alpha_learner_command"
git show "$org_admin_release:scripts/data-changes/staging-org-admin.py" |
  docker exec -i "$org_admin_container" python - delete-recordings \
  "${org_admin_common[@]}" --tenant-id "$org_admin_recording_tenant" \
  --target 16a6f514-e38b-4fc6-9fcc-a8bc3bab5c50 --command-id "$delete_first_command" \
  --target 4e17f992-44fa-40c7-b503-db1e4697f6bb --command-id "$delete_second_command"
```

`org_admin_recording_tenant` is the full original source tenant UUID, read from
the authorised app/Admin record and confirmed in the preview. If the two exact
recordings have different original tenants, preview/apply one command per tenant
with its own stable target command UUID. Do not infer source tenant from where
the owner last viewed a call, or use a processing person's UUID as a tenant ID.

After reviewing each preview and taking the recorded snapshot, rerun its exact
command with `--snapshot-reference "$org_admin_snapshot" --apply`. Read back
membership through `/v1/platform/organisations/{tenant_id}/members` or the app's
organisation CLI. Check recording state through Admin and wait for the existing
worker's erasure completion. Verify pending invites/mail and subsequent verified
sign-in through the app. Post masked before/after, run, approver, release and
snapshot receipt on AUT-1694; never post credentials or recording contents.

Username creation/password issuance is a separate sign-in feature, not a CLI
operation that prints passwords. No staging/production action was executed by
this change. CTO/CEO review and deployed verification remain required.
