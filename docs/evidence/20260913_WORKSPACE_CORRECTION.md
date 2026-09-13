# Admin and Coach workspace correction

Date: 2026-09-13. Base: c06d3a0, Coach shell checkpoint54dd379.

## Accepted changes

- Admin: persistent desktop collapse, mobile drawer, keyboard confinement and focus return, account/sign-out, direct review entry, scoped course counts, publication distribution, real app-control links. Removed disabled future navigation and empty preview metrics. Counts use the existing authorized Studio response; global reference courses are excluded and truncated responses are identified.
- Coach: stable neutral chrome during account checks, persistent sidebar collapse, drawer and account menu keyboard behavior, authenticated sign-out. An editor leave decision happens BEFORE logout; cancellation preserves drafts and active uploads.
- Course editor: drop/choose upload under the selected VIDEO lesson, multiple-file validation, one capability read per admission/check, no remounting the upload through Content/Preview/Publication while unsettled. Existing signed upload, hash, canonical completion and publication rules remain intact. Mobile save actions stay clear of bottom navigation; instructions no longer force a 200px minimum textarea.
- Identity reads: browser and server each start their three independent reads together. All matching person/session/tenant/permission responses are still required before admission. No measured hosted latency claim is made.
- Notifications: returning to a tab hides private state immediately, lets an in-flight read receipt settle, then refreshes. It no longer aborts that write or reads ahead of its commit. A stable new release note describes this correction; the previous note and its receipts are preserved.
- Explicit named test-admin scope: admin@, dipak@ and suyash@authorityclosers.com may administer provider configuration only with existing verified identity, active scoped membership and admin permissions. Exact source/controller checks, external-processing authorization and budget gates remain enforced. No identity/role/verification rows were written.

## Evidence

- Admin mounted/transport/session/editor suite: 199 PASS; full Admin ESLint PASS.
- Coach mounted suite: 45 PASS; Coach ESLint PASS.
- Notification mounted/API suite: 13 PASS; scoped ESLint PASS.
- Python app-update application/HTTP suite: 32 PASS.
- Actual disposable PostgreSQL provider-admin suite: 12 PASS, including all three named emails and denied unverified/learner accounts.
- Actual disposable PostgreSQL authority scope suite: 5 PASS in v02-named-control-scope-02. Initial five failures were before control admission because this new worktree lacked the native test build. Its matching source and binary SHA-256 were verified before reusing the existing local test artifact. No guard or test expectation was weakened.
- Admin, Coach and Learner optimized production builds PASS. Each build retains the normal production authentication gate.
- Browser04: desktop1440 and390/320 phone widths, light/dark, persisted collapse, drawer/Escape/focus, scoped counts, selected-lesson dropzone, multiple-file rejection, dirty-logout cancellation and reachable mobile save action PASS; zero page errors and zero non-GET API requests. Visuals were inspected. Screenshots and result are in v02-workspace-20260913/.
- Browser scope is the supported local development preview with synthetic responses. A local production fixture using process-local DNS interception was rejected by automatic approval review and was NOT run. Supported preview was used instead; this is not hosted session, native-device, performance or media-playback acceptance.

## Read-only hosted diagnosis

Staging: verified admin@authorityclosers.com and rsuyash123@gmail.com among the four requested test emails; no Dipak or suyash@ canonical person. Production: verified Dipak and rsuyash123; no admin@ or suyash@ canonical person. Environments remain separate. rsuyash123's original read receipt is present in each public learner tenant; no receipt existed for the other present named accounts. This does not prove every observed unread badge came from the focus race.

## Remaining release work

People CRM directory, dedicated reviewer admission/invitations, hosted Sales execution/report, named missing-account onboarding, actual long-video transfer/processing/publication, integrated CI and staging/production promotion are separate remaining acceptance items. This source checkpoint does not claim them or the new workspace live. The new notification appears only when its API artifact ships.

The earlier Coach shell note's reliance on beforeunload for sign-out is superseded: the actual editor now receives a cancelable ac:studio-before-leave request before any logout POST.
