# Development approval re-seal: AUT-1083 / AUT-1089 / AUT-1117 / AUT-1158 / AUT-1197 / AUT-1460 / AUT-1515

Root Operator runs this tool from the **merged, released, root-owned application
scripts directory**, after CTO review and CEO merge approval. Engineers do not
read the live sources, install the tool, or apply it. The existing tester
authorization is CEO comment `13688c66-c67e-483a-831d-4b39b6463069` on
[AUT-1083](/AUT/issues/AUT-1083); this tool does not request new authorization.

The repair admits exactly the canonical candidate's appended tester
`2c3d2101-ab7d-5ffd-bf12-b57f66a60751`, `ref:approval/AUT-1083`,
`account_minutes` only. It rejects all other policy changes. The email is
masked in output; the candidate digest binds its already-approved identity.
It never regenerates the candidate or uses `approval-candidate.json`.

| Immutable input | Pin |
| --- | --- |
| Original default serving backend source | `b9f2f70e35c821f72d4f59184a8850977d696aad` |
| Explicit serving source verified by Root on 4 October 2026, 23:02–23:08 UTC | `97f908fa557404ab88bdb494766473643a7dc601` |
| Historical serving source verified by Root on 7 October 2026, 00:01–00:06 UTC | `ce753781ba69f9b2e74b9300619473173bab2be1` |
| Preserved existing template release | `1e784afa128f8d4629aeece5179486d423c0ec52` |
| Existing approval SHA256 | `07ca6c4ea9587ff81b7bd97a891eb81f1195179ca4eb3ff8fa03205267225881` |
| Canonical candidate SHA256 | `72343b19c3028c21dd16fd51d455b6dfdd1008e570f14778abbd8fd3aeb3d217` |
| Canonical candidate path | `/srv/authority-closers/application/operator-inputs/development/aut-1083/approval-candidate-canonical.json` |

The tool intentionally keeps the serving source unchanged while adopting
configuration from a newer reviewed tool release. If any input pin differs,
Root reports the stable failure code on AUT-1083; do not edit the inputs or
relax the tool's pins. The tool release SHA and checksums must be taken from
[AUT-1515](/AUT/issues/AUT-1515)'s final merged/released handoff, rather than a moving `current-staging`
symlink or an agent checkout.

`--serving-release-id` accepts one lowercase 40-hex commit SHA. Omitting it keeps
the original default; it never discovers a release or resolves a moving symlink.
Root must independently verify the serving source before each run: backend Git
HEAD and marker, API release override, current service release and authenticated
readiness must agree. The tool checks these inputs, runtime identity/contract and
loopback readiness against the supplied pin. If dev advances again, Root records
that evidence and explicitly supplies its actual verified source in every command.
This changes neither approval digest, tester scope nor the template's release.

## Dry-run and apply

Execute as Root, one operator at a time, outside a release. Substitute the
exact merged/released tool SHA from the handoff below. Check all three script
checksums against that release's source-reviewed files before executing.

```bash
RESEAL_TOOL_RELEASE=<merged-released-tool-sha>
RESEAL_SERVING_RELEASE=<freshly-verified-serving-sha>
RESEAL_RELEASE_DIR=/srv/authority-closers/application/releases/${RESEAL_TOOL_RELEASE}
RESEAL_DIR=${RESEAL_RELEASE_DIR}/scripts
RESEAL_SCRIPT=${RESEAL_DIR}/reseal-dev-sales-xray-approval.py
(cd "$RESEAL_RELEASE_DIR" && sha256sum --check --strict RELEASE-FILES.sha256)
sha256sum "$RESEAL_SCRIPT" \
  "$RESEAL_DIR/refresh-dev-sales-xray-backend.py" \
  "$RESEAL_DIR/prepare-sales-xray-native-activation.py"
python3 "$RESEAL_SCRIPT" --serving-release-id "$RESEAL_SERVING_RELEASE"
```

Root records the exact reviewed source commit and merged tool release, all three
script hashes, the complete `RELEASE-FILES.sha256` and its successful strict
verification, `RELEASE-COMMIT`, and the non-secret `release-images.env` provenance.
Compare all three installed script blobs with the reviewed merged source, and
record regular-file ownership/modes and unchanged source metadata. A successful
three-script checksum alone does not verify the complete immutable release.
Record the fresh serving-source evidence and masked command exits/run ids with
the dry-run/apply/rollback handoff; neither a branch nor a moving symlink is a pin.

Dry-run is the default. It acquires the installer's existing
`application/.deployment.lock` without creating a file, reads trusted regular
root-owned sources, verifies the serving Git revision and marker, and validates
the current service and both approvals in a network-isolated
uid/gid-10001 transient unit. systemd opens root-only sources and delivers
uid-private credentials to this unit. The application contract never runs as
root. Dry-run does not write files or restart managed services.

### Exact historical baseline format

[AUT-1460](/AUT/issues/AUT-1460) preserves the original approval's sorted,
indent-2 JSON plus LF bytes. After checking those raw bytes against the fixed
before SHA256 `07ca6c4ea9587ff81b7bd97a891eb81f1195179ca4eb3ff8fa03205267225881`,
the tool uses the unchanged hosted parser's canonical representation **only in
memory** for that baseline's validation. The unchanged replacement helper then
checks the complete current hosted policy and provider/service bindings against
both service and template. Service pins still refer to the original raw digest.

Compatibility requires both the supplied before pin and the current raw digest
to equal that fixed approved digest. Other formatted baselines receive no
exception. The candidate always goes directly to the strict replacement helper:
its exact after digest, canonical hosted bytes and sole appended
`account_minutes` tester diff remain mandatory. No live approval, candidate,
helper or global parser is reformatted or regenerated. Backups and rollback
retain and restore the original raw bytes, including whitespace and final LF.

The historical trigger used tool release
`5092cbe1532589afcadc71205fea4438c1192913` and re-seal script SHA256
`d62b90bf57f0bec9a35d03ef20f1bee5f8f33e1038324c5cf5f349d1b71b8c25`.
Those pins identify the failing release, not the repaired release to execute.
All existing authorization, holds, locks, template release and immutable helper
hashes remain unchanged.

### Reviewed code delivery at uid10001

The immutable release's scripts and directory are root:acops mode 0750.
A read-only bind preserves those permissions; uid/gid10001 cannot execute or
import the scripts there. The manager now delivers these exact source files
as credentials named `reseal-dev-sales-xray-approval.py`,
`refresh-dev-sales-xray-backend.py`, and
`prepare-sales-xray-native-activation.py`. It never changes release permissions
or runtime group membership.

Before starting the transient unit, the tool requires trusted root-owned
ancestors and regular, single-link, mode-0750 script files without xattrs.
It compares its own bytes with the digest captured when loaded and both helper
bytes with their fixed reviewed hashes. At uid/gid10001, a bootstrap checks
the exact private credential directory, absence of extra groups, all three
names, confidentiality through the serving contract's existing file/ACL
checks, and all three hashes before executing/importing delivered code.
Only hashes and fixed arguments go in argv. Code, approval and service
credentials use the runtime-private systemd directory; the code directory
is no longer bound into the sandbox.

This delivery runs in dry-run/apply preflight, the apply recheck before backups,
post-adoption verification, rollback preflight using saved inputs, and exact
restoration verification. Memory/CPU/task limits, network isolation, suppressed
output and every existing hold, source/approval pin and rollback guard remain
in place. Missing, untrusted or tampered source/delivered code refuses before
the preflight can admit durable-input or managed-service changes.

### Root-only fictional runtime proof

The normal engineer suite simulates systemd and skips four explicit Root cases.
Root must run all four cases from a root-owned copy of the exact reviewed commit,
with pinned dependencies, before live adoption. The test creates only fictional
private inputs and copies of the three reviewed scripts. It gives those copies
root:acops0750 ownership/modes, then uses real systemd and the development
backend's existing interpreter and contract at uid/gid10001. It proves the
original copies remain unreadable, all delivered bytes validate successfully,
missing/tampered credentials fail, and fixture bytes and source permissions
remain unchanged. The additional full-contract lifecycle test exercises default
dry-run, apply preflight/recheck, post-adoption validation, idempotence, rollback
preflight and exact raw-byte restoration. Every credential validation runs at
real uid/gid10001 through the reviewed code/hash bootstrap and hosted validators
in the unchanged network-isolated sandbox. The outer host/unit operations are
simulated; all written approvals, backups and receipts are fictional fixtures.
Neither test changes a managed service, provider, database or live input.

The full lifecycle runs separately with fresh history, the exact empty 2700
residue, and private history containing prior fictional audit entries. Its
operator-input ancestors are root:acops2750 and root:acops2700, matching the
reported live metadata. All five backups retain exact raw bytes; history/run
directories finish at 0700 and backup/plan/event files at 0600. Existing audit
entries and ancestor permissions stay unchanged.

The lifecycle harness maps the interpreter, working directory and existing
read-only backend bind together to Root's independently verified backend.
The release-marker bind and every credential source remain fictional fixtures;
all sandbox properties stay unchanged. Mapping only the interpreter leaves it
hidden by the sandbox's private `/srv/authority-closers` view and fails before
validation (`203/EXEC`), as recorded by [AUT-1489](/AUT/issues/AUT-1489).

Fictional fixtures cannot have the approved historical digest. The full-contract
test harness substitutes its fictional before digest **in process memory only**
after the unchanged bootstrap checks all delivered script hashes. It executes
the exact reviewed validation function and changes no helper, parser or source
bytes. This substitution exists only in the test harness; the supported tool has
no alternate-pin option. The separate delivery test runs the original bootstrap
without substitution and proves missing/tampered credentials fail. Ordinary
regressions prove an unapproved formatted baseline receives no compatibility.

Root supplies the exact backend from its verified unit metadata and uses the
run-owned `PAPERCLIP_RUN_SCRATCH_DIR` under `/tmp`. Keep the archive, dependency
environment and fixture directory root-owned and private mode 0700; do not
substitute a live credential path. The test verifies the exact three original
script files exist as regular root:acops0750 files with the reviewed hashes and
unchanged metadata before probing their unreadability at uid/gid10001. The
unchanged private-/tmp sandbox can hide these existing host paths, so either
`PermissionError` or `FileNotFoundError` proves they cannot be opened there.
Readable sources and all other I/O failures still fail; absence on the host
never qualifies as sandbox denial. No bind, permission or group change is needed.

Before adoption, repeat from the exact approved test archive against the
explicitly nominated immutable tool release, with the optional
`AC_RESEAL_REVIEWED_SCRIPT` source override. A newer release must be reviewed as
containing all three identical approved runtime scripts; never resolve a moving
release symlink. Root uses the existing audited wrapper and both release and
application locks, and the archive's frozen dependency environment:

```bash
AC_RESEAL_RUNTIME_PROOF=1 \
AC_RESEAL_PROOF_BACKEND=<verified-development-backend-directory> \
AC_RESEAL_REVIEWED_SCRIPT="$RESEAL_SCRIPT" \
"$PAPERCLIP_RUN_SCRATCH_DIR/proof/.venv/bin/python" -m pytest \
  "$PAPERCLIP_RUN_SCRATCH_DIR/proof/tests/infra/test_reseal_dev_sales_xray_approval.py" \
  -k root_only_real_uid10001 -q --tb=short \
  --basetemp="$PAPERCLIP_RUN_SCRATCH_DIR/proof/fixtures"
```

Record the source commit, installed path, three script hashes, actual uid/gid,
zero additional groups, the test result and unchanged-source result on
[AUT-1083](/AUT/issues/AUT-1083). A skipped test or mocked success does not satisfy
these runtime proofs. Before review, Root records the non-skipped fictional
proofs on its concrete child of [AUT-1515](/AUT/issues/AUT-1515); the repaired
immutable-runtime proof and live execution remain on
[AUT-1083](/AUT/issues/AUT-1083). Reverify the serving source independently before the
pinned dry-run/apply/rollback commands; the historical source above is not an
automatic claim about the current deployment.

Before any durable write, API and outbox file **and running-process** holds
must be `true`; their environment must be `development`. The refresh timer
must already be inactive and disabled, and refresh service inactive. The tool
does not change holds, timers or the outbox. Transitional/failed unit states,
untrusted files, policy changes, stale pins or missing credentials are refused.

### Loaded credential sources on systemd 255

Root's captured `systemctl show ... --property=LoadCredential --value` response
was `LoadCredential=[unprintable]` for both API and dedicated worker. This is a
display limitation, not evidence of missing credentials. The tool now reads the
loaded manager property through `busctl --system --json=short --no-pager`:

1. Call `org.freedesktop.systemd1.Manager.GetUnit` with the exact unit name.
   Require an `o` response with one valid systemd unit object path.
2. Read `org.freedesktop.systemd1.Service.LoadCredential` at that returned path.
   Require the `a(ss)` signature and an array of two-string identifier/source pairs.
3. Reject malformed JSON/envelopes, duplicate JSON keys/credential identifiers,
   invalid identifiers or paths, missing required sources, wrong sources, and
   command/D-Bus failures before any backup, write or managed-service mutation.

The captured API mapping contains `approval.json` from the exact development
approval source. The dedicated worker additionally loads `service.json` from
the exact development service source. Source paths remain exact comparisons;
the parser does not infer them, read static unit text, or accept a printable
sentinel. The [systemd 255 busctl implementation](https://github.com/systemd/systemd/blob/v255/src/busctl/busctl.c)
defines the typed JSON envelopes: `GetUnit` has `{"type":"o","data":["..."]}`;
`get-property` has `{"type":"a(ss)","data":[["identifier","source"]]}`.

These reads return metadata only. The independent adopted-credential bytes,
hashes, regular-file/root-owner/mode and process-pin checks remain required.
The same retrieval runs in dry-run/apply, the apply recheck, post-adoption
verification, rollback preflight and restoration verification. No live unit
configuration or credential is changed by this representation repair.

Post the masked dry-run result on AUT-1083, then execute its already-authorized
apply:

```bash
python3 "$RESEAL_SCRIPT" --serving-release-id "$RESEAL_SERVING_RELEASE" --apply
```

Apply first saves root-only exact byte backups and a plan containing source,
approver/comment, five before/after hashes, modes, owners, guards and unit
states. It stops only the API and dedicated worker so consumers cannot observe
partly updated pins. It atomically renames each of these five files:

1. `/etc/authority-closers/development/approval.json`
2. `/etc/authority-closers/development/api.env` (existing approval digest only)
3. `/etc/authority-closers/development/service.operator-template.json`
4. `/etc/authority-closers/development/service.json`
5. `/etc/systemd/system/ac-dev-sales-xray-worker.service.d/manifest.conf`

Every other byte in the environment, template and service is preserved,
including the template's prior release identity. The worker's new digest pins
the exact updated service bytes. After daemon-reload, only previously active
API/worker units restart; previously inactive units remain inactive. The tool
checks loaded credential bytes, API process approval digest, holds, timer,
unmodified outbox/release/native files, prior unit states and loopback API
readiness at the same release. A repeat apply is a validated no-op.

Success prints `run_id`. Root keeps backups under mode-0700
`.../operator-inputs/development/aut-1083/reseal-history/<run_id>/`; backup and
receipt files are mode 0600. Receipts append rather than overwrite history.
Only bounded masked fields, hashes and command exit codes leave the process.
No approval email, environment value or command output is reported.

### Private history under setgid ancestors

The refused apply on 7 October created an empty root:acops2700 history directory
under a trusted root:acops2700 parent: Linux inherited setgid despite
`mkdir(mode=0700)`. That refusal happened before run-id allocation, backups,
consumer stops or target writes. Root must not repair this residue manually.

The supported apply opens each directory with `O_DIRECTORY|O_NOFOLLOW`, verifies
ownership, exact mode and absence of xattrs on its descriptor, and clears
inherited setgid with `fchmod(0700)` before writing backups. Newly created
directories may inherit 2700 from a trusted setgid parent with the same group.
An existing 2700 directory is admitted only at the history path, only when
empty, with no xattrs, and under an exact trusted 2700 parent with the same
group. Existing private 0700 history can contain prior audit entries; they are
preserved. Existing run-id collisions, symlinks, foreign owners, group/other
access, unexpected bits, xattrs and nonempty 2700 history refuse.

After normalization, the tool rechecks exact 0700 ownership/mode, xattrs and
the pathname's inode against the opened descriptor, then fsyncs the directory
and parent. The new plan records each directory's creation flag, before/final
modes and final owner/group in `audit_directories`. It never changes ancestor
permissions or overwrites prior history. Rollback only verifies strict 0700
history and run directories; it does not normalize them. Dry-run leaves the
empty residue untouched. This repair keeps both approval hashes, helper pins,
hosted validators, template release and existing operator authorization intact.

## Rollback and verification

An adoption/write/health failure attempts exact byte, metadata and prior
active/inactive state restoration automatically. Exit 2 with
`apply_failed_restored` means verified restoration succeeded; `rollback_failed`
requires Root recovery. Preserve the plan, backups and all event receipts.
If interrupted, locate the latest run directory's `plan.json` as Root; do not
copy backup approval/environment bytes into chat or Git.

Rollback is also dry-run by default:

```bash
RESEAL_RUN_ID=<run-id-from-apply-or-plan>
python3 "$RESEAL_SCRIPT" --serving-release-id "$RESEAL_SERVING_RELEASE" --rollback "$RESEAL_RUN_ID"
python3 "$RESEAL_SCRIPT" --serving-release-id "$RESEAL_SERVING_RELEASE" --rollback "$RESEAL_RUN_ID" --apply
```

Rollback admits only recorded before/after bytes and metadata for the five
targets, and requires unchanged outbox, release marker, API release drop-in
and native descriptor. The supplied source must match the plan's recorded release,
and the plan must record both fixed approval digests. Rollback rechecks serving Git HEAD/cleanliness,
marker, API override, current service release, runtime identity/contract and
readiness before writes. Isolated validation uses the trusted saved approval,
service and template credentials, so it can recover an interrupted mixed-pin
write without treating those mixed files as a valid runtime configuration.
Either recorded worker pin may still be loaded after
an interruption before daemon-reload. Holds and disabled refresh still apply.
Rollback stops only API/worker, restores backups, adopts the prior states and
verifies credentials and health. A repeated completed rollback is a no-op.

Root then performs AUT-1083's authenticated verification: workspace HTTP 200
with `intake_enabled:true`, acquisition enabled, submissions HTTP 200, the
exact serving source, and preserved holds/timer. Post the run ID, masked result
and endpoint outcomes on AUT-1083. There is no database write, migration,
provider call, outbox/native restart, rebuild, public route or staging/production
operation in this repair. This local tool test evidence does not replace Root's
live credential and endpoint verification.

## Implementation evidence

Reviewed script checksums for this handoff:

| Script | SHA256 |
| --- | --- |
| `reseal-dev-sales-xray-approval.py` | `44cfd752f5c57d937ffffb42de312916de9d903b7d202808ed4c717af121f391` |
| `refresh-dev-sales-xray-backend.py` | `951c82dcb3390ba1e0ffe836d2032deb9aee86c1232d2d8452674da5a6b8feb3` |
| `prepare-sales-xray-native-activation.py` | `0e553343b07e24e7d998085753f36d061591f2990c42761c5824a1926ef41f35` |

The tool also enforces the two helper digests before it imports their code.
The helper bytes and constants are unchanged from this task's latest-main base
`bafeafc1533a717cb00062a06130cdb20027ce26`. The refresh digest was already updated
on main by [AUT-477](/AUT/issues/AUT-477); do not substitute the prior installed
[AUT-1460](/AUT/issues/AUT-1460) helper when executing this new three-script set.

```bash
uv run ruff format --check infra/application/scripts/reseal-dev-sales-xray-approval.py \
  tests/infra/test_reseal_dev_sales_xray_approval.py
uv run ruff check infra/application/scripts/reseal-dev-sales-xray-approval.py \
  tests/infra/test_reseal_dev_sales_xray_approval.py
uv run pytest tests/infra/test_reseal_dev_sales_xray_approval.py \
  tests/infra/test_refresh_dev_sales_xray_backend.py \
  tests/infra/test_refresh_dev_sales_xray_backend_only.py \
  tests/unit/test_prepare_sales_xray_native_activation.py -q
```

Tests use fictional private files and simulated Root commands. They cover
zero-write dry-run; permitted append and rejected policies/scopes; agreement
of all pins; unchanged environment/service/native/release bytes; idempotence;
holds/timer and file trust; isolated runtime contract/expiry checks; secret-free
reports; partial-write, restart and health failures; exact byte/state rollback;
and explicit rollback default/idempotence/guard checks.

Prior AUT-1117 local result (4 October 2026): 81 re-seal tests passed; the 59 unchanged
refresh/preparation regression tests also passed (140 total). The later coherent
source succeeds and preserves the template release; wrong supplied, Git, marker,
API, service and readiness pins refuse writes/service mutations. Malformed pins
fail before protected reads. CLI routes the same source with fixed approval
digests in all modes; plans, receipts, adoption and rollback retain that source.
Repository Python format/lint and the task gate also passed. No live protected
file was read and no host
operation was executed by the engineer.

AUT-1158 local result (4 October 2026): 324 re-seal tests and the same 59 helper
regressions passed (383 total). Captured API/worker typed mappings are admitted
despite the systemd 255 printable sentinel. Missing/wrong/duplicate sources,
invalid signatures/envelopes/entries/identifiers/paths, malformed JSON/UTF-8 and
GetUnit/property command failures refuse in dry-run/apply and rollback
dry-run/apply, with no file writes, managed-service changes or leaked command
output. Typed source admission still requires independent adopted-credential
verification. Python format/lint and diff whitespace checks passed. Root's live
verification, CTO review, CEO SHA-bound approval and immutable release handoff
remain required; these fixture results do not claim adoption or intake success.

AUT-1197 local result (5 October 2026): 408 re-seal tests and 59 unchanged helper
regressions passed (467 total). The explicit real-systemd Root proof was skipped
because the engineer runs at uid1002 and cannot operate host services.
Source-file absence, tampering, symlink/hardlink and writable-mode failures
refuse all four dry-run/apply/rollback modes before backups or service mutations.
The bootstrap independently rejects missing/tampered/public/symlink/empty
delivered code, wrong uid/gid, extra groups and wrong credential contexts before
execution. The suite checks every sandbox property, exact three source names,
digests and private credential delivery, plus the apply and restoration rechecks.
Python format/lint and diff whitespace checks passed. Root's real uid10001 proof,
CTO review, CEO SHA-bound approval, normal release and live adoption/endpoint
verification remain outstanding; this result does not claim any of them.

AUT-1319 local result (6 October 2026): 425 re-seal tests and the same 59 helper
regressions passed (484 total, 68.66 seconds). The explicit real-systemd Root
proof was skipped in the engineer suite. Seventeen new cases execute the exact
denial probe: both sandbox denial outcomes pass for all three source names;
readable sources and unrelated I/O failures at each position, wrong uid/gid and
extra groups fail. The Root test additionally binds denial to exact existing,
regular root:acops0750 sources with all three reviewed hashes and unchanged
metadata. Missing/tampered private-code negatives and final fixture/source
preservation assertions remain in place. All three runtime script checksums
above are unchanged. Python format/lint, diff whitespace and the task gate
passed. The reviewed test archive and explicitly nominated immutable release
must be pinned in the handoff; Root independently repeats the corrected proof
on [AUT-1313](/AUT/issues/AUT-1313). This local result does not satisfy that proof
or claim any live adoption.

[AUT-1460](/AUT/issues/AUT-1460) local result (7 October 2026): 530 focused re-seal,
refresh and preparation regressions passed; the two Root-only proofs were
explicitly skipped. The formatted fictional baseline and compact candidate pass
the complete hosted credential validator through every adoption/restoration
phase. Fifteen negative input cases run in dry-run and apply, refusing before
durable writes. The test-only pin-substitution harness also passes through the
unchanged reviewed code/hash bootstrap and complete validator locally. Python
format/lint, diff whitespace, branch admission and PR single-track gates pass.
The runtime-mapping regression verifies that the interpreter's backend is both
the working directory and read-only bind, while the fictional release marker,
credentials, all sandbox properties and validator arguments stay unchanged.
These results do not claim the real uid10001 proofs, approval, merge, immutable
release or live adoption; Root's non-skipped child proof precedes CTO review.

[AUT-1515](/AUT/issues/AUT-1515) local result (7 October 2026): 566 focused
re-seal/refresh/preparation regressions passed; four real Root cases were
explicitly skipped at engineer uid1002. Fresh setgid history, the exact empty
2700 residue, and existing 0700 audited history pass the full hosted contract
through apply/recheck/adoption/idempotence and rollback with all five exact raw
backups and metadata. Direct run-directory creation clears actual inherited
setgid under both 2700 and 2750 parents. Unsafe history ownership/modes/xattrs,
symlinks, nonempty residue, foreign group, run collisions and failed/ineffective
normalization refuse; rollback rejects untrusted history/run metadata without
repair. Prior audit entries and trusted ancestors are preserved. Python
format/lint, diff whitespace and branch admission pass. Root's four non-skipped
uid10001 cases, sensitive CTO review, CEO SHA-bound approval, CI/merge, immutable
manifest/provenance and installed-source verification remain required before
the pinned live handoff on [AUT-1083](/AUT/issues/AUT-1083). No engineer live
protected read, host permission/service change or live adoption was performed.
