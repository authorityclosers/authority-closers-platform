# v0.2 UI and calibration release scope

The founder's current priority is to make Sales Xray usable in staging and production,
while treating a broader Coach/Admin/learner design pass as a coordinated workstream.
API funding and paid provider testing come last. This document records scope; it is
not evidence that the complete release is live.

## Integrated usability pass

- Coach: clearer course hierarchy, module and lesson counts, learner-readiness guidance,
  publication review presentation and upload feedback. Existing authoring and publication
  permissions remain enforced. Source: `2d1c36c`.
- Reviewer: audio and feedback share the desktop workspace; small screens stack them.
  Sales expert, developer and experience-review perspectives provide concrete prompts.
  Observation counts exclude report reference material. Technical IDs and reference
  frameworks are collapsed. Private audio, precise clip bindings, corrections, review
  history, draft navigation protection and idempotent saves are preserved.
- Admin review: email invitations are the primary entry point; existing-account ID
  assignment remains under Advanced. Expiry uses a local calendar input. Drafts survive
  queue hydration; retries reuse the failed request identity, while edits and intentional
  new invitations get distinct identities. Signup, verification and recovery preserve
  the invitation through same-origin fragments and explicit return links.
- Admin Sales Xray: overview, provider settings, analysis revision references and a
  benchmark preparation page. Sources: `0055fbc`, `8910bc8`. These pages expose the
  existing configuration APIs; configuration state is not claimed as runtime state.

## Required follow-on capabilities

| Area | Required result | Current limitation / owner |
| --- | --- | --- |
| Live Sales Xray | Authenticated upload, analysis progress, in-app report, private playback, history, deletion and allowance enforcement | Release/Sales owner is activating the hosted runtime and proving the live journey. This UI pass does not prove it. |
| Learner report design | Measured visuals, timestamped observations, useful suggestions, language controls, history and progress across calls | Sales UI specialist owns the richer report work; retain evidence coverage and avoid fabricated numeric AI scores. |
| Coach design | Consistent learner-quality navigation, course overview, lesson editor, media processing, previews and publish checklist | Current change is a bounded authoring improvement; a full visual redesign remains a separate workstream. |
| Admin calibration | Create/review prompt, rubric and recipe revisions; compare candidate and baseline output; retain human review history | Current settings save revision references. They do not edit prompt bodies, train a model or activate a new analysis recipe. |
| Admin test execution | Admit a chosen consented recording to selected providers with a fixed budget, show progress/results, compare runs and cancel/retry safely | No hosted Admin benchmark/test-run admission API is wired yet. Do not label the preparation page as a working run launcher. |
| Provider credentials | Configure approved credentials through a protected backend secret reference workflow | Browser configuration accepts references, not secret values. No credentials belong in client state, Git, logs or evidence. |
| Final release | One reviewed main, version/release notes, exact immutable deployment on both environments, then prune integrated clean worktrees | Final merge/tag/deployment acceptance and pruning remain release-owner responsibilities. |

## Verification required before calling the release complete

Use exact commits and runtime identities. Verify Admin/Coach/learner login, course
editing and publication, the licensed 4K media path, invitations and mail delivery,
Sales Xray allowance/admission/report/playback/history, and responsive layouts on
staging and production. Local fixture/browser evidence validates implementation;
it does not substitute for those live acceptance checks. Keep previous release
receipts and failed attempts; append superseding evidence.
