# Release engine (staging auto-deploy)

`infra/release/ac_release.py` runs on the VPS as root from a systemd timer every
two minutes. It keeps staging on the latest `main` commit that passed CI. It
never builds anything. It downloads the exact bundles CI produced, keeps an
immutable copy in `/srv/authority-closers/release-store/<sha>/`, and runs the
same source-owned installers the laptop script used to run over SSH.

| Piece                                         | Source                                                                                                 | Installed by the engine with                                                                                                                                    |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Core app (API, worker, learner, admin, coach) | `ac-application-<sha>` from `application.yml`                                                          | `infra/application/scripts/install-application-release.sh`                                                                                                      |
| Sales Xray web                                | `ac-sales-xray-web-<sha>` from `sales-xray-web-image.yml` (built only when web inputs change)          | `verify-artifact.py`, `docker load`, compose `up --wait`                                                                                                        |
| Sales Xray activation                         | the running release's `/etc/authority-closers/sales-xray/<env>/activation-<sha>.json`                  | carried forward with `prepare-sales-xray-native-activation.py` (see [Sales Xray activation](#sales-xray-activation))                                            |
| Sales Xray native                             | `ac-sales-xray-native-<sha>` from `sales-xray-native-image.yml` (built only when native inputs change) | retained in `release-store/native/<sha>/`; `prepare-native` admits a staging transition and the automatic core path invokes the artifact-bound native installer |

## One-time setup (owner)

1. Create a fine-grained GitHub token: resource owner `authorityclosers`, only
   `authority-closers-platform`, **Actions: read-only**. Save it on the server:
   `sudo install -d -m 700 /etc/ac-release && sudo bash -c 'read -rsp "Token: " T && umask 077 && printf %s "$T" > /etc/ac-release/github-actions-read.token'`
2. Install from a clean checkout of the reviewed commit:
   `sudo infra/release/install-release-engine.sh`.
   A first install leaves staging auto-deploy **paused**.
3. First supervised deploy: `sudo ac-release deploy staging --dry-run`, then
   `sudo ac-release deploy staging`, then `sudo ac-release resume staging`.

After this one-time install, the engine **updates itself**. When a tick finds
that `main` changed `infra/release/`, it waits for that commit's full
validation to pass, then reinstalls itself from that exact commit (a clean
checkout from its mirror, then `install-release-engine.sh`) and ends the
tick. The next tick runs the new engine. A failed self-install is recorded in
`history` and not retried for the same commit; deploys continue on the engine
already installed. `ac-release status` shows the installed engine commit.

## Commands

| Command                                                                                                              | Does                                                                                                                                                                                                                              |
| -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ac-release status`                                                                                                  | What runs where, pause state, failures                                                                                                                                                                                            |
| `ac-release deploy staging [SHA] [--component core\|web\|all] [--dry-run]`                                           | Deploy a commit on `main` (default: latest)                                                                                                                                                                                       |
| `ac-release pause staging` / `resume staging`                                                                        | Stop or restart automatic deploys; `resume` also clears failure marks                                                                                                                                                             |
| `ac-release rollback staging --component web`                                                                        | Restore the previous Sales Xray web image                                                                                                                                                                                         |
| `ac-release history -n 20`                                                                                           | Recent deploy records (`/var/lib/ac-release/history.jsonl`)                                                                                                                                                                       |
| `ac-release prune-artifacts [--apply] [--keep-recent N] [--no-images] [--json]`                                      | Report, or with `--apply` remove, installer artifacts and core images nothing needs (see [Disk space](#disk-space))                                                                                                               |
| `ac-release store-native SHA [--from ZIP]`                                                                           | Keep a Sales Xray native build for good. Downloads it while GitHub still has it; `--from` adopts a saved copy only if it matches the digest and size GitHub recorded                                                              |
| `ac-release prepare-native staging SHA --previous-native-units PATH --previous-native-units-sha256 HASH [--dry-run]` | Verify an exact native transition and both rollback directions. Without `--dry-run`, save an engine preparation receipt. Both modes leave units, current links, activation publication, approvals and containment flags unchanged |

Logs for each deploy are in `/var/log/ac-release/`.

## Safety rules

- Normal builds require successful `push` validation of `main` from this repository.
  The bounded recovery path below can repackage those already-published images.
  Artifact digests are
  checked against GitHub, and bundle checksums against `SHA256SUMS`. The GitHub
  token is sent only to `api.github.com`, never to the storage redirect.
- A failed **core** deploy pauses staging and is not retried automatically.
  The installer takes a database dump before migrating. If the install fails,
  it restores that dump, the release link and the edge route by itself. The
  engine then waits for a person to decide.
- **Automatic backup support for new migrations.** Before a core deploy, the
  engine checks the backup tool installed under `/usr/local/libexec`. If the
  tool does not recognise the bundle's migration head, the engine installs
  only the backup-scoped foundation from that build's exact commit, after
  checking that the candidate also supports every running environment's head.
  It records `foundation-backup-install` and rechecks the installed tool before
  continuing. Failure still pauses staging; dry runs only report the planned
  step, and application-only rollbacks never install the foundation.
- A failed **web** deploy automatically restores the previous web image.
- Production deploys are refused unless `/etc/ac-release/production.enabled`
  exists **and** the same commit already passed staging. That file is created
  only after the off-host backup restore check passes.
- Admin → Releases production controls are proposed in [ADR 0034](../adr/0034-admin-release-control-through-engine-inbox.md); the inbox consumer and Admin release routes are not implemented yet.

## Admin production controls (ADR 0034)

**Status: engine side in progress.** The engine provides `promote` (with
`--dry-run`), `rollback production` and `publish-status`. The inbox consumer
and the Admin release routes are not implemented yet.

`sudo ac-release publish-status` writes the Admin snapshot (contract v1,
`tests/fixtures/release-control/status-v1.json`) to
`/var/lib/ac-release/admin/outbox/status.json`: a temporary file in the same
folder, fsync, rename, mode 0644, at most 256 KB. Every staging tick that
reaches main also publishes it; a publish error is reported as
`status_publish_error` in the tick result and never fails the tick. A paused
staging tick does nothing, so run `publish-status` after `pause` or `resume`.
The snapshot makes no GitHub calls and at most one mirror fetch.

Production Admin submits intent to the engine through the request inbox. The
production API can create request files but cannot list the inbox. Once the
engine moves a request into the root-only `processed/` directory, the API can
no longer reach it. The root engine consumes each request under its lock and
writes `status.json` plus a per-request result into the outbox using atomic
writes. Staging and production APIs mount the outbox read-only. A systemd path
unit triggers the consumer, with the two-minute engine tick as backup.

Requests use a strict schema and reject unknown keys. The engine moves each
inbox request into the root-only `processed/` directory before handling it, so
a request runs at most once. It reads the moved file once: the opened file must
be regular, not a symlink, no larger than 4 KB, and owned by uid `10001`. The
engine validates only the bytes read from that open file; it never re-reads the
inbox path. It also refuses requests older than 15 minutes, concurrent
requests, and stale expected production commit/version values.

Before writing a request, the production API requires the owner-only
`platform_release_manage` capability, a safe origin, and typed confirmation of
the resulting version; it appends an `audit_events` entry and includes its
`audit_event_id` in the request. It then writes the request and returns `202`
with its id. Status is read from the outbox. Staging Admin cannot submit
production actions.

The engine enforces these production guards on every request:

- Production is enabled only when `/etc/ac-release/production.enabled` exists;
  the off-host backup restore check must have passed.
- The core commit and paired web build must be on `main` and pass staging.
- Compare-and-swap must match the current production commit and version, and
  the engine lock permits one action at a time.
- Rollback can target only the immediately previous release with the same
  migration head as production. Database rollback is forbidden.
- Foundation support for new migrations must be installed first, and the
  Sales Xray approval must have at least one day remaining.
- The engine accepts requests only from the production inbox, which no other
  API mounts, and each request must carry its `audit_event_id`.
- The engine derives the next version from tags and release records.

The API requires the owner to type the displayed resulting version to
confirm. The agreed baseline is current production `v0.2.0`; with no existing
`vX.Y.Z` tags, the first minor promote is `v0.3.0` (D1). Production actions
come only from production Admin; staging Admin is read-only, and CLI is the
fallback (D3). The authorization is a new owner-only `platform_release_manage`
capability, not `platform_access_manage` (D4; see [ADR 0031](../adr/0031-explicit-platform-and-studio-capabilities.md)).

The CLI fallback commands are `sudo ac-release promote --bump minor --version
vX.Y.Z` and `sudo ac-release rollback production`. Both refuse until
`/etc/ac-release/production.enabled` exists. Add `--dry-run` to either to run
every guard and rehearse the steps without changing production, the release
ledger, train state or failed flags. `rollback production` restores the
previous release's core first, then its web, skipping a component production
already runs, and records one `rollback` release only when both succeed. It
refuses (exit 2) when there is no earlier release, the current release is
already a rollback, production runs another pair, a build is no longer stored,
or the database changed; a failed step exits 1. `rollback staging` still needs
`--component core|web`.

## Recover a missing core transport bundle

Use this path only after its release-path change has CTO review and CEO merge
approval. Root operates the host steps. A missing or superseded GitHub bundle
does not authorize rebuilding images, changing the requested release SHA,
creating provenance manually, or invoking the application installer directly.

1. Find the original successful `application.yml` push run on `main` for the
   exact release SHA. Its validation, capacity simulation and image packaging
   jobs must have succeeded. Read the original packaging job log and record the
   four `Digest:` values in publication order: API, learner, admin, coach.
2. Dispatch `application-recovery.yml` from reviewed `main`, passing that
   release SHA, validation run ID and four registry digests. Recovery verifies
   the inputs against the original publication log, pulls by immutable digest,
   verifies each image's source revision and the API marker, and packages the
   images without rebuilding or publishing them.
3. The run must complete successfully with both
   `ac-application-recovered-<release-sha>` and
   `ac-application-recovery-proof-<release-sha>`. The proof binds the original
   validation run and packaging job/log digest, the recovery workflow's actual
   main SHA/run ID, the bundle's GitHub ID/digest, the manifest hash and all four
   registry digests. The engine downloads the small proof first, checks both
   artifacts' actual workflow identities, and checks the bundle manifest
   against the proof before storing provenance. Normal main packaging cannot
   reclaim these recovery names. Both expire after one day; Root must use the
   governed engine to store the bundle before then. Pool and size ceilings still
   apply, including a 64 KiB allowance for the proof.
4. Verify that the installed engine includes the reviewed recovery change, then
   run the exact core staging dry run. A successful packaging run alone proves
   neither admission nor a staging receipt. The engine keeps the proof identities
   in its immutable stored provenance for later promotion or offline reuse.

For [AUT-1216](/AUT/issues/AUT-1216), the original release remains
`fa079c696c024ea46faa98c36c5a8ed741de7894`, validation run `37248476568`, packaging
job `111576281101`. These registry digests were read from that job's successful
publication log:

```text
api=sha256:42d7a5772318f986b2cb2ee4664d6cac42cc05f9587115d47f2cc977ccc3bff2
learner=sha256:1a3e045a23dbfaf2e470ac3ada6c3f1e270aa43925960325da82888aacf07d33
admin=sha256:7b48917af083fbecbb268a38b0742b386405f15b6bdcdafeea2145c3819f293e
coach=sha256:e11480ea65a3bc0e680a10458264827056b9f0286ef618ac1db32b5e38ba3034
```

After reviewed main is installed and the recovery run succeeds, Root's admission
command is:

```bash
ac-release deploy staging fa079c696c024ea46faa98c36c5a8ed741de7894 --component core --dry-run
```

Record the admitted Build, stored provenance and dry-run result on the child.
The actual governed staging core deployment and resulting success receipt belong
to [AUT-1065](/AUT/issues/AUT-1065); this recovery card authorizes no production
deployment, organisation writes, activation changes or new canary.

## Sales Xray activation

### Governed native transition (staging)

Unchanged native inputs continue through the strict existing compatibility proof.
An input change, including a native workflow change, still refuses carry-forward.
It requires the target's own stored ordinary CI artifact and an engine preparation
receipt. `store-native` alone does not install or activate anything.

`prepare-native` validates the original successful main push, first run attempt,
repository/run/artifact identities, the retained ZIP digest and
size, all bundle checksums, committed source tree/recipes/helper bytes, the OCI
index/manifest/config/layers, and the image environment bindings. It refuses an
incomplete target record or one recorded as expired at store admission. GitHub's
retention deadline does not invalidate a retained ZIP whose recorded digest,
size and ordinary run/source identities still verify. Approval expiry remains
a live guard. It also checks target/predecessor ancestry,
approval lifetime (at least one day), exact approval bytes, the predecessor's
immutable helper/image, rendered unit descriptor and installed unit bytes,
active/enabled units and socket/mount readback. The prior renderer, core bundle,
healthy core identity, backup support and equal migration heads must be available
for the canonical application-only rollback. Missing rollback pins refuse before
Docker load, unit replacement or activation publication.

The predecessor descriptor must come from the existing root-owned staging
operator inputs and be pinned by its recorded SHA-256. Read that path/hash from
the successful native installation receipt; do not generate a substitute unit
descriptor or provenance record. The engine's reviewed native installer permits
the verified current core release renderer to supervise a target helper before
the target core source is installed. This override is an internal engine API;
there is no new standalone native-install CLI option.

Preparation is keyed to the stored native build **N**, rather than a core SHA.
The existing timer deploys the latest validated main core **T**. It consumes N's
receipt only while its predecessor pins still match, N is an ancestor of T,
and `native_artifact_compatibility.source_inputs(T)` equals N's inputs using the
unchanged strict comparison, including the native workflow. T's activation uses
N's immutable manifest/helper. A further native input change refuses before
runtime mutation. Completed receipts do not govern a new predecessor; ordinary
strict carry-forward takes over after successful delivery.

Each eligible core deploy reruns these checks, checks the
receipt's artifact/controller/approval/predecessor pins, prepares the matching
activation without approval replacement, and rehearses the target units. A dry
run uses disposable stages and publishes no activation or preparation receipt.
It does not load an image or start/stop units, and does not clear pause/failure
marks. Existing immutable store admission and mirror/log activity are separate
from runtime changes.

On automatic deployment the engine retains both immutable artifacts, saves the
predecessor descriptor beside the candidate, and records `native-transition:
armed` before loading the target image and invoking the existing artifact-bound
installer. It then publishes the activation using permanent operator-input
paths and invokes the core installer. Failure in native install/start/readback,
activation publication, core installation or subsequent core readiness restores
the pinned predecessor helper and units first, then uses the installed reviewed
controller's `AC_CORE_ROLLBACK_ONLY` path to restore the prior core without
database migration/restore. Recovery verifies the old activation hash and healthy
core. Created target publication is removed after restoration; its immutable
operator bundle and all receipts remain. Staging stays paused with the failed
target recorded. Unverifiable recovery records `recovery-failed` and keeps
containment. Transition receipts retain their core rollback bundles/images from
normal pruning. The operation is staging-only and does not change production
holds or provider authority.

### Pause-preserving engine bootstrap and exact recovery handoff

Root operates these commands only after sensitive CTO review and CEO SHA-bound
merge approval. This source card authorizes no host execution. The installed
engine's paused tick returns before self-update; keep staging contained and
install the reviewed source through the existing engine installer instead.

1. Record the merged repair SHA and successful ordinary CI run, and the prior
   installed engine SHA/hash. Use Root's existing clean source checkout at the
   exact reviewed merged commit. Verify `git rev-parse HEAD` and a clean status;
   no edited installed engine file or application/native installer invocation
   is an acceptable bootstrap.
2. Record hashes/bytes of `staging.paused`, `staging.core.failed`, every unrelated
   production pause/failure/inflight flag and production enablement. Verify the
   existing tick/train/watch timers already exist and are active/enabled, so
   this route adds no timer or timer enablement. Refuse this route if that
   prerequisite differs; record the concrete host repair on the Root parent.
   Review the installer and its installed unit/module file list against the
   source pin before running it.
3. From that exact clean checkout, under the engine's canonical lock, run:

   ```bash
   sudo flock --exclusive /run/ac-release.lock bash infra/release/install-release-engine.sh
   sudo ac-release status --json
   sudo ac-release prepare-native --help
   ```

   The supported installer switches `/opt/ac-release/current` to the immutable
   source release. On an existing installation it leaves state/hold flags
   untouched. Read back the installed SHA and `ac_release.py` hash against the
   reviewed checkout, all preserved flags byte-for-byte, and the unchanged
   running core/web identities. If installation fails or readback differs,
   reinstall the recorded previous exact clean source through the **same**
   locked installer, and verify those same flags/identities; do not repoint the
   engine link by hand or clear staging containment. Root retains this host
   installation and rollback evidence on its existing recovery parent.

4. For the already built recovery target, use the recorded predecessor unit
   path/hash. These are operators' receipt pins, not values to invent:

   ```bash
   native_sha=386f28ba6f046fd2dda1727ca6736f9260f79709
   sudo ac-release prepare-native staging "$native_sha" \
     --previous-native-units "$previous_units_path" \
     --previous-native-units-sha256 "$previous_units_sha256" --dry-run
   sudo ac-release prepare-native staging "$native_sha" \
     --previous-native-units "$previous_units_path" \
     --previous-native-units-sha256 "$previous_units_sha256"
   sudo ac-release deploy staging --component core --dry-run
   ```

   Preserve the preparation receipt and exact native/activation/core dry-run
   evidence on the Root parent, including the current-main core SHA T and native
   source N printed by core dry-run. Do not supply N as the core deployment SHA:
   the timer advances main. The recorded native bundle/run is reused; no CI rerun,
   rebuild or manual native installation is authorized. If any check refuses,
   keep containment and report the exact missing or changed binding.

5. After Root verifies all checks and the parent's authorized recovery guards,
   Root may run `sudo ac-release resume staging`. Let the **existing timer**
   perform the automatic deployment; do not invoke deploy apply or manual tick.
   Record resulting core/native/activation identities, unchanged approval hash,
   automatic success receipt and health, or containment/rollback evidence.

The source handoff must replace the merge SHA placeholder in Root's receipt with
the exact reviewed merged commit and its CI identity before host installation.
The source issue is not complete on PR approval: it needs merged green source,
this reviewed bootstrap route and exact invocation evidence. Root owns the
installed capability and ultimate live staging proof on the recovery parent.

A core release that runs hosted Sales Xray needs its own activation
descriptor. The installer refuses a release without one. For each core deploy
(real or dry run), the engine does the following:

1. Does nothing if the target already has an activation, or if the running
   release has none (hosted Sales Xray is not active there).
2. Refuses if the running approval, or its acquisition policy, lapses within a
   day. `ac-release status` shows each environment's approval end date.
3. Finds the loaded native artifact behind the running native image and builds
   the native reuse proof from `release-store/native/<sha>/` and its git mirror.
4. Runs the repository tool `prepare-sales-xray-native-activation.py` with the
   approval **carried forward unchanged** into
   `application/operator-inputs/<env>/release-<sha>-<time>/`. It then installs
   the descriptor and its digest (mode 0444). A dry run prepares inside its
   temporary stage and publishes nothing.

After the installer, the core check also waits for `sales-xray-worker` to run on
the release's API image and to stay up for 30 seconds without restarting.

The engine never creates, renews or widens an approval. A new approval (new
limits, testers or providers) is still prepared by a person against a new
release. The engine also pauses staging, with a message, in two cases:

- the release changes the native image inputs (use `prepare-native` with the
  target's stored ordinary CI bundle and recorded predecessor pins first);
- the running native build is not stored and GitHub has already dropped it
  (adopt the saved copy with `store-native --from`).

## Disk space

Two stores keep core release bundles on the server:

| Store                                                 | Holds                                                                                                                            | Cleaned by                                                                              |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `/srv/authority-closers/release-store/<sha>/`         | The engine's downloads                                                                                                           | The engine, after each successful deploy: what runs plus the last 10 successful deploys |
| `/srv/authority-closers/application/artifacts/<sha>/` | The installer's immutable copy of every core bundle it installed (about 390 MB each), plus the four images it loaded into Docker | `ac-release prune-artifacts`, run by the owner                                          |

GitHub keeps each bundle for one day, so these copies are the only local way
to reinstall an older release. Once a copy is removed, reinstalling that
release needs its bundle from the release store, or a new package from the
_Application release package recovery_ workflow.

### What `prune-artifacts` keeps

A core artifact stays if any of these is true. The report prints the reasons.

1. `current-staging` or `current-production` points at it.
2. An environment's records in `application/deployments/<env>/` name it at or
   after the last `COMMITTED` record. That covers the `AC_PREVIOUS_RELEASE`
   rollback target, any later unfinished attempt, and any
   `FORWARD_RECOVERY_REQUIRED` release, whose recovery is to reapply that exact
   release.
3. A file under `application/deployments/` or `application/operator-inputs/`
   names `artifacts/<sha>`. Files over 1 MB are not scanned.
4. It is one of the newest N (`--keep-recent`, default 10), by the time it was
   written.
5. A governed native preparation/transition receipt pins it as the target or
   prior core rollback source.

A core image (`authority-closers-api`, `-learner-web`, `-admin-web`,
`-coach-web`) stays if any container uses it, or if it belongs to a kept
release (by its tag or that release's `release-images.env`).

It never touches:

- `sales-xray-native-<sha>` directories, because the native systemd units run
  their helper from there;
- `sales-xray-web-<sha>` bundles and the installer's `.stage-*` directories;
- Sales Xray web and native images, foundation and third-party images, and
  untagged images.

The report lists their size. The native units start their image only for a
job, so Docker counts it as unused. **Do not run `docker image prune -a`**: it
would delete the live native image.

The command stops without removing anything when a current link or deployment
record is not what the installer writes, or when a file it must scan cannot be
read.

### Running it

```bash
sudo ac-release prune-artifacts
sudo ac-release prune-artifacts --apply
```

The first command is the dry run: every entry marked keep or remove, with its
reasons and size. The second removes what the dry run marked remove. Before the
engine is installed, run the same commands from a clean checkout of the
reviewed commit as `sudo python3 infra/release/ac_release.py prune-artifacts`.

`--apply` runs only as root. It refuses while an engine run or an installer
holds its lock (`application/.deployment.lock`), and it decides again after
taking both locks. Each artifact is renamed to `.prune-<sha>.<random>` before it
is deleted, so an install never sees a half-deleted bundle. The next run
finishes any interrupted removal. Images are untagged with `docker image rm`,
never with `--force`. The outcome is appended to `history.jsonl`.

Dry run on 2026-09-28:

- **Core artifacts:** 109 (31.4 GB). Keep 14 (5.4 GB), remove 95 (26.0 GB).
- **Core images:** all 20 belong to the five kept releases that have images
  loaded, so none would be removed.
- **Unmanaged:** 60 Sales Xray entries (8.0 GB) and 19 Docker images were left
  alone.
