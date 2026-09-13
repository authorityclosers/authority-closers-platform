# Authority Closers v0.2 consolidation

Status: planned release, not yet complete or tagged. Owner direction recorded on
2026-09-13: finish the existing product work, bring it together on `main`, deploy the
accepted release to staging and production, then prune merged worktrees so subsequent
work starts from the consolidated main branch.

## Previous deployed version

The last independently verified common staging/production baseline is commit
`41d3c5726a1b5d217259c034bf058d9107135b1f`. It includes the core learner interface,
normal authentication and email recovery, and the Coach course editor. This is an
exact deployed commit reference; it does not invent a historical version tag.

At that baseline, production Arcade is disabled, the production free-course draft
is not globally published, and the full licensed 4K test video has no completed
Studio upload/publication. Sales Xray has an entry page but hosted upload/report
execution and the requested in-app reviewer workflow are not complete. Those
limitations remain recorded even after a newer version supersedes them.

## v0.2 completion scope

| Area | Required outcome |
| --- | --- |
| Source consolidation | Inventory every AC worktree and branch, reconcile unique work and dirty files, integrate the accepted current feature implementations and fixes, and leave the final reviewed source on `main`. |
| Learner and community | Latest Academy UI, normal signup/sign-in/recovery, working profile-picture upload, Arcade, usernames, opt-in profiles/friends/leaderboards and English/Hinglish/Marlish practice. |
| Coach and course | Dipak can edit/create course content. The intended free course is published through canonical services with the attributed large 4K testing video in Module 1, and learner playback works on mobile. |
| Sales Xray | Authenticated upload/history/loading/report inside the Academy shell, source-linked audio clips and feedback, real measured/human-reviewed visual results, and an explicit initial 100-minute call-audio allowance charged once. |
| Review and calibration | The supplied call is exercised under Dipak's actual learner account. Admin operators manage assignments and email invitations; authorized reviewers submit multiple attributable sales/technical/UX reviews. Database save/reload and later authorized review export work. Original reports and review history remain preserved. |
| Benchmarking | The bounded benchmark plan, clip coverage, model/adapter readiness and cost assumptions are documented. No benchmark result is claimed without execution; a budget estimate does not purchase credits or authorize paid inference. |
| Release operations | Immutable artifact, migrations, recovery, health, protected routes, media, email and browser acceptance verified in both environments; exact source/image/configuration and rollback evidence recorded. |
| Documentation and cleanup | Release notes explain changes from the prior deployed baseline and material limitations. Final version/tag points at accepted `main`. Only then remove worktrees/branches whose work is merged or explicitly preserved elsewhere. |

The active core candidate at this record is
`69db2257b2671baa3aefc7902e69078f381a649d`. Its targeted regression passed and
replacement CI run `34746866804` is in progress. It is an intermediate candidate,
not the final v0.2 release declaration. Sales hosted/reviewer work and the newly
reported avatar-storage failure remain active owned work.

The final consolidation branch is `codex/v0.2-consolidation-20260913`, based on
that candidate with `origin/main` (`691cf1b08f2722d304c19a46ffa5481ae694c872`)
merged. At `048b3be` it also contains the reviewed native supervision recipe,
corrected call-minute accounting, distinct operations controller checks and the
bounded benchmark plan. Its focused test run passed 519 tests; 17 native/POSIX
cases were skipped on Windows and are not counted as execution evidence.

The initial external worktree audit resolved all 63 snapshot paths, found 15
dirty worktrees and 1,198 untracked entries. Later active worktrees are tracked
separately. Seventeen branches require content review because their patch history
is not fully equivalent; this is not evidence that every difference should be
merged. The detailed audit is retained outside Git under
`D:/AC-authority-closers-release-audit/`.

The profile upload failure was reproduced through the actual production browser
under Dipak's learner session: a valid PNG could be selected and previewed, but
`POST /v1/profile/avatar` returned HTTP 503 `media_storage_unavailable` before
upload intent issuance. The existing avatar remained unchanged. This is an open
runtime storage defect, independent of the resolved Chrome file-access setting.

## Merge and cleanup evidence

For each worktree, record its absolute path, branch, exact commit, dirty/untracked
state, remaining unique changes, accepted integration commit or superseding result,
and any retained local artifacts/runtime dependency. A cherry-picked patch may be
integrated without its original commit being an ancestor; verify patch/content
equivalence before deciding it is redundant.

Do not discard unmerged work, local credentials, test media, private receipts,
runtime environments or active-agent checkouts. Move necessary non-source artifacts
to an appropriate external location before cleanup, and verify the final resolved
paths of any removal. Cleanup is subsequent work; no worktree removal is performed
by this plan.

Official autonomous scoring and external processing of unapproved real recordings
remain subject to their capability gates. These do not prevent independent ready
features from being released, and an incomplete capability is reported honestly.
