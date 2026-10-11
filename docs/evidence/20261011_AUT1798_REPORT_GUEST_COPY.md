# AUT-1798: shared Report guest copy

Request: B → G, 11 Oct 2026 23:14 UTC, retained in strike 1798's INBOX.
Reviewed against the existing guest words in
`apps/sales-xray-web/app/report-sections/shared.tsx:106–112` on workbench
HEAD `1864b5a9`. This is a bounded continuation of the existing copy module,
not a new Report design or an analysis-language rewrite.

`app/report-copy.ts` now exports `GUEST` with the existing three values:

- `more(count, noun: [string, string])` retains the count, singular/plural
  noun, and `is`/`are` agreement in the existing saved-for-your-account line.
- `unlock`: "Unlock with a free account".
- `fullReport`: "Sign in to see the full report".

The existing component declaration is still in B's claimed file. B will
import/re-export the shared keys there and verify account/guest readers.
This change adds no rendered UI difference, so this packet records module
readiness rather than a new browser or signed-in journey result.

## Validation

Finite check run started at 23:18:15 UTC and exited normally before
23:18:43 UTC through `ac-heavy`, from `apps/sales-xray-web`:

```sh
pnpm exec vitest run app/report-copy.test.ts
pnpm exec tsc --noEmit --incremental
pnpm exec eslint --cache --cache-location node_modules/.cache/eslint/ app/report-copy.ts app/report-copy.test.ts
```

- Copy suite: **7/7 PASS**, including exact singular/plural saved-item lines
  and both existing account/sign-in labels.
- Incremental full Sales Xray typecheck: **PASS**.
- Cached lint of the two touched files: **PASS**.
- Scoped `git diff --check`: **PASS**.

## Source pins

SHA-256 after the change:

| Path | SHA-256 |
| --- | --- |
| `app/report-copy.ts` | `549ab86125297423c59a2053c61012bc170ea9db42571205205cd5060d817f63` |
| `app/report-copy.test.ts` | `e15b0bba8e34ab4c4b991caec7323852228835b795e0e21798552cceb78f1e42` |
| `app/report-sections/shared.tsx` (read-only baseline) | `9082790a4535cd0003be2d68e35c79e030c03f3057d15ec607d4aad6e867a994` |

Only the owned copy module, its test, and this evidence are committed.
Existing unrelated worktree edits remain with their owners. No account,
source-data, outcome, provider, release, or deployment action was performed.
