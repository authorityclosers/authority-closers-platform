# Persistent development organisation logos

AUT-1416 adds one opt-in for the existing `/v1/organisation/logo` API. It uses
the reviewed still-image decoder, 512px WebP sanitization, immutable private
avatar envelopes and bounded ClamAV INSTREAM scanner. Only the organisation
routes receive this runtime. Generic media uploads, profile photo upload
routes, Studio video, playback and external providers remain unconfigured.
Local, staging and production refuse this flag. No environment is aliased.

The API owns `/srv/authority-closers/sales-xray/development/avatar-objects`
(uid/gid 10001, mode 0700). It refuses missing, linked, foreign-owned,
foreign-marked or non-private roots. Its distinct store marker survives API
restarts. The store has the existing 100 MiB bound; existing objects and audit
history survive replacements and failures. Only sanitized pixels are stored;
an inspection failure cannot publish a logo reference.

The dedicated scanner owns `/run/ac-dev-organisation-avatar` (100:10001,
2750); its socket is 100:10001, 0666, behind that private directory. The API
receives a read-only bind of that directory. The container gets only its
dev-only signature directory and socket, with no published port or avatar,
database, provider, staging or production mount. It is capped at 0.5 CPU,
1536 MiB (including swap), 32 PIDs and a 16 MiB temporary filesystem.
The API retains its existing memory and CPU limits. INSTREAM admits at most
2 MiB and the application bounds the whole scan to 30 seconds. Freshclam runs
12 checks/day; the startup proof rejects signatures older than 48 hours.

## Root step 1: install the reviewed scanner

Run only on the dev host as Root Operator, after CTO review, CEO merge approval
and the normal staging release of a core containing this change. Record the
PR, approved head, merge SHA, selected staging core SHA and source hashes on
the implementation child. These commands do not change application data.
Do not run them from a lane checkout or an unmerged source tree.

First verify that `/srv/authority-closers/application/current-staging` points
to the recorded release, and that the files below belong to that release. Do
not follow another release during this operation:

```sh
set -eu
AC_AVATAR_SOURCE=$(readlink -f /srv/authority-closers/application/current-staging)
AC_AVATAR_PROFILE="$AC_AVATAR_SOURCE/development/organisation-avatar"
AC_AVATAR_INSTALL=/etc/authority-closers/development/organisation-avatar
test -f "$AC_AVATAR_PROFILE/prove.py"
AC_AVATAR_TIMER_WAS_ACTIVE=$(systemctl is-active ac-dev-sales-xray-refresh.timer || true)
systemctl stop ac-dev-sales-xray-refresh.timer
! systemctl is-active --quiet ac-dev-sales-xray-refresh.service
```

Before installing: ensure no release is active and no dev refresh is running;
record the active UI branch/head and dirty-file names without reading their
contents. Ensure host available memory is at least 3 GiB and free disk is at
least 2 GiB. Keep the refresh timer paused through both steps and rollback; if
its service is already running, let that invocation finish before any change.
Refuse links in every target path. Verify the existing dev data
parent is 10001:10001, 0700 and the protected configuration parent is root:root,
0700. Refuse any existing avatar directory with different ownership/mode or
an unexpected marker; preserve it rather than adopting it. Refuse a different
installed scanner profile instead of overwriting it. An exact matching install
can be reused. Never print environment files, sessions or credentials.

```sh
install -d -o root -g root -m 0700 "$AC_AVATAR_INSTALL"
install -o root -g root -m 0600 \
  "$AC_AVATAR_PROFILE/compose.yaml" "$AC_AVATAR_PROFILE/clamd.conf" \
  "$AC_AVATAR_PROFILE/freshclam.conf" "$AC_AVATAR_PROFILE/entrypoint.sh" \
  "$AC_AVATAR_PROFILE/prove.py" "$AC_AVATAR_INSTALL/"
install -d -o 100 -g 100 -m 0700 /var/lib/ac-dev-organisation-avatar
install -d -o 100 -g 100 -m 0700 /var/lib/ac-dev-organisation-avatar/signatures
install -d -o 10001 -g 10001 -m 0700 \
  /srv/authority-closers/sales-xray/development/avatar-objects
install -o root -g root -m 0644 "$AC_AVATAR_PROFILE/tmpfiles.conf" \
  /etc/tmpfiles.d/ac-dev-organisation-avatar.conf
systemd-tmpfiles --create /etc/tmpfiles.d/ac-dev-organisation-avatar.conf
install -o root -g root -m 0644 \
  "$AC_AVATAR_PROFILE/ac-dev-organisation-avatar.service" \
  /etc/systemd/system/ac-dev-organisation-avatar.service
systemctl daemon-reload
systemctl enable --now ac-dev-organisation-avatar.service
python3 "$AC_AVATAR_INSTALL/prove.py"
```

Done check: the proof returns `PASS` with the signature version/time. Record
the JSON and source hashes, not raw container logs. If initialization fails,
stop and disable this unit; keep its signature files and the avatar directory.
No API flag is enabled by this step. Investigate an OOM or signature-download
failure inside these limits; do not raise limits or reuse the production scanner.

## Root step 2: compose and prove the API

After step 1, use the reviewed refresh entry point if the dev backend does not
yet contain the merged code. The consumer on AUT-1285 must not refresh it.
Root records this dedicated invocation on its implementation child:

```sh
python3 "$AC_AVATAR_SOURCE/scripts/refresh-dev-sales-xray-backend.py" --preserve-studio
```

This opt-in uses the same staging-selected core, identity/native guards,
migration sandbox, manifest renderer, health check and automatic rollback as
the scheduled refresh. It skips studio sync/merge and the UI smoke that relies
on that merge. The scheduled timer's behavior is unchanged. Record the returned
core and verify it contains the approved merge before proceeding. Record any
completed migration and automatic rollback receipt. Confirm the active UI
branch/head and dirty-file names still match the preflight. No alternate core
pin, raw Git deployment or code rebuild is permitted.

As Root, read `api.env` without printing it. Require `AC_ENVIRONMENT=development`
and refuse any key beginning `AC_MEDIA_DEVELOPMENT_ORGANISATION_AVATAR_` there:
EnvironmentFile overrides unit Environment and must not shadow this profile.
Verify the installed scanner files still match the pinned source and rerun its
proof before enabling the API:

```sh
python3 "$AC_AVATAR_INSTALL/prove.py"
install -d -o root -g root -m 0755 /etc/systemd/system/ac-dev-api.service.d
test ! -e /etc/systemd/system/ac-dev-api.service.d/organisation-avatar.conf
install -o root -g root -m 0644 "$AC_AVATAR_PROFILE/api.conf" \
  /etc/systemd/system/ac-dev-api.service.d/organisation-avatar.conf
systemctl daemon-reload
systemctl restart ac-dev-api.service
```

Done check: read `/health/ready` through the existing dev-only probe transport
and require the recorded core and ready database. Use only the existing
fictional owner/admin/member sessions, injected from the protected fixture
handoff (never print them). On salesxray-dev, select organisation A
`2f3441d2-3426-4bf9-ab54-99658cd49901`; owner and admin PNG PUTs with new UUIDv4
keys must return 200. New requests must return their sanitized WebP and branding;
an API restart must retain the latest reference and bytes. Verify member edit
denial, organisation B `f65dff52-7eb2-4be6-977b-d3062bcec1e4` returning 404 for
the known A logo, and wrong-type rejection without changing canonical details,
the latest logo or the two existing details audit events. Continue the precise
AUT-1285 acceptance and record sanitized results there. No account provisioning,
credential reset, staging fixture or production request is needed.
Restore the timer only if it was active before this operation:

```sh
if [ "$AC_AVATAR_TIMER_WAS_ACTIVE" = active ]; then
  systemctl start ac-dev-sales-xray-refresh.timer
fi
```

## Rollback

If API health or acceptance fails, remove only this opt-in and restore the
default refusing runtime before stopping the scanner:

```sh
rm /etc/systemd/system/ac-dev-api.service.d/organisation-avatar.conf
systemctl daemon-reload
systemctl restart ac-dev-api.service
systemctl disable --now ac-dev-organisation-avatar.service
if [ "$AC_AVATAR_TIMER_WAS_ACTIVE" = active ]; then
  systemctl start ac-dev-sales-xray-refresh.timer
fi
```

Verify dev health is ready and logo PUT now returns `503/media_storage_unavailable`.
Retain all avatar objects, signature files, configuration sources, canonical
references and audit events. This rollback does not revert normally released
code or migrations. Re-enable only from the same reviewed source with a new
recorded installation run. The runtime and installation never touch staging or
production data, credentials, billing, Caddy or the active UI checkout.
