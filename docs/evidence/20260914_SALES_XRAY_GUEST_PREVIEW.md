# Source-bound guest preview

The owner's September 14 request replaces the previous all-findings-free guest view. Guests now receive whole, useful findings; a free claimed account receives the complete canonical report. No stored report, transcript, profile, claim authorization, or minute ledger is modified by this projection.

## Projection and integration

- Root finding lists and independent overview lists show approximately 60%, rounded to whole entries: 0→0, 1→1, 2→1, 3→2, 8→5, 10→6. A single finding is never cut into an incomplete quote.
- Linked strength, improvement and missed-opportunity explanations are removed with withheld findings. Golden moments referring to a withheld strength are also removed, including a lone linked moment. Retained indices preserve the original prefix, and first-improvement practice/focus remain consistent.
- Summary, verdict, dimensions and singleton overview sections remain available. The complete original transcript remains source evidence. This is a finding preview, not a guarantee that independently authored summaries never discuss similar topics.
- Additive `report.preview` projection metadata uses version `guest-findings-v1` and per-section `visible_count`, `total_count`, `hidden_count`. Claimed-account projections use `preview: null`; historical envelopes without metadata remain readable.
- The client verifies allowed keys, integer bounds, actual displayed lengths, count arithmetic and projection ratios. It uses the existing literal quote, timing, transcript and overview reference validators.
- `DipakOverview` accepts optional `onUnlock: () => void`. The acquisition UI owner connects this to the existing account flow. Cards say “Unlock remaining insights with a free account” and use actual additional-item counts. Hidden findings are absent from the response, not placed beneath CSS blur. Retained objection/closing findings now also have source playback controls.
- Existing password registration already accepts first name, email and WhatsApp number. This patch does not add a username or alter mailbox verification.

## Tests executed here

Receipts are in `D:/AC-authority-closers-release-audit/`.

| Check | Result | Receipt |
| --- | --- | --- |
| Full conversation-intelligence unit suite | 846 passed, 1 POSIX-only skip; one existing Starlette/httpx warning | `peer-guest-preview-all-20260914.log`, matching JUnit XML |
| Final focused projection suite, including rewatch redaction | 28 passed | `peer-guest-preview-focused-final-20260914.log` |
| Standalone frontend suite | 171 passed, 18 files | `peer-guest-preview-web-20260914.log` |
| TypeScript | Pass after fixing a synthetic JSON fixture's literal typing | `peer-guest-preview-types-final-20260914.log` |
| ESLint | Pass, zero warnings | `peer-guest-preview-lint-20260914.log` |
| Ruff and diff whitespace | Pass | Coordinator command receipt |

The original failed typecheck is retained in `peer-guest-preview-types-20260914.log`. It was a test-fixture assignment of a broad JSON string to a literal-union type; no runtime parser check was removed to fix it. The final fixture change preserves the same tested invalid-reference payload.

Tests cover whole-finding redaction across list lengths, absence of hidden titles/explanations/linked notes, reference preservation, immutable account parity, tampered metadata, source/quote validation, historical envelopes, account unlock invocation and retained source controls.

This is local implementation/test evidence. No provider call, production setting, database edit or deployment occurred in this patch. Combined browser/network tests, final release CI, staging and production activation remain owned by the release coordinator.
