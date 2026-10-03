# AUT-880 billing wiring checkpoint — 3 October 2026

Source pin: `b5541b3012fbc3f40a404845017f9e3285f17de6`.
Branch: `task/sales-xray/880-plan-billing-wiring`.

This is an incomplete integration checkpoint. AUT-878 must deliver the buyer
request schema before organisation name and optional GSTIN can be submitted.
Its invoice list/download contract is also pending. The current C1 checkout
request forbids extra fields; this change does not invent those fields.

Implementation choice: keep the requested integration in one slice, including
the explicitly required deletion of the obsolete `PlansView` and its tests.
The existing Plans and Settings layouts remain the presentation surfaces.

## Implemented

- `/plans` reads the strictly parsed public catalogue, retaining the approved
  display catalogue until an on-sale catalogue is returned. Live top-up prices
  come from that catalogue.
- Checkout prepares an AC order with an idempotency key. The buyer confirms the
  server amount and optional tax breakdown before hosted payment opens. Retries
  reuse the same key; an expired hosted step requires a fresh preparation.
- Razorpay SDK subscriptions use the backend's `subscription_ref`; top-ups use
  `order_ref`. An SDK callback or dismissal routes to AC verification.
- Return verifies once, polls unsettled orders, and reads the new balance from
  `/v1/me/usage`. An order's paid display state never supplies the allowance.
- Settings → Plan & billing reads plan, usage and the selected workspace's
  subscriptions. Cancellation stops renewal at the period end and preserves
  the allowance. Account changes clear displayed account data.
- The strict C1 parser accepts optional inclusive/exclusive tax, validates
  integer paise and matching totals, accepts nullable hosted expiry, and accepts
  the C2 catalogue's `per_seat` field.
- Invoice sections stay hidden without invoice data. Renewal approval notes
  use the confirmed subscription flag. Checkout shows the above-₹15,000 note.
- The development fixture now uses `PlansScreen` through the same purchase
  controller, current display prices, tax breakdowns and idempotent fictional
  settlement. It never calls a payment provider.

## Verification

- Latest-main `ac-gate check`: pass.
- `pnpm --filter @ac/sales-xray-web typecheck`: pass.
- App lint: pass; changed-file lint also passes after the SDK changes.
- Focused parser/client/view/hosted-checkout/fixture tests: **16 passed**.
- Full app tests: **1,119 passed, 6 skipped, one unchanged clip-control test
  timed out at 5 seconds**. That exact test passed when rerun alone with
  `--maxWorkers=1` (4.18 seconds). This matches the already tracked shared-host
  timeout symptom in AUT-675; no timeout or assertion was weakened.
- Changed files are formatted with Prettier; `git diff --check` passes.

## Browser and development reference

The existing dev server on `127.0.0.1:3026` serves
`/home/acdev/src/lanes/ui/authority-closers-platform/apps/sales-xray-web`, rather
than this task's checkout. Its Plans screen was inspected at 390px and 1440px
before editing; neither width overflowed. The initial billing browser attempt
there reached the old fixture and failed its first assertion, so it is not
evidence for this change.

`node --test scripts/sales-xray-billing-browser.test.mjs` runs the fictional
purchase → verification → balance → billing → cancellation journey at both
widths. With no supplied origin it owns a temporary Next dev child on loopback
3027, disables the API origin in that child, and terminates it in `finally`.
No Paperclip runtime service is configured for this issue. Results from this
owned test server will be recorded in the next checkpoint.

The fake browser client uses fictional sessionStorage records, not a real
database or the backend payment provider. Actual dev billing activation,
organisation buyer details, invoices and deployed journey checks remain pending.

## Resume

Read AUT-878's merged request/response schemas. Add organisation name/GSTIN
inputs and their serialization using the exact buyer contract, then invoice
parsers, listing and download links. Run the focused checks and browser journey,
open the completed PR for CTO review followed by CEO approval, and verify dev
after the watchdog merges. This checkpoint is not a completed delivery.
