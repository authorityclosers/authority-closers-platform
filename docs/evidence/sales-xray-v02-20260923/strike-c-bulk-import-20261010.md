# Strike C: organisation recording import

Owner request: bulk import a team's folder through normal acquisition, with
confirmed member ownership, uploader attestation, source-hash idempotency, fair
queueing and a batch progress view. Implementation continues on AUT-1676 after
the watchdog merged recovery/report-minute PR #421 at main `43d6eaf`.

## Delivered preview

`adbad4e4cc09ccb5cdc4ebddf2cb0f8613b2afdc` adds the private POST
`/v1/conversation/acquisition/imports/preview`. It reuses the submission router's
current cookie identity, selected tenant, origin and response-privacy guards.
Only current organisation owners/admins can preview. Operations, guests,
ordinary members, ended memberships and inactive people cannot confer import
authority. This command does not write, ingest bytes, accept quotes or reserve
minutes.

The inventory is bounded to 256 files / 1 GiB, with each file subject to the
normal 32 MiB source cap. Safe root-relative paths, lowercase SHA-256 hints and
exact byte lengths are required. Unicode names are normalised; an exact unique
display-name match or unique first-name hint is proposed for confirmation.
Ambiguous and unmatched folders remain unassigned. Response members contain
IDs/names, never email addresses. Duplicate hash hints are explicitly distinct
from canonical already-imported proof.

Verification: 28 focused cases in
`tests/unit/conversation_intelligence/test_bulk_import_preview.py` passed.
These include real canonical cookie HTTP, origin rejection, revoked session,
demotion after preview, changed tenant, active-member filtering, Devanagari,
ambiguous matches, duplicate hints, path traversal, manifest/byte bounds and
strict source hashes. Ruff/format and targeted mypy of both new modules and the
composing submission module passed. All data is fictional; no audio/provider
request or hosted data mutation occurred.

## Source and remaining scope

The exact manifest Drive IDs for the required first seven controlled sources
were fetched in their prescribed order, followed by the first-slice source
set, AC-UXA-01 and AC-GOV-AUD-001. All 23 returned IDs matched. The durable
metadata/digest receipt is `/home/acdev/strikes/1676/bulk-import-source-intake.json`;
no raw controlled document content was copied into Git. AC-IMP-03 authority,
tenant and upload consent/provider/retention gates remain binding. An uploader
is distinct from the selected human call owner and organisation processing
principal.

Durable batch state, upload integration, exact on-behalf authority, safe
idempotency, fair admission and the progress client are not yet delivered by
this preview slice. Unassigned call ownership needs an explicit owner rule;
the existing intake requires a person. Pending invitations are not members.
The intended 89-recording staging run belongs to Claude after the feature is
available on staging; this source session does not load that corpus.

The prescribed Windows ac-orchestra skill is unavailable on this server, and
no accessible existing Pro chat/artifact was found. Verified local work
continues with that limitation recorded. Strike A page/shell and Strike B
report rendering are outside this change.
