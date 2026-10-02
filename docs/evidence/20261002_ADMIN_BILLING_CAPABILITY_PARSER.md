# AUT-870: approved billing capability parser

- Authority: AUT-870 spec card; AUT-560 S1a/S5a; AUT-861 verified plan.
- Authority source pin: `2988a3b0b7b4fab02724506a7485365abb83ae12`.
- Task base: `fd3ce17532ccf698ef9e9bbe0dc7efa15b5ec0e9`; implementation head is recorded in the issue's PR handoff.

## Change

Added only `platform_billing_manage` to the strict enum and "Manage billing" to the exhaustive label map. Admission invariants, transport bounds, inventory gating and layout are unchanged; no billing route, control or grant was added.
Fictional tests cover billing-only/all-capability admission, unknown billing-like names, duplicates, extra fields, empty permissions, session mismatch, owner-role isolation, label-only rendering and explicit tenant-read inventory access.

## Verification

- Before implementation: four expected failures reproduced the enum/admission and missing-label defects; 901 existing/negative tests passed.
- After implementation: the requested Admin test command exited 0; 54 files / 905 tests passed, including both affected suites.
- `pnpm --filter @ac/admin-web typecheck`: exit 0.
- `pnpm --filter @ac/operations-web exec tsc --noEmit --strict --skipLibCheck --target ES2022 --module preserve --moduleResolution bundler --lib ES2022,DOM,DOM.Iterable src/platform-identity.ts`: exit 0.
- Focused Admin ESLint, `pnpm exec prettier --write` on changed code/tests, `git diff --check`, and `ac-gate check`: exit 0.

## Dev check

Unauthenticated dev access returned HTTP 403; live visual access was unavailable. No real-person sign-in or live grant was used.
Run `pnpm --filter @ac/admin-web test -- app/lib/platform-identity.test.ts app/platform/platform-console.test.tsx`: fictional injection shows "Manage billing", zero inventory calls for billing alone, and one inventory call only with explicit tenant-read. CI/review status is tracked on the linked PR.
