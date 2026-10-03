# D1 scorecard receipt repair — AUT-1022

Base: `c387b2d12be65c03342c19dce2390b112bee8b8f` (latest main at gate start, 2026-10-03).
The script, test and session-fixture SHA-256 digests matched [measurement evidence](/AUT/issues/AUT-1020#document-measurement-evidence), revision `6b3cf8b5-c139-4b21-81e8-a6760312ec8d`, inspected source `06c6ca511de3930719a3f57f725ff84d067916c1`.
Declared basis is reported provenance, not installed-producer verification; [AUT-862](/AUT/issues/AUT-862) still gates live Codex validation. No provider or live receipt API was invoked.

In-memory `build_report` / `render_report` replay, same fictional counters before and after (chronological pairs; exact token-cell text):

| Fictional fixture | Before: run tokens / cell | After: run tokens / cell |
| --- | --- | --- |
| Session, Codex per_run | [110,65] / `175.00` | [110,175] / `285.00` |
| Session, legacy Claude per_run | [170,105] / `275.00` | [170,275] / `445.00` |
| Week, two unknown runs | `209.00 (2 runs unreported)` | `n/a (incomplete usage) (2 runs unreported)` |

Week known subtotal remains 418 internally; no partial subtotal is presented as exact tokens per done task. All-known builder attribution retains `400.00`; empty denominators retain `n/a (no done tasks)`.
The session fixture now explicitly describes independent per-run receipts. Other fixture edits add basis annotations only. Fixtures without adapter metadata receive fictional `codex_local` metadata in memory through `fixture_source` in the focused test module; runtime unknown adapters remain unknown.

Verification on the task branch (exit 0 for each; final head SHA is recorded on the task/PR):

- `TMPDIR=$PAPERCLIP_RUN_SCRATCH_DIR PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/infra/test_agent_scorecard.py -q -p no:cacheprovider`: `98 passed in 0.44s`.
- `.venv/bin/ruff format --check packages/python tests`: 914 files formatted; `.venv/bin/ruff check packages/python tests` and the changed script/test lint: passed.
- `TMPDIR=$PAPERCLIP_RUN_SCRATCH_DIR .venv/bin/mypy --cache-dir "$PAPERCLIP_RUN_SCRATCH_DIR/mypy-cache" packages/python`: no issues in 385 source files.
- `ac-gate check`: task branch allowed. CLI fixture success stays 0; validation/read failures stay 2.

Coverage: both providers; three-run per_run/server-delta/raw sequences; interleaved agents/tasks; week boundaries; session rotations; unmarked counter/cache decreases; adapter changes; omitted cache and explicit zero; JSON strings/objects and malformed JSON; booleans, negatives, NaN/infinity; absent fields; conflicting basis; unsupported adapters/ACPX shapes; immutable input and order-independent results. Known server deltas remain Codex [110,65,25] / Claude [170,105,35]; raw sequences and missing predecessors remain unverified.

Dev handoff after merge: record the deployed source SHA, run the focused pytest command above, then load this test module in memory and call `scorecard.render_report(report())` and `scorecard.render_report(report(session_source(adapter)))` for both providers. These helpers use only fictional fixtures and make no API calls. Record the output on [AUT-1022](/AUT/issues/AUT-1022); dev/staging verification and green CI remain release checks, not claims in this local evidence.
