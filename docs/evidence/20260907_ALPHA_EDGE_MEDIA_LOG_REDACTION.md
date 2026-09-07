# Alpha edge credential-log redaction — 2026-09-07

Status: implemented, independently reviewed and parsed with the deployed Caddy
binary; exact-commit CI and release acceptance pending. **No VPS files, services, listeners,
containers or configuration were changed. No real signed URL was requested.**

## Scope and reason

The previous site access-log filter covered OAuth query credentials but not
the media `token` query value. Adding that value only to the site filter was
insufficient: Caddy's separate runtime HTTP error logger also carries the
original request object on upstream errors. The unconfigured default sink
would therefore retain a signed URI on, for example, a proxy failure.

Primary references, checked against the actual installed version:

- [Caddy access log documentation](https://caddyserver.com/docs/caddyfile/directives/log)
  distinguishes access logs from runtime logs and defines query replacement.
- [Global log configuration](https://caddyserver.com/docs/caddyfile/options#log)
  controls the default/runtime destination.
- [Caddy v2.11.4 server.go](https://github.com/caddyserver/caddy/blob/v2.11.4/modules/caddyhttp/server.go#L322)
  attaches the original request to the error logger;
  [app.go](https://github.com/caddyserver/caddy/blob/v2.11.4/modules/caddyhttp/app.go#L212)
  names that logger `http.log.error`. It is distinct from `http.log.access`.

The Caddyfile now declares one `credential_query_redaction` snippet and imports
it into both the global/default runtime encoder and the existing site access
encoder. It replaces `code`, `state`, `access_token`, `refresh_token`, `id_token`,
`client_secret` and `token` with `REDACTED` in `request>uri`. Both remain JSON;
runtime keeps its default stderr destination and access keeps stdout. The
default excludes only the separately routed access stream, not error logs.
Routes, headers, host matching, proxy targets, TLS/admin settings and log levels
are unchanged. The API image still starts with `--no-access-log`.

Only these source/evidence files are owned by this change:

- `infra/vps-foundation/compose/foundation/Caddyfile`
- Log-focused coverage in `tests/infra/test_application_release.py`
- This evidence note

## Verification

`uv run --python 3.12 pytest -q tests/infra/test_application_release.py`:
**46 passed, 4 skipped in 5.92 seconds**. The four actual-parser cases skip on
this Windows host because neither a local Caddy binary nor a usable Docker
daemon exists. CI fails, rather than skips, if neither parser path is available.
Ruff lint/format and scoped `git diff --check` passed.

The new parser fixture uses local Caddy when available, otherwise only the
source-pinned foundation Caddy image in a disposable local/CI container. The
parser has no network, host mounts, published ports, capabilities or writable root;
it has memory/CPU/PID/time bounds and only executes `caddy adapt` on stdin.
It never contacts the deployed VPS, starts an HTTP server or receives secrets.

Parsed JSON assertions require both redacting encoders, all seven exact
replacement actions, the stderr/stdout destination split, the access logger's
actual server binding, and inclusion of runtime errors. Negative controls
remove the runtime encoder, remove access-token redaction, or exclude runtime
errors; all must be rejected. These are assertions on real parser output, not
only matches against Caddyfile text.

Separately, through the already configured `ssh ac` access path:

```text
sudo -n docker exec ac-edge-router caddy version
sudo -n docker exec -i ac-edge-router caddy adapt --config - --adapter caddyfile
```

The second command received only the checked-in candidate Caddyfile via stdin;
its JSON was kept in workstation memory and passed to the same repository
assertion functions. **Caddy v2.11.4 accepted both destinations, and all three
incomplete-redaction controls were rejected.** No reload/run/validate command
was used. The stdin transport produced only a formatting warning, not a parse
error. An initial import-order probe failed safely; declaring the shared
snippet before its first import resolves it.

This proves configuration interpretation, not a deployed log-event test.

Independent review repeated the 46 passing checks and four local parser skips,
adapted the candidate and baseline with VPS Caddy 2.11.4 through stdin only,
and verified that every non-logging adapted setting remained identical. All
three negative controls were rejected. No Critical or Important findings remain
in this scoped change. Reviewed Caddyfile SHA-256:
`f4d41bc1d54e932f27a99459314d446c76d576e38217ef6ad428e105b0a07617`.

### Linux CI parser execution correction

The first PR41 Linux run reported 1,593 passing tests, 28 skips and four
parser-fixture errors: the pinned image's `/usr/bin/caddy` could not execute
with `operation not permitted`. This was not a Caddyfile parsing failure.
Independent disposable-container reproduction confirmed the binary carries
`cap_net_bind_service=ep`; both direct execution and execution from a shell
failed with empty effective/bounding capability sets and `NoNewPrivs=1`.
The fixture already supplied `no-new-privileges:true`, so repeating that option
would not repair the failure. See the Linux documentation on
[file-capability safety checks](https://man7.org/linux/man-pages/man7/capabilities.7.html)
and [no-new-privileges](https://docs.kernel.org/userspace-api/no_new_privs.html).

The test harness now copies only that exact pinned binary, as UID/GID 65534,
into a private 64 MiB tmpfs at `/run/ac-caddy-parser`. It asserts directory
ownership/mode `65534:65534:700`, makes the copy `0500`, verifies its SHA-256
equals the image binary and verifies `getcap` returns no file capabilities,
then execs only `adapt` on stdin. The copy has unchanged executable bytes;
only the privilege-bearing xattr is absent. The image and host are untouched.
Network `none`, read-only root, all capabilities dropped, no-new-privileges,
128 MiB memory, half CPU, 64 PIDs, no container log driver and the existing
timeout all remain enforced. No host bind or image-declared volume exists.

Verification after this correction:

- Windows focused suite: **46 passed, 4 local parser skips** (5.65 seconds).
  Ruff lint/format passed. The CI missing-parser path still fails, not skips.
- The **exact updated fixture** was independently executed through SSH on
  Linux, substituting only its Docker CLI transport. The actual candidate
  Caddyfile parsed, both logging destinations passed and all three negative
  controls were rejected. No server/listener or deployed configuration was
  started, loaded or changed.
- All four owned disposable reproduction/proof containers were automatically
  removed; exact-name readback confirmed none remained. No capability was
  added and no file was extracted onto the host.

This closes the reproduced harness defect; a subsequent complete Linux CI run
is still required and is not claimed by the isolated proof.

After a controlled release, a clearly synthetic noncredential marker must be
checked in both normal-access and controlled error-path output without using
an actual signed URL. Do not inspect or print existing raw credential logs.

## Read-only live identity and gates

The current foundation symlink and the edge container's read-only Caddyfile
mount both resolve to:

```text
/srv/authority-closers/releases/foundation-62538c11e679d757648ca691cc26ece5ba64cb39
```

The mounted file currently has **zero** `replace token REDACTED` lines.
The new redaction is therefore not live, and film capability must remain off
until the edge release and its post-deployment proof pass. Application-only
`scripts/Deploy-Staging.ps1` cannot update this foundation-owned mount.

Read-only directory metadata checks found `/`, `/var`, `/var/lib` and
`/var/lib/authority-closers` as root:root `0755` directories, and the exact
`/var/lib/authority-closers/restore-drill-inputs` leaf as root:root `0700`.
No preparation or repair was performed. These checks must be repeated at the
actual release boundary rather than treated as a permanent attestation.

Service-state sampling found `ac-postgres-backup.service` activating,
`ac-restic-backup.service` failed and the staging restore-proof service failed.
No fresh successful backup, off-host RPO, or restore acceptance is claimed.
Backup repair remains separately owned; these samples do not diagnose its cause.

## Exact foundation delta and narrow installer proposal

The complete 518-line `install-foundation-release.sh` was read, including its
archive gates, host-manifest transaction, Compose reconciliation and rollback.
At the review checkpoint, HEAD was
`c938e336645882374e1b27202bccf598993d6dcb`. The committed foundation delta from
the live `62538c11e679d757648ca691cc26ece5ba64cb39` was exactly:

| Path under `infra/vps-foundation` | Change |
| --- | --- |
| `config/systemd/ac-restic-postgres-restore-proof@.service` | One new writable exception for the private drill-input leaf |
| `scripts/bootstrap-host.sh` | One call to the reviewed leaf-preparation helper |
| `scripts/prepare-restore-drill-input-root.py` | New 97-line no-follow, exact-owner/mode helper |
| `runbooks/POSTGRES_OFFSITE_RESTORE_PROOF.md` | Six explanatory lines |

This list does **not** include concurrently uncommitted backup repairs or this
redaction. The final full foundation delta must be regenerated against the
actual reviewed release SHA. A Git archive includes committed bytes only;
never package the dirty working directory or substitute hand-edited live files.

The existing immutable installer supports a checksum-verified archive directly.
That path avoids `bootstrap-host.sh runtime`, which unconditionally rewrites
Docker daemon configuration and restarts Docker. The direct path is supported
by the installer's archive branch; it is not an ad hoc Caddy reload.

Proposed, **not executed and not approved by this evidence**:

1. Obtain review/CI for the exact full release SHA and all included foundation
   changes. Require acceptable fresh backup/recovery evidence and a maintenance
   window for edge/telemetry replacement; keep film policy off.
2. On the trusted controller, produce `git archive --format=tar <SHA> --
   infra/vps-foundation`, record SHA-256, and validate it with the matching
   `verify-git-release-archive.py`. Transfer/verify the exact archive through the
   controlled SSH boundary and extract only into an isolated root-owned staging
   directory. Do not use `git pull`, an unreviewed tarball or a new provider flag.
3. Recheck baseline, current immutable release checksum manifest, mount identity,
   relevant job states and the drill-input leaf contract. The direct installer
   does not call the new helper: if the leaf is missing/unsafe, stop and obtain
   an explicit scoped action using the reviewed helper from that same archive.
4. Invoke the matching archive-extracted `scripts/install-foundation-release.sh`
   with `AC_RELEASE_ID=foundation-<SHA>`, `AC_RELEASE_ARCHIVE=<absolute verified
   tar path>` and `AC_RELEASE_ARCHIVE_SHA256=<recorded digest>`. No bootstrap
   runtime, Docker-daemon restart, manual Caddyfile overwrite or manual reload.
5. Verify the new `current` link and content manifest, exact read-only Caddyfile
   mount, adapted runtime/access filters, local/public health and synthetic
   log-redaction proof before allowing the later film application release.

The direct installer still has material effects: it installs **55** declared
host scripts/units, always downloads/checks/replaces the pinned Infisical and
rclone binaries, writes the release toolchain marker, reloads systemd units,
reconciles both foundation containers with the new release's bind paths,
refreshes the firewall and enables firewall/health timers. It verifies OS pins
but does not install OS packages or restart the Docker daemon. Edge and telemetry
can be recreated even if their image digests are unchanged. It does not perform
application migrations or directly edit database state.

## Backup and rollback boundary

Durable bootstrap archives normally live under `/root/ac-bootstrap-backups/`;
their freshness was not established here. The direct installer's transaction
captures its managed files in `/tmp/ac-release-rollback.*/host-files.tar` and
verifies the previous immutable release before mutation. That snapshot is
temporary: cleanup removes it on exit, **including after an unsuccessful
automatic rollback**. It is not an adequate durable recovery artifact by itself.
Require independently verified, retained pre-change recovery evidence before
the proposed rollout; do not expand this task into manual backup/recovery edits.

Normal rollback uses the previous verified immutable installer's own release ID:

```text
sudo AC_RELEASE_ID=foundation-62538c11e679d757648ca691cc26ece5ba64cb39 \
  /srv/authority-closers/releases/foundation-62538c11e679d757648ca691cc26ece5ba64cb39/scripts/install-foundation-release.sh
```

That reconciles old files/toolchain/Compose, checks health and changes `current`;
it is not a mere symlink swap. The old release lacks token redaction. If films
were subsequently enabled, disable signed-film delivery through the controlled
application release policy **before** intentionally returning to the old edge
configuration. No rollback command was run in this task.
