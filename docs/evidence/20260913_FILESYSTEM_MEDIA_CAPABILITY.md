# Source owned Studio video filesystem capability

This slice composes the existing authenticated Coach upload and learner
delivery lifecycle in staging or production when the explicit filesystem
profile is enabled. The profile keeps the canonical flow intact:

1. Coach authorization creates a course scoped upload intent.
2. `StudioVideoByteTransport` streams request chunks directly into the private
   `VideoFileStorage` root. It never calls `request.body()` and never builds a
   browser-sized `ArrayBuffer` for the film.
3. Completion rechecks the upload lease, scans the stored object through the
   mounted ClamAV Unix socket with bounded INSTREAM chunks, and enqueues the
   existing `media.process_version.v1` job.
4. The shared application worker runs the existing lease and recovery gated
   `StudioVideoJobWorker` beside the durable email loop. FFmpeg writes only to
   the same private store.
5. Ready playback still requires the existing tenant, enrollment, catalog
   binding, grant, cookie session, and signed range delivery checks.

The source limits are exact and intentionally expressed in their native units:

| Bound | Value |
| --- | ---: |
| Uploaded source | 2,000,000,000 bytes |
| ClamAV stream/file limit | 2,000,000,000 bytes |
| ClamAV scan limit | 4,000,000,000 bytes |
| Scanner total deadline | 1,800 seconds |
| Scanner disk temp capacity | 8,000,000,000 bytes free before start |
| Scanner active scans / queue | 2 / 2 |
| Private store aggregate envelope | 8 GiB |
| FFmpeg temporary workspace quota | 8 GiB |
| Video processing concurrency | 2 active completions |
| API memory limit | 768 MiB |
| Worker memory limit | 512 MiB |

The reviewed Python runtime image installs the Debian `ffmpeg` package, which
provides both `ffmpeg` and `ffprobe` for the processing worker. The worker
therefore does not depend on a host binary or an unreviewed sidecar image.

The dedicated Compose companion profile mounts the target environment's private
host root into API and worker:

- staging: `/srv/authority-closers/volumes/media-video/staging`;
- production: `/srv/authority-closers/volumes/media-video/production`.

Both mount at `/var/lib/ac-media`, with the application root at
`/var/lib/ac-media/video-objects`. The scanner socket is a separate private,
read-only safety endpoint at `/run/ac-media-safety/clamd.sock`; it contains no
application media objects.
- The worker's `TMPDIR` is `/var/lib/ac-media/tmp`, a precreated private
  directory on the media volume. This avoids the foundation `/tmp` tmpfs
  limit while retaining the processor's bounded source/output reservation.

ClamAV uses the dedicated disk-backed
`/srv/authority-closers/volumes/media-safety-tmp` workspace rather than its
256 MiB process tmpfs. The controller requires at least 8,000,000,000 free
bytes before start, and the reviewed scanner policy bounds active scans to two
4,000,000,000-byte scan envelopes with a two-item queue.

The default application profiles remain disabled. Activation is a source-owned
release change: the checked-in target profile sets
`AC_MEDIA_FILESYSTEM_ENABLED=true` together with its exact environment root.
The canonical application installer consumes that selector for install,
service composition, and rollback. Do not add a manual Compose overlay; it
would bypass target-release rollback policy. Before running that installer,
prepare the reviewed private roots and prove ClamAV:

```sh
sudo install -d -o 10001 -g 10001 -m 0700 \
  /srv/authority-closers/volumes/media-video/<environment>
sudo install -d -o 10001 -g 10001 -m 0700 \
  /srv/authority-closers/volumes/media-video/<environment>/tmp
sudo install -d -o 100 -g 100 -m 0755 \
  /srv/authority-closers/volumes/media-safety-socket
sudo install -d -o 100 -g 100 -m 0750 \
  /srv/authority-closers/volumes/media-safety-tmp

sudo python3 /srv/authority-closers/media-safety/releases/<scanner-release>/manage.py \
  prove /srv/authority-closers/media-safety/archives/<scanner-release>.tar \
  <scanner-release> <scanner-archive-sha256>

sudo env \
  AC_TARGET_ENVIRONMENT=<environment> \
  AC_RELEASE_ID=<application-release> \
  AC_RELEASE_ARCHIVE=/srv/authority-closers/application/archives/<application-release>.tar \
  AC_RELEASE_ARCHIVE_SHA256=<application-archive-sha256> \
  AC_IMAGE_BUNDLE_DIR=/srv/authority-closers/application/artifacts/<application-release> \
  AC_INFISICAL_PATH=/application \
  /srv/authority-closers/application/releases/<application-release>/scripts/install-application-release.sh
```

The installer validates the profile and prepared roots before service mutation,
and every `compose_for` call reads the target release's own profile. The
placeholders are release identities; Infisical supplies secrets through the
existing installer boundary. The first real upload, scan, processing
completion, catalog selection, and mobile playback remain deployment receipts
owned by the root operator.

## Evidence

Focused composition and scanner-controller tests passed after this wiring:

```text
99 passed - Studio runtime, delivery and media-safety controller tests
194 passed - settings and durable worker tests
39 passed - application/studio HTTP composition tests
```

The previously verified public Big Buck Bunny 4K source remains outside Git and
is not copied or downloaded by this change. Its release-pack manifest and
SHA-256 receipts are retained in the AC owned transfer worktrees.
