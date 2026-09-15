# Private upload to Dipak overview

The actual standalone `/` route mounts `AcquisitionStudio`. It discovers the
release-owned `/v1/conversation/acquisition/entry` capability. When explicitly
disabled, the existing signed-in studio remains available. A failed request
shows recovery; it never substitutes a synthetic example.

## User journey

1. Choose a supported original audio file. Selection and local playback do not
   upload it. File limits and free allowance come from the API.
2. Accept the displayed private-upload terms. A new guest also completes the
   managed Turnstile check. The browser receives only the public site key and
   holds the short-lived challenge response in memory; the server verifies it
   and issues an HttpOnly guest cookie.
3. Upload the original with its SHA-256 and exact policy fingerprint. Duration
   and minute reservations come from the server's full native inspection.
   Retrying preserves the submission UUID and bytes. An already-owned exact
   retry is still permitted after its reservation exhausts the allowance.
4. Poll the scoped local run. After it finishes, display the exact approved
   providers, models, privacy notices, maximum cost and expiry. Only the user's
   separate acceptance starts that plan. Internal checkpoint codes are not the
   user's navigation.
5. Receive the v2 report projection and matching literal transcript. The same
   evidence validators reject mismatched source, recording, transcript revision
   or quotation. The existing fourteen-point overview, factor cards, transcript
   search and timestamp playback present the verified draft. The app shell is
   English; the supplied transcript script remains intact.
6. Print/save PDF, return in the same browser, explicitly save to an AC account
   after sign-in, or request permanent deletion. Account discovery and claim
   use the root-owned optional-account session contract. No implicit claim is
   performed. The overview remains a draft; numeric publication stays withheld.

## Recovery and storage

Only the current opaque submission UUID is kept in local browser storage. No
recording, filename, transcript, report or credential is stored there. A blocked
local store does not prevent upload. Server authorization is always required to
resolve the UUID; it is never a bearer credential. This selector remembers the
current call, not a new account-wide history service.

Incomplete uploads keep the selected file for an idempotent retry. Processing
continues in durable workers after the browser closes. Polling is bounded after
repeated errors and offers recovery. Expired plans require a fresh visible plan;
acceptance never follows automatically. Deletion is reported as requested only
after the canonical server acceptance and removes the local selector.

The main audio element remains mounted while report sections change. Timestamp
selection seeks and plays that source span; browser autoplay failures leave a
plain instruction to press play. PDF and narrow-screen presentation reuse the
reviewed report components. These are interaction capabilities, not proof of
model accuracy or hosted capacity.

## External widget

Turnstile loads directly from Cloudflare's documented explicit-rendering URL.
Release CSP must allow the required challenge script/frame origin; the secret
stays in the narrow backend file. See
[Cloudflare's rendering documentation](https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/).
Local browser tests replace the widget and its verification with a declared
synthetic adapter; staging must exercise the real managed widget separately.
