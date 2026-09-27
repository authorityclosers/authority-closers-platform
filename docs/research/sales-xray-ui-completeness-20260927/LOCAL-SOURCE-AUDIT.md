# Sales Xray UI completeness — local source audit

Date: 2026-09-27. Decision: what research and interaction contracts are still needed before expanding the design library. Research only; no product changes, provider requests, builds, browser tests or deployment.

## Evidence boundary

- Repository HEAD: `e488f952b1aafc10761f304630965d8233a2e39b` in the existing `sales-xray-v02-core-release-20260925` checkout. References below are repository-relative `path:line` locations.
- Design plans/manifests are untracked working artifacts, not bytes committed at that HEAD. Their hashes are recorded below. Source excerpts were inspected, not executed; this is not a live-behaviour or API-completeness audit.
- Existing uncommitted changes were observed in `apps/admin-web/app/sales-xray/analysis-settings.tsx`, `analysis-settings-contract.ts`, and `analysis-settings.test.tsx`. They were preserved. No conclusion below depends on treating those modified files as committed source.
- Exact controlled-source IDs were checked through `docs/traceability/CONTROLLED_SOURCE_REGISTER.md:7` and `docs/plans/sales-xray-v02/source-intake.json:1`. The latter explicitly marks Brain/report/prospect material `candidate_not_runtime_policy` (Brain 3.0 approval marker at line 35). Controlled Drive document bodies were **not freshly fetched in this bounded read-only lane**. Proposed retention, provider activation, identity, access and assessment decisions therefore remain unresolved here; this audit cannot approve them.
- This audit follows AC Orchestra and AC Evidence Research. The parent owns any cloud research, controlled-source retrieval and final synthesis. No private call contents or credentials were copied into this handoff.

## Finding

The first 192 images plus 240 planned images are not an application completeness criterion. The expansion already covers report depth, charts, evidence, calls, prospects, preferences, provider setup, Brain operations and privacy. Repeating those subjects as new screen names would add little. The missing work is primarily **whole journeys across roles, asynchronous state transitions, evidence-to-data mappings and capability decisions**.

The base review itself records 40 originals selected with corrections, 118 needing revision and 34 rejected; none is unconditionally accepted (`docs/design/sales-xray-v02-refresh-20260926/EXPANSION-PLAN.md:7`). Repairing shared shell/recovery/report contradictions has higher value than rendering all 240 pending images indiscriminately.

Priority means: **P0** resolve before enabling the affected capability; **P1** complete before the relevant release journey; **P2** improve after its essential journey is reliable. It does not block the entire product.

### What “gap” means here

| Findings | Classification | What may be concluded |
| --- | --- | --- |
| 1, 3, 4, 13, 15 | Existing source behaviour omitted or compressed in named design coverage | Design its actual transitions and verify them; do not rebuild the capability merely because its image is missing. |
| 2, 6, 8, 12 | Existing source behaviour needs an explicit contract/adapter/ownership map or interaction proof | Clarify source versions, authority, route mounting and return/recovery behaviour. Missing proof is not proof the code is broken. |
| 5 | Existing cursor list and loaded-item filters; proposed richer querying | Separate supported list behaviour from future server-wide search, sort and aggregate semantics. |
| 7 | Existing physical measurement view; proposed additional conversation metrics | Do not claim proposed speaker/semantic metrics are supplied by the inspected Atlas projection. A broader backend inventory is still needed. |
| 9, 10 | Proposed persistent product capability in the design documents | No mounted prospect directory or saved coaching mutation was identified in the inspected standalone routes/components. This is not a claim that no experiment or backend model exists elsewhere. |
| 11 | Existing provider configuration; benchmark UI explicitly describes absent hosted test endpoints | Treat the UI statement as pinned composition evidence needing backend confirmation, not a fresh runtime probe. BYOK remains proposed. |
| 14 | Existing DOCX export and source deletion; proposed broader formats/background jobs | Use current semantics first; investigate extra services separately. |

This is a research inventory of missing design/contract evidence, **not fifteen verified software defects**.

## Fifteen concrete gaps

### 1. Reviewer invitation and access lifecycle — P1, existing source seam omitted from named design coverage

Admin navigation already mounts a Reviewer queue (`apps/admin-web/app/sales-xray/sales-xray-navigation.tsx:15`); invitations have validation, issue and revoke states (`apps/admin-web/app/sales-xray/review/review-invitation-panel.tsx:79`, `:325`). Acceptance routes into an exact assigned review (`apps/learner-web/app/sales-xray/review/review-invitation-acceptance.tsx:70`). Neither image matrix names this journey.

Add a role-spanning storyboard: admin selects exact run/revision and lens → invite → invited user signs in → correct Academy/account → acceptance → assignment; include expired/revoked invitation, wrong identity, duplicate acceptance and permission loss. Distinguish a created invitation from delivered email. This is review access, not general team sharing.

### 2. Human correction submission versus adjudication — P1, partly covered by generic quality review

The source validates saved feedback against the submitted idempotency key, lens, confidence, text, evidence and proposed correction (`apps/learner-web/app/sales-xray/review/review-assignment-api.ts:340`, `:365`). Its 409 preserves the draft, while 403 can mean expired/revoked access (`:383`). The design has challenge/feedback receipts and a quality-review image but does not specify the reviewer-to-final-decision transition.

Research the controlled capability boundary between learner feedback, technical/contextual reviewer proposal and Dipak adjudication. Design submit-in-flight, committed-but-response-lost, history, conflicting draft and revoked-while-editing. A saved proposal must not relabel the report as adjudicated or overwrite its source version.

### 3. Authentication is more than a session-expired frame — P1, mounted flows need separate states

The sign-in component has email-code resend timing, consent-version changes, Google popup completion and an explicit timeout fallback (`apps/sales-xray-web/app/account-auth.tsx:47`, `:209`, `:529`, `:883`, `:1051`). The callback is a separate page (`apps/sales-xray-web/app/auth/complete/auth-complete-client.tsx:18`). A shell session-expired state does not cover this.

Add Google popup pending/cancelled/closed, callback-without-opener, code sent/invalid/expired/resend, changed Terms, existing-account/password recovery and safe return to the selected file or call. Browser security errors require an honest handoff, not an invented automatic bypass. Verify account continuity without exposing account-existence information.

### 4. Upload transport continuity before durable acceptance — P1, generic background processing is insufficient

The upload store survives client navigation but a full reload ends transport (`apps/sales-xray-web/app/hooks/upload-session.tsx:104`). It has explicit unresolved-upload sign-out confirmation and clears retained file/controller only after confirmed logout (`:185`, `:206`). A single processing-background image can incorrectly suggest bytes always continue after closing the page.

Add navigation during byte upload, native leave-page prompt, cancelled leave, account change during upload, sign-out cancelled/confirmed, interrupted upload and status reconciliation. Keep the three milestones distinct: local file selected, upload durably saved, analysis durably admitted. Only the latter states can promise the corresponding safe-to-leave behaviour.

### 5. Calls search/filter/count contract — P1, expansion promises deeper capability than the mounted list

The existing list is cursor-paginated and its filter explicitly covers only loaded calls (`apps/sales-xray-web/app/calls-library.tsx:178`, `:882`). Its displayed duration is an admission estimate, not measured source length (`:38`, `:49`). The expansion proposes search, advanced filters, density and duration visuals.

Decide which queries are server-backed, their indexed fields/sort order, and whether counts cover loaded or total results. Add next-page failure, stale cursor, empty-loaded-page with more results, renamed item under a filter and concurrent refresh. Keep approximate duration labelled until the projection supplies a measured field; do not build precise total-talk-time dashboards from estimates.

### 6. Fourteen report sections need an explicit adapter map — P1, naming alone cannot establish completeness

The detailed presentation includes named entries through final verdict 14 (`apps/sales-xray-web/app/dipak-overview.tsx:398`). A separate legacy report metadata parser accepts exactly nine numbered sections (`apps/sales-xray-web/app/report-contract.ts:438`), while projected reports can omit that metadata (`:628`). This is not proof of a bug: it is proof of multiple contracts.

Create a schema/revision → presentation-section crosswalk: source field, evidence requirements, empty/unsupported treatment and allowed actions for each section. Test legacy, projected, incomplete and language variants. Prevent a visually complete fourteen-card screen from claiming content the current report did not actually return.

### 7. Graph contracts: channel is not speaker; measurement is not sales interpretation — P0 for misleading metrics

The mounted measurement contract currently exposes source-bound physical channels with dBFS/F0 series (`apps/sales-xray-web/app/measurement-contract.ts:1`). It pins a decoded-audio clock and explicitly says container/video sync is uncertified (`:87`); SignalLab runtime output is unavailable (`:112`). The expansion proposes talk time, questions, objections, pauses and turn taking.

For every graph, specify the actual upstream artifact, clock/alignment, denominator, missing coverage, overlap handling, definition and drill-down. Research which values can be deterministic from transcript/timing and which need a new approved analysis schema. Do not turn physical-channel pitch/level into seller skill, emotion or voice identity. F02 is a synthetic illustration, not runtime measurement evidence.

### 8. Reading navigation across modes and origins — P1, state contract exists but needs source-specific sequence design

Tabbed sections preserve mounted panels and use `replaceState` so browser Back remains the prior page (`apps/sales-xray-web/app/report-explorer.tsx:35`, `:70`). The design requires evidence-return bookmarks and reading-location restoration (`docs/design/sales-xray-v02-refresh-20260926/INTERACTION-CONTRACTS.md:60`, `:105`). These are two different navigation mechanisms.

Specify a small navigation table for Calls → report → section → evidence → transcript → Return, including browser Back/Forward, reading/tabbed mode switch, new deep link, late report load and changed/deleted source. Test focus and semantic anchor restoration, not only scroll animation. An explicit Return to reading action must not be silently replaced by browser Back.

### 9. Persistent prospects need identity, field provenance and deletion decisions — P0 for live writes

The design correctly labels Prospects proposed and leaves retention/shared visibility unresolved (`docs/design/sales-xray-v02-refresh-20260926/DEVELOPMENT-PLAN.md:131`, `:139`). The current shell has only analyse/calls/account destinations (`apps/sales-xray-web/app/shell/lightbox-shell.tsx:34`), while the source delta grants access to exact source/run/reviewer lanes (`docs/contracts/SALES_XRAY_SOURCE_INVENTORY_AND_DELTA.md:55`).

Before more CRM-like screen detail, resolve Person/Business/Opportunity identity, membership of facts, owner/tenant scope, deliberate call linking, duplicate review, conflicting supplied facts, independent corroboration and unlink/delete/revocation effects. Include an unclassified supplied-fact path so fixed cards do not drop relevant data. More fields are not authority to infer sensitive traits, enrich externally or retain everything indefinitely.

### 10. Practice, bookmarks and multi-call progress need a persistence contract — P1, proposed feature rather than a mounted saved workflow

The current next-call view reads report findings and local selection state (`apps/sales-xray-web/app/next-call-plan.tsx:29`, `:36`). The plan itself marks persistent learner focus/reflection proposed (`docs/design/sales-xray-v02-refresh-20260926/DEVELOPMENT-PLAN.md:139`; `INTERACTION-CONTRACTS.md:212`). The expansion adds bookmarks, notes, practice and multi-call context.

Research the minimum private learner entity: source revision, selected focus, author, current/superseded choice, draft/save/conflict, voluntary completion and removal. Keep it separate from prospect facts. Cross-call comparison needs deliberate identity/source association and comparable evidence, not an autonomous improvement score or fabricated streak.

### 11. Provider configuration, testing and activation are distinct journeys — P0 for paid execution

Provider catalog entries already distinguish planned from implemented (`apps/admin-web/app/sales-xray/provider-controls.tsx:497`, `:593`). The mounted benchmark page explicitly states test-run/probe HTTP composition is absent (`apps/admin-web/app/sales-xray/benchmark-center.tsx:114`, `:193`). Settings history says changes apply to new plans only (`apps/admin-web/app/sales-xray/analysis-settings-history.tsx:101`).

Expand the capability matrix before drawing active-provider success: credential reference vs masked storage, stage capability C2/C4/C5, model/schema support, zero-cost check vs paid fictional trial, quality review, approval cap, expiry and activation. Include pending request under old settings when a new revision is saved. OpenAI selected for writing is not evidence of analysis capability. BYOK and any new test runner remain proposed until their credential, billing, egress and endpoint contracts exist.

### 12. Account edits and avatar are not generic preferences saves — P1, existing domain-specific failure states

The mounted account page uses `AccountView` (`apps/sales-xray-web/app/account/page.tsx:1`). That editor uses expected profile revision, re-reads after PUT, distinguishes accepted-but-unconfirmed from conflict, and validates name/phone (`apps/sales-xray-web/app/account-view.tsx:357`, `:379`, `:394`). A separate avatar/profile component exists; its presence does not prove it is mounted by this account route.

Map the real profile surface and shared learner-account authority. Add concurrent profile edits, successful write/failed reread, expired session with draft, avatar select/crop/upload/save/remove and failure states only for the supported contract. Do not promise cross-app photo synchronization or persistent appearance/audio preferences without identifying their canonical storage and propagation.

### 13. Admin minute grants across administrators and reload — P1, hidden but essential microflow

The minute-admin code preserves unresolved grant identity and distinguishes recovery by the original versus another administrator (`apps/admin-web/app/sales-xray/minute-account-admin.tsx:450`, `:458`). It refuses a new grant when safe recovery state cannot be retained (`:559`). The expansion covers duplicate submission and concurrent balances, but not this cross-admin recovery boundary.

Add original administrator resumes after reload, second administrator encounters unresolved operation, local storage unavailable, target account changes mid-review and session expires after submit. Keep grant confirmation separate from request resolution and notification delivery. The image must never offer a new key as a shortcut around uncertainty or show delivered notification from balance change alone.

### 14. Export and deletion require current-capability versus proposed-state separation — P1

The current export path downloads a DOCX response as a Blob (`apps/sales-xray-web/app/acquisition-studio.tsx:1652`, `:1662`). Deletion accepts distinct `deleting`/`deleted` source states (`:1615`, `:1627`). The expansion proposes format options, pending export artifacts and privacy controls; these are not proof of an existing asynchronous export service.

Design the actual DOCX path first: pending, permission loss, failed response, retry and unchanged report access. Separately mark PDF/other formats or background artifact jobs proposed. For deletion, distinguish request acknowledged, processing, completed and partial/uncertain cascade; clarify report, transcript, source audio, derived prospect facts, review evidence and existing downloads. Place actions in overflow, but keep discoverability and honest consequences.

### 15. Standalone, learner-embedded and earlier-recording parity — P1, app-shell reuse has multiple entry contexts

Learner Sales Xray mounts within `LearnerShell`, with its own three-link subnavigation and embedded `StandaloneStudio` (`apps/learner-web/app/sales-xray/sales-xray-shell.tsx:16`, `:45`). Earlier recordings use `CallStudio`, not the acquisition page (`apps/learner-web/app/sales-xray/recordings/page.tsx:1`). The library's learner-inspired standalone shell does not automatically cover either route.

Create an entry-point matrix with standalone, learner-embedded, legacy recording, exact report link, reviewer and Admin contexts. Specify which shell owns header/navigation/player, auth return path and main landmark. Add no-double-navigation, no-double-player, correct back destination, old report compatibility and guest/private route states. Validate laptop, narrow mobile, zoom, keyboard and reduced motion across these entries rather than only one visually preferred route.

## Smallest useful next research batch

1. **Journey audit:** invitations/review, auth, pre-admission upload and embedded/legacy navigation. Output a transition table with source/API identity and role on every edge; reuse existing screen references where they fit.
2. **Evidence/data audit:** report revision-to-fourteen-section mapping, chart artifact definitions, list/query semantics and private coaching/prospect boundaries. Output field-level contracts and explicit unknowns, not invented metrics.
3. **Operations audit:** provider configuration versus paid trial/activation, profile/grant concurrency, export/deletion lifecycle. Output supported/proposed/blocked capability rows and the minimum additional states.

The next image batch should be selected **after** these tables, using one repaired reusable shell and a connected desktop-to-mobile sequence. Do not assign another arbitrary hundred-image quota. Definition of covered: role + entry + precondition + event + canonical data + permission + pending/error/recovery + exit/return + accessibility + evidence owner. A screenshot count covers none of those by itself.

## Verification and limits

- Text-only inspection, manifest ID comparison and Git status check; no automated test suite run because this handoff changes no application code.
- No claim that a source seam is reachable/healthy in staging or production. No source absence claim beyond the listed frontend route/component scope; backend composition and current runtime require separate verification.
- Controlled documents were indexed, not refetched; line citations refer to mounted local source and local implementation interpretations. Business-policy proposals require exact controlled-source reconciliation before activation.
- No generated images were re-reviewed in this lane. The prior review counts above are attributed to the existing expansion document, not independently established here.
- Parent-owned final synthesis should attach any fresh controlled-source receipts and cloud-research links separately. This file is the bounded local audit only.

## Inspected-file fingerprints

SHA-256 inventory follows. Source files are clean relative to the pinned HEAD unless explicitly described above; design artifacts are working-copy inputs. The modified Admin settings file was inspected only as an observation and is not used as committed evidence.

| File | SHA-256 |
| --- | --- |
| `AGENTS.md` | `a8e85be2fa4043d02d80c0cf731fc3c9adb1354a3830ca45f24a30f3c80c56d0` |
| `apps/sales-xray-web/AGENTS.md` | `63f2c50380ed6303237cce215ce27af1d620d094c215e28d1b1538a3c070e3bb` |
| `docs/traceability/CONTROLLED_SOURCE_REGISTER.md` | `bfddcd073959581d8e0661d7d3daf70395472864a50f7f5d947df57d092bd2ca` |
| `docs/plans/sales-xray-v02/source-intake.json` | `034494a3a8beefbf53dba457d9d5edf802d8187307ff19b0070273f36e6af271` |
| `docs/contracts/SALES_XRAY_SOURCE_INVENTORY_AND_DELTA.md` | `41dff83f07e41d25e9c3b0555b00217f2143d36f532baf6f452bf2be572ccbe8` |
| `docs/contracts/PROVISIONAL_SOURCE_GAPS.md` | `86502029b34b3a13d2f1772233f16f89e2127053adfc39ef8045a1c7cd043df5` |
| `docs/contracts/onboarding-profile-source-manifest.json` | `c44ca6bbb20243410ab573f80bd3924c3cd45cd34446d05af1c9e17b1f29b890` |
| `docs/design/sales-xray-v02-refresh-20260926/DEVELOPMENT-PLAN.md` | `56090f78fcf3db08f58f86118c49ae961aa182854d6a997297e65ebce51bc32e` |
| `docs/design/sales-xray-v02-refresh-20260926/INTERACTION-CONTRACTS.md` | `263fead800a54df23c7b16e64101dde46b1d2473e0a0c37c9ff6657d920cc72e` |
| `docs/design/sales-xray-v02-refresh-20260926/EXPANSION-PLAN.md` | `a1e71eaae8cf99bbed652e8db1e30852cfcb37a48d14bcd4968572cc94e47862` |
| `docs/design/sales-xray-v02-refresh-20260926/state-manifest.json` | `0de2b56846c77cfc3f50ff8bd76482a594d68a7a67fab31224a916b4d75b52b1` |
| `docs/design/sales-xray-v02-refresh-20260926/expansion-manifest.json` | `e4dfdeb326e3b413f31207747652afd1ec1c5958d26480cba863acc94a41f6e0` |
| `apps/sales-xray-web/app/page.tsx` | `2928884196d71b593a311aacfeb78a7dacf8bdf2f28a24857e79fd2cf4103b7f` |
| `apps/sales-xray-web/app/shell/lightbox-shell.tsx` | `66ad3a5bf273ff3c76d2a018121ae5a6fb4082f41f8dd45b6620d79b6a85cf87` |
| `apps/sales-xray-web/app/account-auth.tsx` | `1c9c6126ede89004a435443158e7d152a57e1754050a070538e795c1c9ba3ce7` |
| `apps/sales-xray-web/app/auth/complete/auth-complete-client.tsx` | `c1e450afcb62996a3604bdf12de1a859fc7c116b3da4c1c47ee0ff1f23af4b36` |
| `apps/sales-xray-web/app/hooks/upload-session.tsx` | `bf3368528e594b9a4474336707225d9aa1e2d40c85bed90bd93a4baa723b9444` |
| `apps/sales-xray-web/app/calls-library.tsx` | `c71a8050ca70f0751cd5ac19f6e19f72e764f42656cab612f82c3a5783055a77` |
| `apps/sales-xray-web/app/report-contract.ts` | `240ef7c979170244c9a89ebd797d9f83f1e7b06f6d886409e0f6a66f8b61d822` |
| `apps/sales-xray-web/app/dipak-overview.tsx` | `92158b49d30cbe1bc10b00f2ca757f110627a42eda14938776ed7d7e46971bb3` |
| `apps/sales-xray-web/app/report-explorer.tsx` | `8243b2b641b316c9a6e526610251dfa4ced7569858fd298c21eaccdc13eba4b0` |
| `apps/sales-xray-web/app/report-header.tsx` | `1b1bd5dd3c0c15bb667641eebfa5638cb34a25112854c3e35a2628adca2f52a4` |
| `apps/sales-xray-web/app/measurement-contract.ts` | `f4427ff678c7625e937cecb1402e4a732c7db67d40b17ff2b35fb75618f326c3` |
| `apps/sales-xray-web/app/next-call-plan.tsx` | `36f5c919734213af5f72c7cea5165ecc63022174e1e578648ba31c7775e4ce13` |
| `apps/sales-xray-web/app/account/page.tsx` | `1a2f8ac33a091d0f2f9235914bda7d628ce552ed88dcb0219c9df9ea750f6909` |
| `apps/sales-xray-web/app/account-view.tsx` | `a021c79706259b5382f4206ce2ac312bd7e40ac84a5fddf3ab15ef80c839faed` |
| `apps/sales-xray-web/app/account-profile.tsx` | `5d314c3df845cde4e34f2c46f601dcd5539f409cfc98c947d70f90054648f9dd` |
| `apps/sales-xray-web/app/profile-menu.tsx` | `39117e52cd8bce8a57283fed4991376eae3f44ea605e67dd239d5d37d28ac0af` |
| `apps/sales-xray-web/app/acquisition-studio.tsx` | `fb70df3c81b217e1d6326d8a7cdcc30d5fdaedfb96fc4a10e4f2dcc5d707fa48` |
| `apps/sales-xray-web/app/call-studio.tsx` | `1be640f7f87cd8b501f9afbe6f0dbe375d4b36790c713456b3d5538084ea6758` |
| `apps/sales-xray-web/app/call-audio-dock.tsx` | `b9ad5a915b4e887aa58593abd411694c92411f59a4f049d6f149a15502aaa565` |
| `apps/admin-web/app/sales-xray/sales-xray-navigation.tsx` | `1c94f5070fd11c378d346ea24c1650bf9296133d6599c82f7d6f573f66c5d960` |
| `apps/admin-web/app/sales-xray/provider-controls.tsx` | `ab926920917ad40a859596a8288c1cab1c51d7d2ca01327e1a67e8ae460ecdf0` |
| `apps/admin-web/app/sales-xray/benchmark-center.tsx` | `2ff8f2022376c4e3594b837ca7a858e21e2d20022f28d0ca8db09f9860c6ebef` |
| `apps/admin-web/app/sales-xray/analysis-settings-history.tsx` | `c05aa46ebdf5f5418e9bef190e4ddd3afc9adef9a9aecc0f2cf655c17173c523` |
| `apps/admin-web/app/sales-xray/analysis-settings.tsx` | `f12c97498763ac8785bb7a6477a4d12c9a7f4522a67070b05eacb1d3e57171c3` |
| `apps/admin-web/app/sales-xray/minute-account-admin.tsx` | `b18de0d0ba42e4d455f273d12c37522f7dd61debe1fe68e09e308df8f096671b` |
| `apps/admin-web/app/sales-xray/review/review-workspace.tsx` | `f2228afc8281331e3c4e90aae788c4b9efdd0b10eab424d1765d06af3292954a` |
| `apps/admin-web/app/sales-xray/review/review-invitation-panel.tsx` | `3bdc72872b5142010d416a7442515b9c6f3143061f282d3bc9a502ee52dc99db` |
| `apps/learner-web/app/sales-xray/review/review-invitation-acceptance.tsx` | `b66c6260eaef77f5843c7773f0bfbce9db699a24476b095da6159424d5566cc6` |
| `apps/learner-web/app/sales-xray/review/review-assignment-adapter.tsx` | `5d201e491f08a5c2e8dc5965a1ba270fd17667d2fe53c0b47d1db7c8dfc0f1f1` |
| `apps/learner-web/app/sales-xray/review/review-assignment-api.ts` | `8414b1bd276f01ec5cc0b937a9c788db36dbf62e52df4b44dbb5d2d0c51182ec` |
| `apps/learner-web/app/sales-xray/sales-xray-shell.tsx` | `fa7fad6ff7ffa43e910c5a6f83f70df50e42258d5d6602328f8656da966c17c7` |
| `apps/learner-web/app/sales-xray/recordings/page.tsx` | `766d31a9c901fbaf4e030d9200c5e3fb8eec12365865c09e7f13e68515a13a01` |
