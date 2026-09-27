# Sales Xray upload continuity — P2 implementation evidence

Date: 2026-09-25
Scope: standalone browser source-upload continuity across internal App Router navigation, and root-owned quiet first-use intake behavior. This records code and offline test results only; it does not claim release, deployment, or visual verification.

## Behavior implemented

The root layout owns an `UploadSessionStore`, allowing one upload started in the intake view to continue across client-side route changes. The store retains the selected `File` only in memory, preserves the locally computed SHA-256 across uncertain outcomes, and binds it to the `WorkspaceAccess` person/session/tenant observation. A confirmed account change aborts the request and revokes the retained file; sign-out requires explicit confirmation during unresolved work and clears saved/pending opaque selectors only after the canonical logout endpoint confirms success.

The source flow performs a read-only GET for the same opaque submission ID first. It sends at most one PUT after a 404 and only when the user has accepted the exact current upload-policy digest. The saved selector is promoted only after the server response matches both submission ID and source SHA-256. After an uncertain PUT result, recovery uses a safe GET for that same ID and digest; it does not repeat the PUT automatically. Abort checks after awaited GET/PUT responses and before creating a pending selector or starting the PUT prevent a late success from restoring cleared selectors.

A minimized status indicator stays visible on unrelated saved-call views, while the report remains usable. The indicator links to the exact new call only after the server confirms it. The originating intake owns its upload view and the same client-side transport continues through internal navigation. The two internal New-analysis links use Next `Link`; external, sign-out, and download navigation remain unchanged.

The quiet-intake presentation hides empty lower dashboard panels and sample guidance for a standalone first call. The existing queue rail remains visible with two or more selected files; embedded learner presentation is unchanged. Details specific to the quiet layout are also recorded in `20260925_SALES_XRAY_QUIET_INTAKE.md`.

## Offline verification

Runtime: pinned Node.js `C:/Users/Suyash/.codex/private-artifacts/sales-xray-node24/node-v24.21.0-win-x64/node.exe` (v24.21.0).

Focused test command:

```powershell
& 'C:/Users/Suyash/.codex/private-artifacts/sales-xray-node24/node-v24.21.0-win-x64/node.exe' node_modules/vitest/vitest.mjs run app/hooks/upload-session.test.tsx app/new-analysis/source-upload.test.ts app/shell/lightbox-shell.navigation.test.tsx app/acquisition-studio.test.tsx --maxWorkers=1
```

Result: **4 files passed, 94 tests passed**. Coverage includes navigation during a pending PUT, unrelated report usability, exact-call indicator link, lost-response GET reconciliation with one PUT, interrupted digest retention, aborted late GET and PUT responses, no PUT after an aborted 404, current-policy consent, account revocation, sign-out confirmation and selector cleanup, plus internal navigation links.

`tsc --noEmit` passed. Targeted ESLint over the changed upload, account, navigation, workspace, and shell files passed with `--max-warnings=0`. `git diff --check` passed.

## Limits and release gates

No visual browser check or screenshot was performed in this lane. No real provider, credential, network service, deployment, or product activation was used. The tests use synthetic fixtures and a mocked browser transport. Browser review and release checks remain separate gates.
