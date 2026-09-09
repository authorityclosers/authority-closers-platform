# Operations workspace sign-in — local implementation evidence

Date: 2026-09-08. Scope: shared Admin/Coach frontend, local automated validation.

The extracted [shared login](../../packages/typescript/operations-web/src/operations-login.tsx) now uses the canonical [workspace client](../../packages/typescript/operations-web/src/operations-workspaces.ts). Its companion backend is documented in [self-workspace evidence](20260908_SELF_WORKSPACES.md).

An existing session with one already selected, authorized workspace retains the fast path. Multiple memberships or a selected context without the requested app's access receive an explicit named-workspace selector. Password authentication and Google return-to-`/login` use the same recovery. Mount performs reads only; selection requires an explicit action and existing `POST /v1/context`, followed by canonical identity and app-specific permission verification. Person, identity session and selected tenant must match the authorized listing. Membership alone does not create Studio capabilities or Platform Admin access.

Production never requests a manually entered tenant UUID. The explicit synthetic-local tenant workflow remains available only in local mode. Credential inputs and submit are disabled before hydration; forms use POST. Errors use bounded local copy rather than upstream bodies. Pending selection is deduplicated, aborted on unmount/surface change, and late results cannot navigate. Empty membership lists offer confirmed sign-out recovery.

Admin and Coach anonymous-page redirects now use relative `/login` with `Cache-Control: no-store`, avoiding internal HTTP authority in HTTPS proxy deployments. Legacy Admin Studio links retain only the path when redirecting to the exact configured Coach origin; commands are not redirected.

Validation: **221 passed** across eight focused API, identity, session, transport, access, workspace-client and mounted-login test files. Full Admin TypeScript check passed; scoped ESLint and diff checks passed. Seven pre-extraction access-test expectations were updated to test public login, relative redirects and the separate Coach boundary while retaining permission denials. New checks cover malformed/duplicate workspace identities, scope mismatches, no inferred selection, OAuth recovery, pending/unmount races, and pre-hydration safety.

No browser, real identity, Google-provider, runtime restart, deployment or live multi-workspace proof was performed in this subtask. The three-app extraction review found the multi-membership selection gap; sole-membership auto-selection already existed and was preserved. Parent independent review and integrated runtime acceptance remain required before release claims.
