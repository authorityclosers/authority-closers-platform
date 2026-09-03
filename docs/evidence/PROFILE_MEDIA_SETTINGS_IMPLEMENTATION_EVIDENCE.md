# Learner profile media/settings slice — implementation evidence

Status: bounded learner-web slice, provider-neutral and fail-closed. No production object-storage, scanner, or image-processing provider was activated.

## Authority and scope

The exact Drive IDs used for the controlled product and engineering sources are recorded in [`source-manifest.md`](../workflows/v0.1-alpha-experience/01-research-journeys/source-manifest.md). The slice follows the profile/settings boundaries in `JRN-04-profile-settings-appearance.md`, `SF-SET-001-settings.md`, `API-004-session-settings.md`, `API_CONVENTIONS.md`, and `AUTHORIZATION_MATRIX.md`:

- `/v1/me` remains the source for verified identity and membership facts.
- Theme remains device-local (Light/Dark/System); no account-theme, notifications, MFA, SSO, integrations, deletion, or tenant-branding semantics were invented.
- Learner avatar reads and mutations are self-scoped through the authenticated `ActorContext` and active tenant membership.

## Server contract

- `GET /v1/profile/avatar` returns the authenticated learner's current avatar and, when applicable, one pending replacement state.
- `POST /v1/profile/avatar` and `POST /v1/profile/avatar/{upload_id}/complete` reuse the existing media upload-intent lifecycle.
- The service rechecks tenant and owner boundaries, never trusts a browser-supplied tenant/person identity, and returns no provider object key or provider identifier in the profile response.
- Delivery URLs are minted only for a server-confirmed ready private variant, are short-lived, and are rejected if the variant leaves the asset's private namespace.
- Replacements create a new version and preserve the prior ready version until the replacement is processed and confirmed. Failed/uploading/processing history is surfaced as pending state; audit-critical history is not overwritten.

## Browser UX and state handling

- Profile identity and the existing advanced settings ledger remain usable when avatar delivery fails; the avatar read is a secondary read with an explicit retry state.
- The crop dialog validates JPEG/PNG/WebP, non-empty data, readable dimensions, bounded zoom/position, keyboard-operable range controls, focus trapping, Escape/cancel handling, and focus restoration.
- Preview is a local blob URL only. The profile image changes only after the server confirms the new version and delivery URL.
- The API adapter uses the server-issued upload intent, sends the file without ambient credentials, completes the intent with optional SHA-256, then polls the profile contract until the version is ready. Errors are mapped to safe terminal/retryable copy without provider details.
- Desktop and narrow/mobile layouts are covered by the existing responsive crop-dialog/profile styles; controls use at least 44px touch targets.

## Provider gate

The default runtime remains `UnconfiguredPrivateObjectStorage`, `FailClosedScanner`, and `FailClosedProcessor`. The in-memory storage, signature scanner, and copy processor are explicit local/test adapters only. Before any real activation, AC-GOV-AUD-001 and the relevant security/privacy gates still require:

1. an approved private storage adapter and deployment-managed credentials/configuration;
2. approved malware/content scanning and image processing adapters with provenance, retention, and deletion/supersession behavior;
3. staging evidence for upload URL expiry, CORS/origin policy, checksum/size/MIME enforcement, signed delivery TTL/revocation, quota/abuse limits, and lifecycle retries;
4. provider/store/recording/AI data governance and professional review; and
5. an end-to-end tenant-negative authorization test against the selected deployment configuration.

No provider activation, secret, external upload, or production deployment is part of this commit.

## Verification

The focused verification run on the main-relative branch is recorded in the task handoff:

- `pnpm --filter @ac/learner-web typecheck`
- `pnpm --filter @ac/learner-web lint`
- `pnpm --filter @ac/learner-web test` — 302 tests passed
- `uv run pytest -q tests/unit/media/test_media_service.py tests/unit/http/test_app_composition.py` — 25 tests passed
