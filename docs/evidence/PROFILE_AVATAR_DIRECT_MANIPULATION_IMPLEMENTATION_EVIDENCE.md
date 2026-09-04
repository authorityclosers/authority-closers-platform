# Profile avatar direct-manipulation implementation evidence

Status: implementation evidence for the bounded UX slice on `codex/profile-avatar-direct-ui`.
This is not a production, staging, provider-activation, or device-visual sign-off.

## Scope and controlled source alignment

This slice was implemented from the current `origin/main` worktree after reading the
source manifest and the controlled profile/onboarding/media/UI/security/accessibility
documents listed there. The relevant design decisions are:

- learner-facing surfaces keep the existing Closers Academy calm, directional visual
  language and tokenized surfaces; no new visual system or asset provider was added;
- avatar changes remain self-scoped behind the existing authenticated profile API and
  tenant boundaries;
- the browser owns only a temporary preview and crop interaction; the profile service
  remains authoritative for MIME, byte-size, content/security scanning, processing,
  revision, and delivery URL acceptance;
- provider/storage/CDN activation remains outside this slice.

## Direct manipulation behavior

`apps/learner-web/app/components/avatar-crop-dialog.tsx` now exposes one direct crop
stage rather than the former slider group:

- selecting a file, dropping a file, or pressing Enter/Space on the empty stage opens
  the existing picker path;
- pointer capture supports mouse, touch, and pen dragging to reposition the local
  preview; a two-pointer gesture combines centroid movement with bounded pinch zoom;
- wheel input over the crop stage zooms in or out, with the interaction isolated by
  `touch-action: none` and `preventDefault()` so page scrolling is not hijacked outside
  the stage;
- the focused stage supports Arrow keys for movement, Shift-modified larger movement,
  `+`/`=` and `-`/`_` for zoom, and Home/`0` for neutral framing; all values pass through
  the existing bounded crop contract;
- Reset framing returns the crop to its neutral state without replacing the selected
  file; Cancel closes the editor without uploading;
- `cropShape` is a controlled `circle | square` seam. The default presentation remains
  circular and the square variant changes the frame and guide shape using existing CSS
  tokens.

`apps/learner-web/app/components/avatar-crop-dialog.module.css` keeps the existing
desktop modal/mobile bottom-sheet behavior, 44px interactive controls, tokenized focus
state, and reduced-motion behavior. The local preview is explicitly labeled and the
keyboard instructions are exposed through `aria-describedby`.

## Identity and upload safety

`apps/learner-web/app/lib/profile-identity.ts` is the single presentation-only fallback
for initials. It uses the first initial plus surname initial for multi-word names (for
example, `Dipak Vishwakarma Sharma` → `DS`) and does not participate in identity,
authorization, or tenant decisions. The shell, profile runtime, upload response adapter,
and crop dialog share it.

The selected image is represented by a revocable local object URL until the existing
upload adapter reports a server-confirmed ready revision. Success callbacks only run on
that confirmed result; terminal/retryable/unavailable outcomes keep the current server
avatar and show a recovery message. Processing without an adapter status path also
fails closed. The client computes a SHA-256 digest in bounded 1 MiB slices, binds the
lowercase digest into the profile-avatar upload-intent request and completion request,
and passes the server-issued checksum header unchanged to the private PUT. The existing
server adapter therefore remains responsible for signing and verifying the object; no
client policy silently replaces the server's MIME, size, dimension, scan, or revision
authority. Existing auth/tenant boundaries, completion flow, and revision/supersession
semantics remain intact. No URL is invented and no S3/CDN/provider credentials are
introduced.

The direct crop state retains the validated natural image dimensions from the browser
decode. `toAvatarCropMetadata` derives the neutral `object-fit: cover` source extent,
then applies bounded scale and translation to the normalized source rectangle expected
by the server processor contract. Landscape, portrait, multi-scale, and edge cases are
covered so server crop metadata reproduces the visible preview rather than serializing
CSS transforms.

Upload and processing requests use caller-owned `AbortController` signals plus bounded
request/deadline timers. Escape, Cancel, unmount, and offline transitions abort active
work without mutating the current server avatar or reporting fake success. Async status
reads retry transient failures with capped exponential backoff, while terminal API
responses and terminal media states stop immediately. A controlled online/offline notice
retains the local preview and disables submission until reconnect.

Profile view colors now bridge the existing profile aliases to `--theme-*` tokens,
including scoped badge/button states and the existing light/dark surface, text, border,
action, warning, and shadow tokens. Static assertions cover the profile block's absence
of the previous light-only literals and the dark token contract.

The profile host keeps a persistent success status outside the crop dialog, so the
server-confirmed success announcement survives dialog unmount. It also refreshes the
server-owned signed delivery URL on a bounded interval and after image error; while a
failed URL is being replaced, the profile safely falls back to the presentation initials.

## Activation gate

P1 release gate: no controlled avatar-specific maximum byte or pixel dimensions are
authorized in this slice. The client therefore does not invent numeric limits; it only
rejects unreadable/non-positive values and leaves MIME, size, dimensions, scanning,
orientation, and processing authority with the approved profile service. Provider,
storage, scanner, device, and staging evidence must record the approved policy and
server-side enforcement before avatar upload is activated.

## Focused evidence

Focused tests cover:

- accessible dialog/picker copy, direct-manipulation guidance, no `input[type=range]`,
  square/circular seam, bounded crop/keyboard math, adapter-result abort guard, and
  static cancellation/offline/pointer wiring checks in
  `app/components/avatar-crop-dialog.test.tsx`;
- checksum hashing, upload-intent/completion binding, private PUT cancellation, bounded
  file slices, object-fit cover parity, async display-name alt text, transient retry/
  backoff, and terminal status behavior in `app/lib/avatar-upload.test.ts`;
- static host-level success-status, signed-URL refresh, and expired-image fallback
  wiring checks in `app/components/profile-runtime.test.tsx`;
- exact client wire shape and abort-signal propagation for the existing `/v1/profile/avatar`
  schema in `app/lib/learner-api.test.ts`;
- Pydantic strict-schema compatibility for checksum intent/completion payloads in
  `tests/unit/media/test_avatar_upload_contract.py`;
- first/surname, single-name, whitespace, and empty-name fallbacks in
  `app/lib/profile-identity.test.ts`.

Validation run in this worktree:

- `pnpm --filter @ac/learner-web typecheck` — passed;
- `pnpm --filter @ac/learner-web lint` — passed;
- focused avatar/API/profile/theme tests — passed (6 files / 65 tests);
- full learner suite — passed, 28 files / 377 tests;
- `uv run pytest tests/unit/media -q` — passed, 108 tests;
- `uv run pytest tests/unit/http -q` — passed, 193 tests;
- `.venv\Scripts\python.exe -m pytest tests/unit/media/test_avatar_upload_contract.py -q` — passed;
- `pnpm format:check` — passed;
- `git diff --check` — passed.

The commands emitted the repository engine warning because this host currently has
Node `v22.17.0` while the repository declares Node `>=24 <25`; CI/runtime validation
under the declared version remains required.

## Deliberate limitations

No browser, Playwright, real mobile device, image scanner, storage provider, S3/CDN,
deployment, or production/staging endpoint was used. Device-specific gesture fidelity,
screen-reader announcement quality, server-side MIME/size/content enforcement, and
actual processing latency still require the existing QA/security/controlled-service
gates. This worktree has not been committed or pushed.
