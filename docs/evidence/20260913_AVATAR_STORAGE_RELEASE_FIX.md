# Profile avatar storage recovery

The actual production learner flow accepted and previewed a valid PNG, then
`POST /v1/profile/avatar` returned HTTP 503 `media_storage_unavailable` before
upload intent issuance. Filesystem deployment composed Studio video storage but
left the avatar operation using unconfigured private object storage.

The correction supplies a separate bounded filesystem avatar store, a tokenized
same-origin authenticated PUT, ClamAV scanning and bounded image processing. The
canonical installer provisions the new avatar directory beneath the validated
media parent and rejects invalid existing paths. The upload route retains a 5 MiB
limit, JPEG/PNG/WebP contract and private storage quota.

Independent review caught two intermediate dispatch defects. The accepted chain
preserves the base media service and explicitly routes generic media intent and
completion through it. Avatar intent, read and completion use the separate avatar
service; delivery delegates non-avatar keys to the existing video handler. The
HTTP regression exercises VIDEO and AVATAR intent/completion and verifies the
separate service calls and filesystem avatar finalization.

Integrated commits: `390dbbb`, `6e1aee4`, `0135f3b`, `4a1636e`. Original reviewed
chain: `b09696c`, `ccac8b5`, `92fd46a`, `87689b4`. Only the complete chain is eligible
for release; earlier intermediate commits are not independently accepted fixes.

Validation on the integrated source:

- 83 HTTP/media/app-composition tests passed in 20.23s, no skips.
- Independent review: no remaining P1 in the reviewed dispatch/delivery path;
  9 route tests plus 74 composition/runtime tests passed with explicit package path.
- Actual production browser reproduction used a neutral generated test image;
  the failed request left the original profile unchanged.

Receipt: `D:/AC-authority-closers-release-audit/v02-avatar-routes-02.xml`.
Staging/production upload, reload and displayed-photo acceptance must still be
performed after the immutable corrected release is deployed. No live fix is
claimed by this source evidence.
