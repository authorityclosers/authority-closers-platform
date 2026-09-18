# Studio video upload through the canonical API

Use this runbook for the authorized full-size public test film after the
filesystem media profile is active on the intended environment. It sends the
file through the existing Coach upload lifecycle and does not copy an asset to
the VPS by hand.

## Preconditions

- The target release has the reviewed filesystem profile enabled and its
  scanner/worker readiness evidence is current.
- The operator is the verified Coach owner with `catalog_read` and
  `catalog_write` for the exact course. The course and activity UUIDs come
  from the Coach workspace; do not infer them from a filename or database.
- The source is a local regular `.mp4` or `.webm` file. The operator tool
  computes its byte length and SHA-256 before creating an upload intent.
- The workstation has Python 3.12+ and the reviewed `ssh ac` alias. The tool
  uses the VPS loopback Caddy listener at `127.0.0.1:8080` with a canonical
  `Host` header, so the upload remains authenticated and audited while avoiding
  the public Cloudflare request-body limit.

## Upload

Run with shell tracing disabled. The tool prompts for the Coach session cookie
with hidden input. A private ephemeral `AC_STUDIO_SESSION_COOKIE` environment
variable may be used instead; it is never written to a file or included in an
SSH argument. Do not paste a cookie into the command line.

```sh
python3 infra/application/scripts/studio-video-upload.py \
  --video /private/path/Big.Buck.Bunny.4K.mp4 \
  --program-id <verified-course-uuid> \
  --origin https://coach.authorityclosers.com
```

For staging, use the reviewed staging course and
`--origin https://coach-staging.authorityclosers.com`. The script refuses
arbitrary origins, public API URLs, SSH targets other than `ac`, files above
the exact `2,000,000,000`-byte source cap, malformed checksums, or any upload
intent whose returned URL and headers do not exactly match the local file and
course.

The tool performs these canonical operations:

1. `POST /v1/admin/studio/programs/{program_id}/video-uploads` with the
   filename, `video/mp4` or `video/webm`, exact byte length, and SHA-256.
2. `PUT /v1/admin/studio/programs/{program_id}/video-uploads/{upload_id}/bytes`
   through `ssh -T ac` into loopback Caddy. The stream carries the exact
   `Content-Length`, `X-Content-SHA256`, Coach `Origin`, and host-only session
   cookie. No whole-file buffer or VPS asset copy is created.
3. Bodyless `POST .../{upload_id}/complete` with a fresh idempotency key.
4. Authenticated status polling until `ready` or a terminal failure.

The API's upload intent expires after 900 seconds. The transport has bounded
30-second idle and 1,800-second transfer deadlines; the shorter intent expiry
is the effective end-to-end deadline. If the PUT is interrupted, the API has no
resume or `Content-Range` operation. Start again from byte zero with a new
intent.

After the tool reports `ready`, bind the returned media version to the intended
activity through the normal Coach catalog selection flow. That separate
selection is what makes the private, granted media playable in the course.

## Cloudflare boundary

The source Caddy routes allow exactly 2,000,000,000 bytes for Coach and Admin
API paths. A public browser request still traverses Cloudflare. Cloudflare's
current documented maximum request-body sizes are 100 MB for Free/Pro, 200 MB
for Business, and 500 MB by default for Enterprise; Enterprise can configure
up to 5 GB. A 633 MB film must therefore use the reviewed SSH loopback path
unless the zone's configured maximum has been independently verified above the
file size. Do not claim a public browser upload proves the 2 GB capability.

Official reference: <https://developers.cloudflare.com/support/troubleshooting/http-status-codes/4xx-client-error/error-413/>.
