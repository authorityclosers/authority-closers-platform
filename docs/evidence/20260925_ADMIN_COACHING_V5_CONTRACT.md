# Admin coaching v5 contract repair

## Observed defect

On 2026-09-25 the staging Sales Xray settings page displayed “Analysis limits
could not be verified” while its provider controls loaded. The API supports
`coaching-v5` (`conversation_intelligence/analysis_settings.py`), but the Admin
web settings contract accepted only v3 and v4 in both saved settings and the
advertised bounds. This also prevented reading a revision history containing v5.

## Change

The Admin contract accepts the three explicitly supported revisions. Both v4
and v5 permit the server-supported English, Hindi/English and Marathi/English
settings. The v5 selector has its own label. Older responses still default to
v3/English and offer only advertised choices. Unknown revisions, unsupported
languages, existing token bounds and the v3 English-only restriction remain
validated. Saving continues to create an immutable future-plan revision; this
patch does not modify live settings or accepted plans.

## Validation

With Node 24.21.0, from `apps/admin-web`:

- `vitest run app/sales-xray/analysis-settings.test.tsx app/sales-xray/analysis-settings-history.test.tsx`:
  2 files, 10 tests passed. Includes loading and saving v5 for all three supported
  languages, mixed old/v5 history, unsupported future revision rejection and
  preserving existing limits.
- `tsc --noEmit -p apps/admin-web/tsconfig.json` from the repository root: passed.
- Targeted ESLint with zero warnings and `git diff --check`: passed.

This is local contract/UI verification. The repaired Admin bundle must still
be packaged, deployed and checked against the staging API before claiming the
live settings screen is repaired. No provider execution or credit mutation was
performed by these tests.
