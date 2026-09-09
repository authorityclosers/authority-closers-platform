# Local profile photo: upload, processing and durable private delivery

Date: 2026-09-08. Implementation tree: `C:\Users\Suyash\.codex\worktrees\d2de\authority-closers-platform`.

## Boundary and implementation

This is the explicitly enabled **disposable localhost** runtime, not production
media-provider or antivirus activation. No live account, VPS, deployment, push,
operational SQL recovery, protected progress or scoring changed.

- The managed launcher composes only the exact `ac_local_sandbox` database,
  existing real cookie/session authentication, the explicit local-avatar flag and
  `.tmp/local-platform/avatar-objects`. Defaults and non-local environments remain
  disabled. The separate original `ac_platform` database is preserved.
- Canonical avatar intent, owner/tenant checks, expiration, byte declaration,
  checksum, quota, completion, processing and immutable version history are
  retained. Raw PUT requires a valid signed intent and a currently active session
  for its owner and tenant; it does not claim original-upload-session binding.
- `local_avatar_storage.py` stores immutable, checksum-verified objects in a
  marked, reparse-point-rejecting local directory. Paths are digest-derived, not
  supplied object-key paths. Uploads are bounded at 5 MiB; the store at 100 MiB.
- `local_avatar_processing.py` uses pinned Pillow 12.3.0 to verify and decode
  static JPEG/PNG/WebP, reject mismatched or malformed input, limit decoding to
  12 million pixels/8192-pixel edges with one concurrent processor, apply EXIF
  orientation and the existing normalized crop, and re-encode actual
  128/256/512-pixel WebP variants without original EXIF/ICC/XMP. This bounded local
  image sanitizer is **not an antivirus attestation or production provider review**.
- Normal profile completion publishes the processed current version; replacing
  it preserves history. Private GET/HEAD rechecks active session, person, tenant,
  current avatar version and exact variant. Anonymous, other-person/tenant/session,
  retired and superseded reads are refused.
- The learner Next bridge uses the same real cookie and server-issued token for
  exact-local bounded native PUT/read, never a browser role or bearer claim.
  Projection agent owns this transport and its browser evidence.

Decoder references: [Pillow Image](https://pillow.readthedocs.io/en/stable/reference/Image.html),
[EXIF transpose](https://pillow.readthedocs.io/en/stable/reference/ImageOps.html),
[pinned package](https://pypi.org/project/pillow/).

## Failures caught and fixed

Actual relational/HTTP testing exposed two existing shared-path defects:

1. A newly added `MediaVersion` could be flushed after its referencing upload
   intent, violating the real foreign key. The service now explicitly flushes
   the version before creating the intent.
2. Upload HTTP telemetry sent the canonical `uploading` lifecycle through a
   different bounded telemetry vocabulary, causing a 500 and transaction rollback.
   Upload routes now emit only the valid operation outcome. Canonical lifecycle
   remains in the response and audit; telemetry vocabulary was not widened.

The parent independently reviewed the backend, FK ordering and telemetry fix:
no Critical/Important finding remained in the reviewed scope.

## Validation

- **435 passed**: complete media unit suite, new HTTP telemetry regressions and
  HTTP security-boundary tests, 35.81 seconds. One existing Starlette/httpx
  deprecation warning. Focused avatar/telemetry subset: **49 passed**.
- Scoped Ruff passed; mypy passed all 10 selected production Python modules.
- Actual PostgreSQL + direct API acceptance: **1 passed**. Real normal login,
  >1 MiB synthetic PNG raw PUT, canonical completion, persisted READY avatar,
  actual decoded 512-pixel WebP GET/HEAD, anonymous upload/read denial and logout.
- The same full acceptance through `learner.localhost:3100`: **1 passed**,
  2.69 seconds. A first HEAD attempt during concurrent Next recompilation failed;
  the complete rerun passed. No stale response is counted as success.
- **Actual managed API restart persistence passed**, 1.69 seconds: read existing
  avatar before restart, stop/start only the tracked API, then fresh normal login
  through learner Next. Exact canonical version UUID and delivered WebP SHA-256
  were unchanged, and the existing image decoded at 512×512. No reseed, photo
  replacement, password reset, database restart or UI restart was used.
- After avatar composition/restart, the existing two-film real HTTP acceptance
  through learner Next passed again (**1 passed**, 7.47 seconds): MP4 range/HEAD,
  HLS manifests/segments and anonymous denial. The combined storage adapter did
  not regress the independently authorized video path.
- Reproduction: `tests/e2e/test_local_avatar_runtime.py`; explicitly opted-in
  runtime acceptance uses the local DPAPI credential in process memory, never
  prints credentials, cookies, signed URLs or raw response diagnostics.

Separate browser editor evidence is under
`screenshots/local-avatar-browser-20260908/`. Upload/zoom/save and decoded image
were observed by the projection agent. Its first reload screenshot was caught
as a loading skeleton and is **not retention proof**; corrected new-document and
mobile browser acceptance remains separately owned. The actual API restart proof
above does not depend on that screenshot.

Remaining boundaries: no public-avatar directory, social visibility policy,
external storage/AV provider, production retention activation or public release
is claimed. This local adapter is not a general multi-process object store.

## Editor follow-up — 2026-09-09

The profile editor follow-up keeps this lane in the disposable, synthetic
localhost boundary. The existing sandbox photo was not uploaded or replaced;
there was no backend save, restart, external request, Drive change, deployment,
authentication change or production activation.

- Closing with an unsaved photo now asks for confirmation. Keep preserves the
  same mounted preview/crop; closing while busy warns that a save may already
  reach the server. The parent canonical read reconciles an uncertain close.
- Successful saves abort earlier avatar reads and invalidate generations so stale
  photo reads cannot overwrite a newer selection. The crop square has a
  circular result mask and gesture grid, a fixed footer, body-scroll locking,
  and a reduced-motion busy icon.
- Fifty-two avatar interaction/static, upload-adapter and profile-runtime tests
  passed on Node 24. Full learner TypeScript, scoped ESLint, Prettier and diff
  checks passed; the Important stale-read-overwrites-new-photo review finding
  was resolved and no finding remains in this scope.

Final browser proof is `screenshots/profile-editor-20260909-AbP0BM/proof.json`:
eight light/dark checks at 320, 390, 768 and 1440 widths passed, including the
same mounted image/crop, square stage, body-scroll lock and reduced-motion
state. Native Escape, Tab/focus trap and backdrop focus behavior passed, as did
the short 844×390 confirmation state. The canonical avatar remained version
`056dccb5-7e90-4ece-8911-27a08ee28aea` (number 5, `ready`) before and after;
main-document write attempts and external requests were both zero, and the owned tab closed.
The root review also inspected light 390, dark 1440, portrait and landscape
confirmation views. The earlier `IFYDgS` short-viewport failure is retained as
intermediate evidence, not acceptance. The earlier `rqAUqr` bounds run passed,
but manual review found a decorative thumbnail overlapping the landscape
footer; the final implementation hides that thumbnail at viewport heights ≤460px and
the final assertion checks the overlap.

The final browser matrix preceded only the saved reduced-motion selector
addition. Its CSS contract test covers both existing saved preference attributes;
the browser captures use OS reduced-motion emulation, not persisted preferences.

Release access remains blocked: PR43 is still an open draft at SHA
`2c56de938753a669265c4dda0d08ad9f3cb2ed0b`, its image-packaging check is
skipped, and the sole bounded `ssh ac` probe timed out during the Access banner
exchange. This evidence does not close staging or production gates and does
not claim release readiness.
