# Sales Xray legacy clip context — implementation evidence

Date: 2026-09-25. Base commit: `1ee6a6d893b7a432fa187e3b9b56f6b49cc9dccd`.
Status: implementation and local verification complete; deployment verification remains pending.

## Change

- Preserve each report evidence quote and its original time range. Context playback uses a separate selection containing no more than the immediate canonical transcript segment before and after the citation.
- Offer context only when the report source hash, transcript revision, evidence membership, citation text, and segment boundaries match. Revalidate the selection against the current report and transcript before either player seeks.
- Label transcript speakers neutrally by first appearance (`Speaker 1`, `Speaker 2`, and so on). No seller, buyer, or other role is inferred. Context and saved source quotes use the source-script attributes needed for Devanagari text.
- Keep contextual playback bounded at the selected neighbor’s actual interval. Saved evidence playback retains its original stop boundary; manual seeking and full-call playback clear the bounded stop state.

## Verification

- Focused Vitest command for `source-playback-context`, `dipak-overview`, `acquisition-studio`, and `call-studio`: **4 files, 154 tests passed**. Synthetic coverage includes the 800 ms numeric citation with its question and units, a reaction citation with its reply, stale or mismatched bindings, first/last segments, one long neighbor per side, and bounded playback/reset behavior in both hosts.
- `pnpm --filter @ac/sales-xray-web typecheck`: passed.
- ESLint on the eight touched TypeScript source and test files with `--max-warnings 0`: passed.
- Prettier check on the nine changed application files and `git diff --check`: passed.

All examples and transcript content in these tests are synthetic. This patch made no provider calls, persisted report edits, or backend/profile/prompt changes. It does not establish live-call proof, new report-generation semantics, or full Brain3 adoption; those remain separate acceptance work.
