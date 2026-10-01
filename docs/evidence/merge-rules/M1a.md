# M1a: pure path classifier

Task: [AUT-618](/AUT/issues/AUT-618). Base: `8d8a9be48f0cb37c4e485f558ad508911e503b7e`.
Sources: [CTO brief](/AUT/issues/AUT-544#document-cto-brief), revision
`a0769a8b-2068-4da8-be3b-64ca96bd278e`; [amended plan](/AUT/issues/AUT-589#document-plan),
revision `8c9f8dbb-4f41-4f78-96aa-e62e7cee1cb7`; [synchronized instruction packet](/AUT/issues/AUT-589#document-board-action-batch),
revision `6c68b0a2-ba05-4f6e-91d2-7e8d9cd9109a`.

## Implementation

`scripts/ci/merge_class.py` exports `classify_changed_files(files, contents, *, changed_files, truncated=False)`.
It returns only `routine` or `escalation`, with sorted unique reason codes. It has no IO,
input execution, GitHub access, content interpretation or downgrade override.
The caller must supply complete GitHub records and head-pinned strings; this pure contract
cannot verify a GitHub SHA. M3 supplies that provenance, not M1a.

Protected rules inspect the full case-folded path, including both rename names and deleted
paths. All card categories, purchases, secret/Infisical names and common top-up spelling
variants escalate. Ordinary files under exact apps/packages/tests/docs/tools roots are routine;
case-distinct roots remain unknown on the repository's case-sensitive filesystem.
Dockerfile protection includes the exact basename, dot/hyphen/underscore suffix variants,
and `.dockerfile` endings, case-insensitively.
Every db/migrations path escalates; no AST exception exists until M1b.
Evidence rules require list/tuple records, a matching nonnegative integer count, a boolean
truncation flag, recognized added/modified/removed/renamed statuses, canonical relative paths,
distinct path evidence, and valid previous names only for renames. Surviving files require
string contents; removed files do not. Unsupported statuses and ambiguous evidence escalate.
Reasons contain policy codes, never filenames or supplied content.

Owner-only fixtures cover secrets, billing settings, payment settings, purchases, production
data-change scripts and deletion, including both rename directions and missing/ambiguous
rename evidence. Innocently named file contents do not establish protected business semantics.
No classifier output or approval line grants separate owner permission for these actions;
AGENTS.md rule 5 and OWNER-APPROVED procedures remain mandatory.

## CEO conditions and deferred handoff

1. CTO review then CEO approval remains mandatory until 24 continuous shadow hours have
   no unexpected differences and the synchronized source/instruction switch is verified.
2. A classifier miss posts `Rule approvals paused` immediately. Only CEO may post
   `Rule approvals resumed`, after the corrective fix actually merges.
3. Protected owner-only paths and incomplete/ambiguous classification evidence fail closed;
   merge approval never supplies separate owner permission.

The amended plan and instruction packet link [deployment prep AUT-619](/AUT/issues/AUT-619)
and [Root shadow/switch AUT-620](/AUT/issues/AUT-620). M3/Root owns provenance, pause posting,
watchdog state, board changes, shadow timing and activation. No strict branch-up-to-date
requirement applies: red/unknown main pauses merges; running main alone does not.
This PR changes no live authority, workflow, gate, instruction bundle or environment state.

## Review correction

CTO review of `2ba74ef57b55d8a1b33e87132339f9ed9121f152` found that
`apps/Dockerfile-dev` and `apps/Dockerfile_dev` bypassed deployment protection.
The two fictional fixtures add 20 cases: original/uppercase names, added/modified/removed
statuses, and both rename directions. Before the fix they produced **20 failed, 407 passed**;
after extending the basename prefix rule they produce **427 passed**. Each case requires
`protected:deployment` and sorted unique reasons. Only the three card files changed.
This correction is pre-activation evidence; the deferred shadow/pause/switch conditions above
remain mandatory, and the corrected head requires fresh CTO review then CEO approval.

## Verification

Offline dev check runs fictional records in the platform lane checkout, using the repository
virtual environment: `PATH="$PWD/.venv/bin:$PATH" python3 -m pytest tests/unit/test_merge_class.py -q`.
System python lacks pytest; no host package installation is needed. This is pure-function
evidence, not a claim of merged deployment or the future shadow window. No screen/API/report
changes require browser QA. After merge, repeat the narrow command on dev.
Results on 2026-10-01:

- Corrected narrow pytest: **427 passed**, exit 0. The initial reviewed head had 407 passing
  cases, including a separate verification of the pytest console entry point.
- Repository `pnpm run format:check`, `pnpm run lint`, `pnpm run typecheck`: exit 0.
- Explicit script/test Ruff formatting and lint: exit 0; explicit classifier mypy: exit 0.
- `python3 scripts/ac_task.py check`: exit 0. `git diff --check` is required before push.
- The PR and task carry head-specific CI/single-track receipts. Remote checks start when
  the PR opens; this offline evidence does not claim they have passed in advance.

The complete fictional fixture matrix and evidence exceed the nominal ~300-line target;
this is recorded on the task, with the three-file scope and bounded M1a behavior preserved.
