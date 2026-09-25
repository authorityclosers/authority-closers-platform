# Lightbox and core integration — 25 September 2026

## Purpose

Combine the reviewed Lightbox P1 shell with the current core release so the next
release can retain both the UI foundation and the OpenAI/backend changes.

- Core parent: `234ca575fada1c21f1e6a11fd347caa0d623e0e0`.
- UI parent: `fb2f743ebcd3cb512b9db42024da0f3913739f77`.
- Integration branch: `codex/sales-xray-v02-release-20260925`.
- The merge has no content conflicts. No source change was required to reconcile
  these parents.

## Local verification

The first combined check found that this checkout had not installed the four
font dependencies already recorded in the UI lockfile. An offline, frozen-lockfile
install with lifecycle scripts disabled reused four cached packages, downloaded
nothing, and did not change the lockfile. The repeated check passed:

```text
vitest run app/acquisition-shell.test.tsx app/styles.integration.test.ts
  app/layout.test.tsx next.config.test.ts --maxWorkers=1
4 files passed; 12 tests passed
```

The available local Node runtime was `v22.17.0`; pnpm was `11.19.0`. This is below
the repository's required Node 24 runtime, so these checks are local integration
evidence only. Exact-source CI on the required runtime, build, and release/browser
acceptance remain required before promotion.

`git diff --cached --check -- apps packages pnpm-lock.yaml` passed. The complete
diff reports whitespace already present in three lines of the imported original
design asset sheet and handoff document; those source artifacts were preserved
without rewriting their contents.

## Limits and next work

This integration alone does not complete P2 background uploads, the report
redesign, admin minute grants, or the full v0.2 acceptance scope. The newer quiet
intake and upload work remain in the separate UI worktree pending review and
integration. Admin allowance changes likewise remain separate pending database
verification.

No staging or production release, credential change, provider call, database
mutation, or report-quality benchmark was performed by this merge. The deployed
staging revision remains `234ca575`; production remains at its separately
recorded revision. The existing branches and release receipts remain available
for comparison and rollback.
