# Next design batch — connected, source-aware coverage

27 September 2026. This queue follows the three contract audits. No images were generated in this research follow-through. Existing generation manifests are preserved. This document is a selection and correction overlay, not another generation-complete claim.

## Inventory and selection rule

The prior library contains 204 images: 192 base workflow states, ten corrections and two earlier concepts. Prior visual triage classified 50 as selected **with corrections**, 120 revise and 34 reject. The expansion manifest lists 240 further candidate slots; none are generated. These numbers describe inventory, not application readiness. The 76 expansion refinements should reuse adequate images instead of automatically creating duplicates.

Use [UPDATED-REQUIREMENTS.md](UPDATED-REQUIREMENTS.md) as the current intent baseline. The old BRD must not supply hidden defaults. Use [JOURNEY-CONTRACTS.md](JOURNEY-CONTRACTS.md), [EVIDENCE-DATA-CONTRACTS.md](EVIDENCE-DATA-CONTRACTS.md) and [OPERATIONS-SETTINGS-CONTRACTS.md](OPERATIONS-SETTINGS-CONTRACTS.md) for behaviour and data details.

Each packet below has both desktop and mobile coverage, but not necessarily a new full-screen raster for every transient state. Existing images can be selected only after their exact state is checked. A new materially different layout needs an image; a focus shift, timing or persistence rule additionally needs an interaction contract and working prototype. A picture cannot verify a retry, save or animation.

## Execution order

| Packet | Design sequence and important deltas | Reuse/extend | Required outcome |
| --- | --- | --- | --- |
| P01 — shell and identity | Expanded → collapsed → keyboard/hover → account/workspace change; compact header and correctly owned player across standalone, learner and Admin/reviewer | 01-shell, 13-account, 24-account-preferences | Stable toggle/logo; one main landmark; no double shell/player; meaningful full-width layout; focus and active route survive navigation |
| P02 — sign-in and upload | Selected file → Google/email-code auth → callback/closed popup → workspace/profile prerequisites → consent → bytes uploading → durable save → analysis admission | 01-shell-06, 02-upload, 03-processing, 04-recovery | Same operation and account; clear safe-to-leave boundary; successful valid path avoids redundant plan screens; page reload and account change handled |
| P03 — processing into Calls | Background/re-entry/status unknown → reconcile → complete → same call in library → rename/filter/paginate → open report | 03-processing, 04-recovery, 05-calls, 21-calls-workspace | No new analysis from status failure; honest loaded-page filter/count and estimated duration; no fake global totals |
| P04 — report into evidence and return | Compact overview → specific finding → exact clip → pause/resume/context → transcript → Return → mode switch → browser Back | 06-report, 07-evidence, 10-transcript, 17-report-depth, 19-claim-evidence | Preserve source/run/quote/range and reading origin; reuse current ReportModes; readable multilingual content; deletion/export in discoverable overflow |
| P05 — report depth and visuals | Fourteen-point coverage → incomplete/legacy fallback → skills/source references → available/partial measurements → accessible data table → next-call focus | 08-skills, 09-next-call, 17-report-depth, 18-conversation-visuals, 20-rewatch-practice | Point 13 honestly unavailable; no numeric skill radar from missing data; physical channel not speaker; clear interpretation versus fact |
| P06 — settings and operator recovery | Connection/model-stage configuration → saved revision → unknown save → confirmed read → eligible activation → old-plan/new-plan comparison → test evidence | 14-providers, 16-admin-operations, 25-provider-connections, 26-brain-quality | Configured/tested/active distinct; OpenAI analysis and writing separately evidenced; hosted test controls and BYOK clearly proposed until implemented |
| P07 — account and access | Profile edit/conflict/unconfirmed save → usage → request more → Admin exact account grant → lost response/original-admin recovery → second-admin block → notification outcome | 13-account, 15-admin-users, 24-account-preferences, 27-access-operations | Actual persistence and ledger data; minutes/tokens/cost separate; grant/request/delivery receipts independent |
| P08 — prospects and data lifecycle | Entity directory/profile → complete supplied facts → source support → conflicts/unclassified/reclassification → deliberate association → revoked source/unlink/deletion → review proposal | 11-prospects, 12-prospect-detail, 19-claim-evidence, 22-prospect-intelligence, 23-prospect-journey, 28-help-data-controls | D03–D05 govern persistent capability; no silent fact loss or automatic identity merge; reviewer proposal not adjudication; deletion stages honest |

P01–P04 form the first connected prototype. P05 can develop against validated current fixtures. P06–P08 can have proposed layouts, but must not show unsupported live success. A protected decision affects only its dependent write or claim; it is not an excuse to stop layout and navigation work.

## Exact candidate references and missing deltas

`-desktop` references below each have a corresponding `-mobile` manifest entry. “Base” means a generated reference exists in the original library, not that it passed review. “Expansion” means planned and ungenerated. Contract delta names are work items, not fabricated image IDs.

| Queue ID | Exact reference | Status | New or corrected behaviour to design | Decision dependency |
| --- | --- | --- | --- | --- |
| Q01 | `01-shell-02-compact-desktop` | Base | Stable toggle position, hover/focus reveal, route-aware header, host ownership | None for visual work |
| Q02 | `01-shell-06-session-expired-desktop` | Base | Email-code/popup/callback/changed-account branches and preserved safe return, not one generic expired screen | D07/D11 only where shared identity policy changes |
| Q03 | `02-upload-03-selected-desktop` | Base | File retained through supported in-app auth/navigation; no reload-persistence promise | D11 |
| Q04 | `03-processing-06-background-desktop` | Base | Distinguish bytes transferring, durably saved and admitted; leave/reload/sign-out cancellation | D11 |
| Q05 | `04-recovery-02-checking-status-desktop` | Base | Unknown status reconciles same submission/plan; no fresh-plan shortcut for response loss | D02 only for a genuinely new paid attempt |
| Q06 | `21-calls-workspace-10-stale-list-refresh-desktop` | Expansion | Next-page failure, stale cursor, filtered rename and exact loaded/total scope | D12 for global queries |
| Q07 | `17-report-depth-08-fourteen-section-map-desktop` | Expansion | Every point maps to actual schema; one/two priorities and absent legacy detail stay honest; point13 unavailable | D09/D10 for new content |
| Q08 | `19-claim-evidence-02-surrounding-context-desktop` | Expansion | Exact quote stays pinned while context expands; return to original reading/focus; revision mismatch | None for existing source-bound evidence |
| Q09 | `07-evidence-03-paused-desktop` | Base | Same inline/global player toggles pause/resume; excerpt end behaviour and keyboard | None |
| Q10 | `18-conversation-visuals-09-partial-metrics-desktop` | Expansion | Unknown/gaps/unsupported separate from zero; physical channels labelled; timestamp-base caveat | D12 for additional metrics |
| Q11 | `18-conversation-visuals-10-accessible-table-desktop` | Expansion | Graph focus/selection has equivalent labelled rows and useful source actions | D12 where data itself is proposed |
| Q12 | `20-rewatch-practice-09-practice-save-failure-desktop` | Expansion | Draft, save, unknown result and conflict; source-bound private persistence distinct from report advice | D10 |
| Q13 | `25-provider-connections-05-analysis-writing-review-desktop` | Expansion | Separate stage routes; saved/active revision and pinned existing plan; unknown activation result | D06 for new connection/billing capabilities |
| Q14 | `25-provider-connections-06-test-scope-review-desktop` | Expansion | Fixture/source/model/cap/paid distinction; hosted runner absent today; no inert fake Run button | D02/D06/D09 |
| Q15 | `24-account-preferences-10-save-and-session-error-desktop` | Expansion | Accepted PUT plus failed reread; concurrent revision; draft isolation after identity change | D07 |
| Q16 | `27-access-operations-07-duplicate-submission-desktop` | Expansion | Same-admin reload recovery, other-admin unresolved block, local recovery-store failure | D01 for unit changes |
| Q17 | `27-access-operations-09-notification-delivery-desktop` | Expansion | Separate request/grant/delivery states; failure or unavailable receipt stays explicit | D08 |
| Q18 | `22-prospect-intelligence-02-all-supplied-facts-desktop` | Expansion | Exact numeric range/unit/currency/period, original wording, unclassified facts and source lifecycle | D03–D05 |
| Q19 | `23-prospect-journey-08-association-review-desktop` | Expansion | Person/business/opportunity identity; duplicate/cross-account boundary; explicit call linking | D03–D05 |
| Q20 | `19-claim-evidence-10-feedback-receipt-desktop` | Expansion | Dedicated reviewer invitation/email-link/assignment entry plus expiry/revocation, draft and proposal receipt | D09 for adjudication rules |
| Q21 | `28-help-data-controls-07-export-failed-desktop` | Expansion | Current DOCX download failure/permission loss; preserve report context; no async/PDF capability claim | D12 for more formats/jobs |
| Q22 | `28-help-data-controls-09-deletion-request-review-desktop` | Expansion | Accepted/in-progress/completed/partial distinction and derived-source consequences | D04 |

Review invitation and acceptance, identity/workspace prerequisites, upload sign-out and reload, provider unknown outcomes, and grant recovery need explicit additional named state contracts. They were not adequately covered by the earlier generic frames. Link those states to the corresponding Q row before assigning any new image ID; do not overwrite an unrelated image just to keep a count stable.

## Acceptance record for every packet

Record: requirement IDs; exact input/source revision; actor and entry route; canonical entity and operation IDs; viewport; precondition; trigger; observed pending/success/error/unknown result; recovery; return/focus; keyboard/reduced-motion/zoom checks; selected/revised/rejected image IDs; implementation test or unresolved contract; reviewer and evidence location.

Use one fictional connected fixture through upload → call list → report → clip → transcript → return. Extend it with declared variants (long multilingual text, no improvement, missing audio, conflict, legacy report and source revocation), rather than mixing unrelated facts between screenshots. Use a separate fictional operator fixture for configuration/grants. A snapshot never certifies canonical persistence, provider quality, production activation, actual delivery or paid retry safety.

Stop a packet only when its materially distinct states are covered and the implemented behaviours pass their meaningful checks. More images are useful when they explain missing product behaviour; repeated pretty screens cannot close a data or policy gap.
