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

## Completed reader handoff

B committed its owned import/re-export and duplicate removal as `4e847e7c`
at 23:21:04 UTC. G independently compared the original declaration from
`1864b5a9` with the shared module: byte-identical. The new reader imports and
re-exports `GUEST`, with no local declaration; its SHA-256 is
`befb261c50f0b6012c46e16c197c7a3e0a0f1eb09409bc9f0c1855e4b9e90b41`.
Both current source hashes match B's retained source-pin receipt.

Consumed B's completed checks without repeating them:

- `report-pillar-screen.test.tsx`: **8/8 PASS**, including original guest
  counts and sign-in checks.
- `report-corpus.test.ts`: **1/1 PASS**; B reports 13 saved reports as account
  and guest projections, 156 rendered sections, 26 valid Word files,
  0 failures/provider calls, and 3 retained missing baselines.
- B's incremental Sales Xray typecheck and focused cached lint pass.

B's post-commit shared-dev account-shell smoke completed
23:23:03–23:23:15 UTC: **4/4 PASS**, 1440/390 in light/dark, no page errors,
sideways overflow, hot-reload refreshes or outcome requests. Source HEAD
stayed `84b2c8761567bfe4a6e945f5e1d41573036b3fec`. G inspected all four
saved populated screenshots. This fixture account-shell browser check is
separate from the guest rendered/model tests and does not establish a
deployed signed-out persistence journey.

Retained B receipts in `/home/acdev/strikes/1677/`:

| Receipt | SHA-256 |
| --- | --- |
| `guest-copy-validation-20261011.json` | `c1b12fa5924a37ef6d49044fafe1fae43f1e8f902a92aa7bcc1231dd17eb9675` |
| `guest-copy-source-pins-20261011.json` | `30333b91453eb706bfa6748c6b594c932ff8f99903aa00fa3ee13b8031af258f` |
| `shots/2026-10-11/guest-copy-shared/receipt.json` | `ec75bdbb1b6e71125fe161cefa54c10b3e59518ea51616a3e112e60e49233afd` |
