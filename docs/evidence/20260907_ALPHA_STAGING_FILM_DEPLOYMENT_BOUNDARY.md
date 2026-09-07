# Staging film deployment boundary — 2026-09-07

## Implemented, not activated

Repository-controlled deployment support now exists for the reviewed two-film
technical sample package. The committed policy candidate is **off**; this task
did not enable a release, upload media, modify the VPS, create database state,
start Docker, repair WSL, or commit changes.

Ownership is confined to application infrastructure, focused infrastructure
tests, and this evidence. Existing application/media authorization remains the
byte-serving authority; this change supplies immutable files and API-only mount
composition, not grants, lessons, enrollments or progress.

## Exact source authority

- `infra/application/capabilities/staging-public-films.json`: fixed staging-only
  schema, Boolean enable switch, exact manifest hash; no path/provider fields.
- `infra/application/data/alpha_public_films_12s_v1.json`: exact byte mirror of
  `packages/python/ac_platform/media/data/alpha_public_films_12s_v1.json`.
- Both manifests and the helper's compiled pin equal
  `d693acc73dc3f66c1b13ad6e68d5e41cba8478dc719f4b68211ce829442b0222`.
- The manifest enumerates exactly 30 files, totaling 54,274,209 bytes. It remains
  labeled non-course-content and production-disabled, with original registry
  provenance hash `fc61c87d5428d53d35b82061a53fbdbd9967b8bf658c6d0425a78a07bc106290`.
- The thin release archive requires policy, mirror, helper and override files;
  normal exact-commit/archive/RELEASE-FILES verification covers them.
- Host destination is fixed in reviewed source:
  `/srv/authority-closers/application/media-staging/<manifest-sha256>`.
  Neither untrusted file metadata nor CLI/environment input can choose it.

## Safety behavior

`scripts/staging-public-films.py` is a standard-library-only helper available in
the thin archive. Its install command admits staging only and requires the root
operator on the POSIX host. It accepts one exact immutable release directory and
an explicit source directory, not a URL, external manifest, destination, provider
or attestation flag.

It validates complete source inventory, singly-linked regular files, strict
relative paths, per-file byte length/hash, bounded total bytes and file identity
before writes. Symlinks, reparse points, missing/extra files, hardlinks and
non-regular objects are rejected. The explicit destination is protected by a
root-owned exclusive installation lock. A private sibling stage receives only
the approved files; copying rechecks source identity/hash; files become root-owned
0444 and directories root-owned 0555; the complete stage is revalidated before
atomic rename. Partial failure removes only the freshly created stage. An
existing valid pack returns `already_installed` without changing its inodes or
timestamps; any existing drift is refused without replacement or repair.

The fixed Compose override applies only to `api`. It uses a read-only bind at
`/run/ac-staging-public-films` and `create_host_path: false`. Base API/worker/
migrator configuration explicitly disables fixture delivery and general provider
activation. Only API fixture flags become true when the reviewed staging
override is selected. Worker and migrator receive neither a mount nor activation.

The installer evaluates policy for **each target release**, not an ambient
process variable. New-release and existing rollback-release preflight run before
writer shutdown. Enabled policy requires the installed complete root-owned,
non-writable/readable pack; a missing or unsafe pack fails preflight. Old releases
without a policy remain off and do not require a pack. Production ignores staging
policy and never merges its override; the install command refuses production
before artifact I/O. Runtime environment flags are scrubbed from Compose's
ambient environment and do not choose an override.

Operational sequence: release this implementation with policy off; transfer the
reviewed 30-file source and run the bounded install command; explicitly review a
new policy-on source release; then use the canonical catalog/import commands and
prove real authenticated streaming. No live release-file editing is an enable
or recovery path. Root-owned immutable files/read-only container mounts do not
claim to resist an OS administrator who can replace trusted deployment code.

## Local verification

```text
uv run pytest tests/infra/test_staging_public_films.py -q --tb=short
36 passed, 3 skipped in 3.55s

uv run pytest tests/infra/test_application_release.py \
  tests/infra/test_application_release_archive.py -q --tb=short
90 passed in 21.71s
```

The new tests cover byte-identical mirror/pin, off and legacy behavior, production
ignore/refusal, policy path/provider/string-bypass rejection, malformed and
drifted inventories, traversal/link/hardlink rejection, owner/mode rejection,
preflight ordering, per-target rollback selection and ambient flag scrubbing.
The real Docker Compose CLI's read-only `config --format json` output confirms
the API-only mount and inert worker/migrator/general-provider configuration; it
does not start containers or need a Docker daemon.

Three tests for actual atomic installation, read-only POSIX permissions/inode
preservation, drift refusal and partial-copy cleanup are present but explicitly
skip on Windows. Ownership/mode admission logic is separately exercised with
controlled metadata cases. Linux CI must execute the actual filesystem tests.
Local Docker's Linux daemon is absent and existing Ubuntu WSL cannot attach its
missing ext4 disk; neither was started or repaired for this task. Therefore
POSIX installation acceptance is **pending**, not inferred from Windows.

Still required: independent review, Linux CI including all three filesystem
tests, an explicit policy-enable release decision, authorized fixed-pack host
installation, release preflight/mount proof, application import evidence and
signed same-origin learner player QA. No VPS acceptance is claimed here.

Independent review subsequently reported no actionable Critical/Important
findings and reran the three infrastructure files: **126 passed, 3 POSIX-only
skipped** in 20.06s. The reviewer inspected ownership, symlink/reparse/hardlink,
path and byte bounds, atomic publication/idempotency/drift, per-release rollback
selection, production exclusion and pre-writer-stop preflight. The Linux
filesystem proof remains explicitly pending CI. No VPS files were changed by
the reviewer.
