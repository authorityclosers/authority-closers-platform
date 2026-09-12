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
| Private store aggregate envelope | 8 GiB |
| Video processing concurrency | 2 active completions |
| API memory limit | 768 MiB |
| Worker memory limit | 512 MiB |

The dedicated Compose companion profile mounts the same host paths into API and
worker:

- `/srv/authority-closers/volumes/media-video` to
  `/var/lib/ac-media`, with the application root at
  `/var/lib/ac-media/video-objects`;
- `/srv/authority-closers/volumes/media-safety-socket` to
  `/run/ac-media-safety`, read-only for API and worker, with ClamAV at
  `/run/ac-media-safety/clamd.sock`.

The default application profile remains disabled. An operator activates this
capability only after the exact reviewed application and scanner archives have
been installed and proved:

```sh
sudo install -d -o 10001 -g 10001 -m 0700 \
  /srv/authority-closers/volumes/media-video
sudo install -d -o 100 -g 100 -m 0755 \
  /srv/authority-closers/volumes/media-safety-socket

sudo python3 /srv/authority-closers/media-safety/releases/<scanner-release>/manage.py \
  prove /srv/authority-closers/media-safety/archives/<scanner-release>.tar \
  <scanner-release> <scanner-archive-sha256>

sudo docker compose --project-name ac-application-<environment> \
  --env-file <exact-reviewed-application-env> \
  -f /srv/authority-closers/application/releases/<application-release>/compose.yaml \
  -f /srv/authority-closers/application/releases/<application-release>/compose.filesystem-media.yaml \
  config --quiet

sudo docker compose --project-name ac-application-<environment> \
  --env-file <exact-reviewed-application-env> \
  -f /srv/authority-closers/application/releases/<application-release>/compose.yaml \
  -f /srv/authority-closers/application/releases/<application-release>/compose.filesystem-media.yaml \
  up --detach api worker
```

The placeholders are release identities and the already reviewed environment
file selected by the application installer; this source change does not read
or write secrets. The first real upload, scan, processing completion, catalog
selection, and mobile playback remain deployment receipts owned by the root
operator.

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
