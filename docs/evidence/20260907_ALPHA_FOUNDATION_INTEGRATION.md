# Alpha foundation integration — 7 September 2026

Status: implemented local candidate; **not a staging, production or final Alpha acceptance claim**.
Baseline: `31aee3ce5915e476c08a722f8b28768b49b514cf` on staging.
Implementation lane: `codex/local-staging-dev-bridge`, worktree `d2de`.
Candidate: the code checkpoint carrying this record; no live release SHA assigned.

## Implemented scope

- Shared presentation-only company/academy/platform identities, supplied AC Open A,
  Closers Academy book and provisional Cohorva marks. No tenant IDs, role names,
  authorization predicates, memberships or canonical curriculum changed.
- Desktop and mobile academy shell identity; mobile honors the configured academy
  destination. Admin uses the provisional platform mark while retaining real
  selected-tenant and permission information.
- Selected verified portrait derivatives replace the heavy public hero image and
  supply the learner home portrait. Source access/provenance is documented in
  [brand evidence](20260907_ALPHA_BRAND_ASSETS.md). Total selected public brand
  inventory is 24 files / 147,798 bytes, not an initial-transfer measurement.
- Manifest, Apple icons and a new shell-cache version use supplied academy icons.
  Only the three exact versioned icon paths become cacheable; protected API/media
  responses remain excluded. Production PWA lifecycle acceptance is still pending.
- [Theme runtime extraction](20260907_ALPHA_THEME_RUNTIME.md) removes settings
  UI/CSS/icons from the root appearance runtime. Existing preference compatibility,
  persistence and effective reduced-motion behavior remain supported.
- [Dashboard plan loading](20260907_ALPHA_DASHBOARD_PLAN_LOADING.md) lets the primary
  task render before optional plan responses, while preserving fatal current
  session failures, abort handling and stale tenant-response rejection.
- [Sidebar navigation](20260907_ALPHA_SIDEBAR_NAVIGATION.md) tracks real Next link
  pending status rather than permanently latching click feedback. Dirty-work guards,
  disabled/current links and no-prefetch behavior are preserved.
- The existing six-file Discover/My Learning polish was retained and integrated.
  Root tightened a responsive test's selector so it checks the intended phone grid,
  rather than accidentally accepting an unrelated two-column rule.
- Home copy now says course progress and continue learning, not weekly activity or
  continue watching where those facts are not known. Home no longer unconditionally
  claims missing media; the actual activity/player still uses authorized media state.

## Browser review drove additional fixes

Isolated Chrome contexts use synthetic API reads and block API writes. These are
local-development browser results, not live learner, throughput or lab-speed proof.
No existing browser profile, cookies or authentication state was copied.

1. Initial direct collapse clicks failed because the test ignored the control's
   hover/focus affordance. Normal pointer entry followed by an unforced click works;
   this was corrected in the test, not presented as a product fix.
2. Mobile search really was hidden by a late CSS rule. Restored its 44px target;
   mobile command search, Escape and focus restoration are tested.
3. New course cards still moved in reduced motion due to cascade specificity.
   Both explicit preference and OS-reduced rules now suppress hover transforms.
4. Dark-mode header account text measured only 1.16:1 after parent opacity.
   Replaced both hardcoded source colors with the appearance text token; the
   recheck measured 12.03:1 in the tested dark header.
5. The More sheet now follows surface, text, border and danger tokens. It retains
   semantic sign-out color and existing focus/inert-background behavior.

Final [browser QA](20260907_ALPHA_SURFACES_QA.md) passed 24/24 cases in run
`20260907T122356Z`: zero overflow, page/console errors, unknown API reads, writes or
external attempts; 12 reduced-motion combinations, eight search/focus cases,
four More/focus cases and four real sidebar collapses. All 12 primary screenshots
were visually reviewed independently; the root also reviewed dark desktop and
320px mobile captures. There are 32 PNGs, 3,615,063 bytes.

Browser run evidence is recorded separately by `scripts/qa_alpha_surfaces.py`.
The development-only bridge banner and Next development indicator visible in its
screenshots are not production UI. Passing this two-route matrix does not certify
all learner/Studio routes or every state.

## Engineering verification and limits

- Required local runtime: Node 24.19.0, pnpm 11.19.0, Python 3.12.
- First full check: formatting, ESLint/Ruff and TypeScript/mypy passed; learner
  519/519 and admin 132/132 tests passed; Python 1,203 passed, 139 skipped and one
  cookie-isolation browser test failed. Its original traceback was truncated.
- [Cookie-browser repair](20260907_ALPHA_COOKIE_ISOLATION_BROWSER.md) aligns the
  Chromium launch channel with the binary actually checked and allows an explicit
  installed Chrome channel. The exact unchanged isolation assertions passed in
  Chrome 152; this does not establish the cause of the original failure.
- Both optimized Next 16.2.11 builds passed before the final small CSS corrections.
- A subsequent aggregate rerun passed formatting/lint/typecheck and JS tests, but
  Python collection encountered Windows resource error 1450 while local browser
  QA and transcoding were also running. This is a failed run, not silently waived.
  Resource-heavy verification was then sequenced; the successful final run below
  supersedes this failed run without erasing it.
- The retained serial Python run reproduced the browser failure before launch:
  a collected PostgreSQL test installs Windows' selector event-loop policy, which
  cannot launch Playwright subprocesses. The cookie test now scopes a Proactor
  policy around Playwright and restores the previous policy on success/failure.
  Full collection with targeted execution passed all three browser/policy tests;
  no global application policy or isolation assertion was weakened.
- Independent source review: prior mobile-destination and reduced-motion Important
  findings corrected; 247 focused tests and eight executed service-worker boundary
  checks passed. Later mobile/theme fixes passed the final browser retest above.
  Final independent media/cookie review found no Critical/Important defects;
  36 targeted tests and Ruff passed.
- PostgreSQL-backed suites that lack their configured integration database are
  skipped, not counted as proof. No production performance or actual-field claim.

Final aggregate command, with `AC_BRIDGE_COOKIE_BROWSER_CHANNEL=chrome` and Node
24 first on PATH: **`pnpm validate` exited 0**. Formatting, ESLint/Ruff,
TypeScript/mypy, 519 learner tests, 132 admin tests, 1,216 Python tests and both
optimized production builds passed together. Python reported 139 explicit
environment-dependent skips and one existing Starlette/httpx deprecation warning.
Local output is retained at `.tmp/alpha-final-validation-20260907.log`.
Build-generated `next-env.d.ts` path churn was restored to the tracked development
paths afterward; no unrelated generated-file change is included in the checkpoint.
Required remote CI/integration environments and full Alpha gates remain pending.

## Licensed test media addition

The user explicitly requested real high-quality sample footage and VPS playback
testing. The acceptance contract now includes A13, requiring at least two licensed
high-quality sources including 4K, a separately labeled staging test content/version,
authorized ingestion/binding/delivery, controls/range/seek/resume/captions/network
and access-negative testing, and bounded VPS resource/concurrency measurements.
Sample film is not Dipak's actual instruction and cannot fabricate learner evidence.

On 7 September, the existing strict acquisition CLI downloaded official Big Buck
Bunny Sunflower 2160p30 footage into the ignored test cache. The pinned archive hash
`750b255c6d9fee1e2a03a6716d4f358bca56e9115bf3e06a66162fc5272ae151` and video hash
`37f0ff251a606c2dcfa26c19fe6bf843234b4e7a8889cfab50bc26f644e55520` both verified;
ffprobe confirmed 3840×2160, 30 fps, 634.6 seconds. The archive is 632,204,510 bytes
and the extracted master is 633,016,449 bytes. Attribution and CC BY 3.0 are pinned
in `tools/media-player-stress/fixture-manifest.json`.

Default Python HTTPS verification reported an expired certificate; Windows-backed
`truststore` validation successfully used the existing strict CLI. Certificate
verification was not disabled and the download host, size and checksum gates were
not weakened. Reproduction wrapper:

```powershell
uv run --with truststore python -c "import truststore,runpy,sys; truststore.inject_into_ssl(); sys.argv=['acquire_media_fixtures.py','acquire','--fixture','bbb-4k-30-normal','--timeout-seconds','600']; runpy.run_path('tools/media-player-stress/acquire_media_fixtures.py',run_name='__main__')"
uv run python tools/media-player-stress/acquire_media_fixtures.py verify --fixture bbb-4k-30-normal
```

A bounded 12-second local HLS ladder completed with 2160p, 1440p, 1080p, 720p,
480p and 360p profiles plus synthetic diagnostic captions. It lives under
`tools/media-player-stress/.artifacts/hls/alpha-bbb-4k-20260907/` and records the
then-current fixture manifest digest `ee4da2e4039d458ecaf933aaa9a019fee29eb813addbe85b61ef7d78254859ae`.
This is local encoding evidence, **not VPS streaming, adaptive player or course
publication proof**.

The [second fixture slice](20260907_ALPHA_SECOND_MEDIA_FIXTURE.md) is also complete:
official Caminandes 2: Gran Dillama, native 1920×1080/24 fps, 146.041667 seconds,
CC BY 4.0 as identified by its current specific Blender Studio item. Its full ZIP
and MP4 were acquired and hash/probe verified. The current registry adds this
exact source and preserves checksum/provenance/path/production gates. A 12-second
1080p/360p test ladder encoded successfully with two-thread decoder/filter/encoder
pools. These are per-pool caps, not OS memory or total-process quotas. All 161
media unit tests passed; no master, sample binding or provider configuration was
published to VPS.

## Skill, documentation and preservation

The user authorized updating `workflow-ui-production`. Its revised workflow
distinguishes exploration, actual implementation and release; limits unnecessary
artifact generation; tests mounted runtime paths; requires measurable browser/
performance/PWA evidence; and separates fixture/local/staging/production claims.
`quick_validate.py` passed. An independent three-scenario reasoning forward-test
found no Important gap after sanitized-error guidance was added. This is skill
validation, not a claim that three product journeys were executed.

The previous skill is recoverably backed up outside Git at
`C:\Users\Suyash\AppData\Local\Temp\workflow-ui-production-before-0eed957d75b0458eaba1deda3086352e`.
No secrets or project credentials were added to it. The change was made because
the previous workflow risked overproducing design packages before actual coding.

The updated [Alpha acceptance contract](../workflows/v0.1-alpha-experience/00-start-here/alpha-acceptance-contract-2026-09-07.md)
was uploaded to the existing release-evidence folder and read back successfully:
[Drive acceptance contract](https://drive.google.com/file/d/1O6Rdy9M_ciUKzWkak3oUaNLFemqovp9s/view).
It includes the licensed-video addition and dated supersession of reviewable docs.
It is not a new live-release ledger entry.

The [local QA report](https://drive.google.com/file/d/1bs6YeI5qDo5TItacLCwb0iLWVleDTow1/view)
and [all 32 screenshots plus results JSON](https://drive.google.com/drive/folders/1cHokGeWlomfPSB5l2chlA9SG7sGfXvZG)
are also in Drive. Folder readback matched all 33 expected names and byte sizes;
the exact IDs are preserved in [the artifact register](20260907_ALPHA_DRIVE_ARTIFACTS.json).
No sharing permissions were broadened. These are explicitly local fixture
artifacts and do not replace before/after evidence for a future live deployment.

The persistent app goal remains unfinished/usage-limited; creating a replacement
was refused. The contract and scorecard are the measurable delivery plan, not a
claim that this tool resumed or replaced the app goal. External research/UI chat
pause cannot be confirmed because thread read/control tools are absent here.

This source/evidence set is being saved as a scoped local code checkpoint. No
merge, deployment, new worktree or deletion is claimed by this record. The
unrelated user DOCX, existing UI evidence and stash remain.
Live staging still serves the baseline. Production activation and recovery evidence
remain separate blockers; do not label this foundation candidate final Alpha.
