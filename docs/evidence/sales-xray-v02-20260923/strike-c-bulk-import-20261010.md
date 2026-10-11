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

## Folder client and explicit confirmation

The additive `BulkImportPreview` island uses the existing page kit. Strike A
can mount it without a new page/shell layout. It strips exactly the selected
directory-picker root, preserves salesperson subfolders and extensionless
files, skips other extensions visibly and hashes one bounded file at a time.
Actual completed hashes drive the displayed count. Reads have a 60-second
per-file budget and cancellation; the private preview fetch has 15 seconds.
Preview responses must match the local canonical UTF-8 manifest digest and
folder counts. Sparse responses yield an unavailable corner card and clear
the busy skeleton. Selection never uploads recording bytes.

Twenty-two focused frontend cases pass, including exact native WebCrypto
hashes, Devanagari canonical digest agreement, source/aggregate bounds,
normalised duplicate paths, cancellation during a stalled file read, private
request options, invalid member proposals and malformed/API failure responses.
Component proof covers real inventory-to-preview wiring, honest proposed
states and stale completion after cancel. No page mount or deployed journey
is claimed. Typecheck and changed-file ESLint pass.

The first preview slice introduced `ImportConfirmation`. The durable slice
below now mounts it through the private import route. Fifteen Python cases pass. Explicit `true`
rights confirmation, the exact manifest digest and one choice per folder are
required. Boolean/numeric/name coercion cannot supply member identity or
consent. Different member assignments for the same source hash are rejected
rather than choosing an owner implicitly. Nullable unmatched choices remain
inventory metadata; no unassigned call is admitted.

## Source and remaining scope

The exact manifest Drive IDs for the required first seven controlled sources
were fetched in their prescribed order, followed by the first-slice source
set, AC-UXA-01 and AC-GOV-AUD-001. All 23 returned IDs matched. The durable
metadata/digest receipt is `/home/acdev/strikes/1676/bulk-import-source-intake.json`;
no raw controlled document content was copied into Git. AC-IMP-03 authority,
tenant and upload consent/provider/retention gates remain binding. An uploader
is distinct from the selected human call owner and organisation processing
principal.

The durable slice below completes those source integrations. Unassigned call ownership needs an explicit owner rule;
the existing intake requires a person. Pending invitations are not members.
The intended 89-recording staging run belongs to Claude after the feature is
available on staging; this source session does not load that corpus.

The prescribed Windows ac-orchestra skill is unavailable on this server, and
no accessible existing Pro chat/artifact was found. Verified local work
continues with that limitation recorded. Strike A page/shell and Strike B
report rendering are outside this change.

## Durable batch and normal intake

Sensitive: migration `20261011_0081`, source/member admission, the account-minute
approval hook and backup parity require CTO/CEO review and the owner's one-tap
approval. No merge or hosted write is performed by this session. PR #436 closed
without merging at the latest read, freeing the shared-file slot.

POST `/imports` records the exact confirmation once under the real uploader,
with immutable tenant, policy, manifest and member decisions. Records contain
digests/IDs/byte bounds rather than raw paths or call content. GET
`/imports/{id}` reads current canonical call/plan/minute state. Both routes keep
the existing account, selected-workspace, origin and private-response guards.

The ordinary source, plan and safe retry routes accept paired
`X-Recording-Import` / `X-Recording-Import-Item` selectors for one exact grant.
The uploader remains the actual authenticated actor. Only this batch's current
uploader/admin may act for its exact confirmed, current member. The adapter
does not fabricate a member session or grant deletion/rename/arbitrary stage
authority. Account-minute exemptions resolve the confirmed member rather than
inheriting an uploader's tester status. Normal member ownership, organisation
processing principal, native measurement, retention, provider plan and ledger
controls remain the processing path.

Source-hash reuse preserves the original canonical owner and avoids another
decode, job or reservation. Admission rechecks after native streaming under
the same normal organisation lock. At most one unfinished bulk call per
organisation is queued; normal uploads remain available. A seven-day batch
window bounds new admission; admitted calls retain their ordinary lease/plan
budgets and member-owned lifecycle after the window or uploader demotion.
Unassigned or removed-member files are metadata only and reserve no minutes.

PostgreSQL proof: four native/cookie/restart cases and two authority/concurrent
receipt cases passed. These cover actual content-sniffed extensionless WAV,
role loss during streaming, duplicate replay after failure, retained owner on
a different-member duplicate batch, normal upload interleaving, exact-header
negative cases, cross-tenant denial, member removal, append-only history,
migration/registry parity, app restart and two racing safe retries renewing
exactly one reservation/job. Twelve registry cases and all three backup/restore
consumer parity contracts passed. All fixtures are fictional; native decode is
real, and no external provider runs. A host-only test bridge retains the
non-secret inherited ac-heavy guardian marker for ffmpeg/ffprobe; the launcher
still verifies live ancestry and the children remain in the acquired slot.
Earlier slot-timeout and fixture failures are retained in strike notes.

`BulkRecordingImport` is an additive island for Strike A to mount with a
server-loaded policy/restored batch. It confirms folder IDs and the one rights
attestation, drives the ordinary source/quote/exact acceptance path, and shows
canonical batch states. Failed calls require explicit Try again. Missing API
data returns unavailable, with bounded reads/uploads and pause/resume. It
never recreates consent on load. Eleven command tests and two component tests
passed; frontend typecheck and changed ESLint passed. No page/shell mount or
authenticated hosted journey is claimed. All files remain local until normal
admission; resumption requires the same folder and fresh explicit consent.
Directory enumeration is sorted by Unicode scalar values before hashing, so
reselecting the same files reproduces the exact confirmed manifest. Lone
surrogates are rejected before canonical UTF-8 hashing; real emoji and
Devanagari remain supported. The final focused run passed 63 Python cases and
36 frontend cases. Ruff, formatting, targeted mypy, typecheck and changed-file
ESLint passed. CI and deployed acceptance remain pending.

## Synthetic continuation

F has published `synthetic-call-bundle/1`, 3,360 transcript/key/report/coaching
folders and multi-year summary data. The owner request for this builder is
sandbox organisations only, superseding the dataset's older Personal option.
The sandbox flag, separate call storage and read integration are still in
progress. No dataset load, verified audio, inferred scoring translation or
official AI scoring is claimed. AC-SVAL-01 was fetched by its exact manifest
ID; synthetic answer keys do not demonstrate instrument validity.
