# Sales Xray auth and workflow UI checkpoint — 2026-09-24

## Scope

- Replaced `/login` with the shared AccountAuth code-first flow and a responsive Sales Xray brand shell based on an actual ChatGPT Pro image generation pass. The password route remains available when email-code configuration is unavailable.
- Mounted local multi-file staging and processing components, with an explicit account-first path for selected Files. Selecting a File as an unauthenticated visitor opens auth; returning preserves the original File and queue; clicking Analyze reopens auth without a guest upload.
- Updated guest-facing shell and profile copy to describe the required sign-in.
- Added synthetic fixture previews for selected files and auth steps; these previews do not upload, analyse, save, or create report data.

## Evidence

- Pro design reference: `D:\AuthorityClosers-Private\sales-xray-v02-20260923\assets\auth-login-pro-1024-reference.png` (SHA-256 `58394E69DE763D7399586704984E28E0CACFB4CFE9D882955AE0B98EF1F42CD0`). The generated image itself is 1448×1086; browser fit was verified separately.
- Design handoff: `D:\AuthorityClosers-Private\sales-xray-v02-20260923\ui-handoffs\auth-design-1024-handoff.md` (SHA-256 `5F0DE96C8B114D4567786DD3E6D7D80498B5EC941C400929E1E6CF1527C30EEB`).
- ChatGPT Pro conversation: `https://chatgpt.com/c/6ab3e17b-2130-83e9-a03b-3c1f90b1cb95`.
- Commits: `7d7d393f`, `8bc44a46`, `03622e3e`, `6298e370`, `4ce7d16b`, `6e13ea81`.
- In the live local in-app browser, direct `/login` measured document 1024×768 at a 1024×768 viewport with no scroll. Password fallback rendered and fit. Synthetic auth email/code/error fit at 1024×768. Three-file fixture fit at 1024×768, 1280×720, and 1440×900 without document or studio scroll. Processing fixture fit at the same three desktop sizes.
- `apps/sales-xray-web`: `npm test` 48 files / 405 tests passed, `npm run typecheck` passed, `npm run lint` passed, `git diff --check` passed. The integrated guest-selection test verifies no `/source` PUT or `/session` POST before authentication.

## Limits

- The local email-code configuration read returned unavailable, so code delivery and a real account sign-in were not attempted. The code path was checked with synthetic UI states and unit tests; the live browser check covered password fallback layout.
- Fixture files and report states are synthetic. No real recording was uploaded or processed in this checkpoint.
- Desktop fit was measured at the three sizes above; this is not a claim about every possible viewport.
