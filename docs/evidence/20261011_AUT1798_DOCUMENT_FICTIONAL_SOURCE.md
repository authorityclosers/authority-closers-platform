# AUT-1798: standalone fictional Document agrees with its own source

QA's 23:23:26 UTC finding is retained in strike 1798's INBOX. Its standalone
Document showed a declined next step in 1.1/6.2 and an agreed follow-up time
in 1.3. Original captures:

- `1694/shots/2026-10-11-workbench-document-quote-readback/document-overview-1440-dark.png`
- `1694/shots/2026-10-11-workbench-document-quote-readback/document-facts-390-light.png`

## Proved cause and repair

`review-fixture/report/synthetic-report.ts` replaced the outcome but spread
`base.overview` from `tests/fixtures/dipak-overview.json`. That inherited
diagnosis, conversation change, missed moments and ethics notes citing the
other fixture's `s1`/`s2`/`s3` dialogue. Both Document and Word faithfully
read that inconsistent input; no production reader change is needed.

The source file was unclaimed in the active strikes' NOTES. G claimed it
before editing; B acknowledged no claim or dirty-edit collision at 23:28:36
UTC. The shared copy/section/model and recording dock remain with their
existing owners.

The corrected overview explicitly uses this fictional call's three authored
records: `synthetic-concern` at 12–15 s, `synthetic-boundary` at 26–30 s,
and `synthetic-respect` at 31–35 s. Its influence and recommended deal action
now respect the buyer's existing request not to follow up. Unrelated
inherited change/missed/rewatch/ethics claims are omitted. The existing
uncertain-timing observation is bound to its own quote; no motive is added.
The improvement detail remains for existing Coaching readers, using that
quote and the existing future-call focus. The two original unknowns remain
"Comparable conversion history" and "Lead volume".

The Document fixture maps both buyer lines to the fictional buyer and the
seller's acknowledgement to the fictional seller, replacing the alternating
speaker assignment. All three quotes, ids, time spans and the original
no-sale outcome block are byte-identical before/after. The person-recorded
outcome remains **Outcome not set**, with no invented commitments, next event,
progress, score, audio or provider run. No saved or real report was edited.

## Focused verification

Final finite `ac-heavy` check started at 23:29:58 UTC and exited normally
by 23:31:14 UTC:

```sh
pnpm exec vitest run app/review-fixture/document/document-preview.test.tsx app/review-fixture/report/synthetic-report-preview.test.tsx app/report-document.test.tsx app/report-document-model.test.ts app/report-docx.test.ts app/report-call-coaching.test.tsx
pnpm exec tsc --noEmit --incremental
pnpm exec eslint --cache --cache-location node_modules/.cache/eslint/ app/review-fixture/report/synthetic-report.ts app/review-fixture/document/document-preview.tsx app/review-fixture/document/document-preview.test.tsx app/report-docx.test.ts
```

**46/46 PASS**, full incremental Sales Xray typecheck PASS, cached touched-file
lint PASS, scoped whitespace PASS. Regression assertions require every report
and Document clip source to equal one of the three exact evidence records;
1.3 and 6.9 agree with the buyer boundary; 6.8 retains both unknowns; actors
match the authored lines. The Word test checks the same boundary/action and
rejects the other fixture's follow-up claim and quote.

The first 38 tests passed, but the initial typecheck caught an existing
Coaching test expecting its improvement-detail record. The final repair
keeps that record with this call's quote and includes the eight Coaching
reader checks. This initial typecheck failure is retained, not a claimed pass.

## Source pins

| File | Before SHA-256 | After SHA-256 |
| --- | --- | --- |
| `review-fixture/report/synthetic-report.ts` | `5fab18ba35fd0fa0c36ea1fa4f3bc8e9bc2b3227c4105269fb04fc93447ccc4b` | `101f8311744f66ce9dd9cae415a173ebda420a2a9fb19ae0c46719b0f37cf6ad` |
| `review-fixture/document/document-preview.tsx` | `aba59013e4a5c0a78b7b34c18551223a3d005cebfce4b164fea3398bd0cf634d` | `04a929dbaadbf6deefbd4d19ff4bd4070798b8dfb40ada1d6fda7fb3c3eccd83` |
| `review-fixture/document/document-preview.test.tsx` | `3b404d418ce0f63d97c6838a31d638e81e08f4dc80d1a23a9d0cc7163b0bce2f` | `7c7c051a969bd12b52939bd78e1d06a039935e5d9d30ac3fa296d1c4c09b8f42` |
| `report-docx.test.ts` | existing test retained | `a76bd77b33bb2b17741236eaf54f1c702a430448af7ab4bae731b6684caeaadb` |

All app paths are relative to `apps/sales-xray-web/app/`. Shared-dev readback
is pending the post-commit warm-up; the bounded fixture harness is
`1798/harness/document-fictional-source-proof.mjs`. This is fictional builder
evidence, not production or an authenticated persistence result.
