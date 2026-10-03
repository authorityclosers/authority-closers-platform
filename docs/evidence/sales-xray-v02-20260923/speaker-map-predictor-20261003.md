# AUT-315: pure speaker-map prediction and resolution

Source pin: `ee819d0f5b18779c05b5661b06e76f27cabb2ca1` (latest main at task start).
Authority: ADR 0042; [rev 3 plan](/AUT/issues/AUT-624#document-parent-plan-rev3)
revision `da009f49-2e08-40b9-a8cf-dfd1cd96c5cb`; [N1–N8](/AUT/issues/AUT-624#document-decision-brief)
revision `e7301533-e92f-43e8-9ffb-c69e2059eb8f`; [R1–R8](/AUT/issues/AUT-615#document-decision-brief)
revision `6cbf3709-d0f7-4875-8ae5-ccdb8e2c9754`.

Read-only references: `apps/sales-xray-web/app/speaker-profiles.ts`
SHA-256 `ec07b4aa5fe614a734b2191e924c983130e48f368b52808661bcec16d4f112d3`,
and its existing test suite SHA-256
`97c4affb1204a8e96943b193638b14dc84535f6610af10183fca13398b5327b5`.

## Implementation boundary

`predict_speaker_map` reads projected C2 and an explicitly supplied owner profile name.
It ports the shipped Unicode name patterns, stop-list, 150-second window, spelling,
honorific greetings, account-name matching and transcript-only `suggestYou` path.
The server additionally gates `you` on a detected stated-name match; coaching cannot
assert account ownership. Five closed seller cue types plus the account-name cue
provide at most five native segment/time references per speaker. A unique seller on
a two-speaker call makes the counterpart a prospect; three-speaker counterparts,
tied/no cues and `unattributed` remain unresolved. Channel/confidence are null for text.
Playback tail projection retains native C2 evidence time. Inputs are never mutated.

`resolve_speaker_map` accepts already validated, detached source revisions. It applies
per-field user → saved-side channel → same-C2 model → text precedence, ignores stale,
duplicate/unknown-id or multiple-you source maps with content-free diagnostics, and
enforces at most one `you`. Null user names restore spoken defaults, or the profile
name for `you`. Model parsing/literal-evidence validation belongs to S5; channel
capture and mapping belong to phase 3. This module only accepts their resolved interfaces.

`project_speaker_roles` contains exactly provenance/revisions and names-free role
entries. You/salesperson become seller with true/false account-holder flags. Mixed
predicted/model or incomplete maps cannot acquire authoritative origin. No persistence,
HTTP, provider, pipeline, scoring, migration, recipe activation or UI changes.

Size choice: keep the complete pure-module acceptance boundary together, exceeding
the 300-line target to preserve readable Unicode parity, precedence tests and evidence;
S2 storage, S3 HTTP and S4 pipeline wiring remain separate tasks.

## Verification on the dev checkout

Dev reference: https://salesxray-dev.authorityclosers.com. This slice has no endpoint
or visible screen change. From the sales-xray checkout, use only the checked-in
fictional fixtures; no customer call or provider access is needed.

| Command | Result |
| --- | --- |
| `ac-gate start sales-xray 315-speaker-map-predictor` | Started from latest main |
| `ac-gate check` | Allowed to work on this task branch |
| `uv run pytest tests/unit/conversation_intelligence/test_speaker_map.py -q` | 58 passed |
| `uv run ruff format --check packages/python tests` | 904 files formatted |
| `uv run ruff check packages/python tests` | Passed |
| `uv run mypy packages/python` | 381 source files passed |
| `pnpm --filter @ac/sales-xray-web exec vitest run app/speaker-profiles.test.ts` | 15 passed |

The 49-case fixture matrix compares exact names, first-name profile matches and
transcript-only suggestions with the unchanged shipped web implementation. It includes
English, Devanagari, romanized Hinglish, decomposed accents, honorifics, filler/stop-word
regressions, profile match/mismatch/missing, reversed labels, one/two/three speakers,
ties, null attribution and the window boundary. Separate tests cover native clocks,
unattributed roles, server seller additions, per-field precedence, default/renamed
profiles, model-you rejection, stale/malformed maps and uncertain snapshot origins.

Reproduce the shipped-reference comparison from the repository root (exit 0 on pass;
assertion failures exit 1). Transpile only the pure exported section, leaving both web
files untouched; empty findings deliberately exclude the coaching fallback:

```sh
node - <<'JS'
const fs = require('fs');
const assert = require('node:assert/strict');
const ts = require('./apps/sales-xray-web/node_modules/typescript');
const vm = require('vm');
const source = fs.readFileSync('apps/sales-xray-web/app/speaker-profiles.ts', 'utf8');
const pure = source.slice(source.indexOf('export function firstName'), source.indexOf('export const ROLE_WORDS'));
const context = {exports: {}};
vm.runInNewContext(ts.transpileModule(pure, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText, context);
const cases = JSON.parse(fs.readFileSync('tests/unit/conversation_intelligence/fixtures/speaker_map/parity.json', 'utf8'));
for (const item of cases) {
  const names = context.exports.detectSpokenNames(item.transcript).names;
  assert.equal(JSON.stringify(names), JSON.stringify(item.names), item.case);
  assert.equal(context.exports.suggestYou(item.transcript, {strengths: [], improvements: []}, item.account)?.speakerId ?? null, item.web_you, item.case);
  assert.deepEqual(Object.keys(names).filter(id => context.exports.isAccountName(names[id], item.account)), item.account_matches, item.case);
}
console.log('PASS: 49 fictional cases match shipped web names, account matches, and transcript-only suggestions.');
JS
```

Observed result: `PASS: 49 fictional cases match shipped web names, account matches,
and transcript-only suggestions.` Full CI is evaluated on the PR. Server storage,
endpoint/browser journeys and model/channel runtime validation are later slices.

## CTO review round 1 correction — 3 October

The CTO reproduced a provenance downgrade on `f35acbe` when an otherwise fully
confirmed/channel-mapped transcript also contained an `unattributed` segment.
`project_speaker_roles` now excludes that label when selecting provenance, while
the displayed map retains its unresolved row and the names-free snapshot omits it.
Real unresolved speaker labels still prevent authoritative provenance.

The two new fictional regression cases failed before the fix (`predicted` instead
of `confirmed`/`channel`) and pass after it. They cover user-confirmed and saved-channel
origins, snapshot omission, unchanged inputs, and the real-unresolved-speaker guard.
Latest verification supersedes the initial focused-suite count above:

- `uv run pytest tests/unit/conversation_intelligence/test_speaker_map.py -q`: 60 passed.
- `uv run ruff format --check packages/python tests`: 904 files formatted.
- `uv run ruff check packages/python tests`: passed.
- `uv run mypy packages/python`: 381 source files passed.
- `ac-gate check`: this existing task branch may be worked on.

Only the provenance filter, regression tests and this evidence addendum changed.
