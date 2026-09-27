# Operations and settings — source-grounded UI contracts

27 September 2026. G11–G14. Read-only source audit at HEAD `e488f952b1aafc10761f304630965d8233a2e39b`. Existing uncommitted work is preserved. The old BRD is excluded; [updated requirements](UPDATED-REQUIREMENTS.md) distinguish owner direction from unresolved policy. Source code proves inspected behaviour only, not staging/production execution.

## Provider configuration and activation

Source: `apps/admin-web/app/sales-xray/provider-controls.tsx:893` distinguishes provider, transport and task implementation; `:1330` saves configuration; `:1450` activates a server-listed saved revision; `:1492` states existing plans retain saved routes. `apps/admin-web/app/sales-xray/analysis-settings-history.tsx:101` describes preserved revisions/new-plan scope. Current settings files have concurrent modifications; do not overwrite them while implementing this handoff.

| State/edge | Required visible result and identity | Recovery and verification |
| --- | --- | --- |
| Catalog read → selected stage/model | Stage, provider, model and capability status; transcription, analysis and writing separate | Loading/forbidden/empty/planned/unsupported are distinct; no active badge from selection alone |
| Draft → local validation | Invalid field remains editable; no server success toast | Preserve draft on validation errors; credential content never enters prompt, logs or local storage |
| Save → saved revision | Expected revision plus exact submitted configuration; server-returned immutable revision | Concurrent save must surface conflict and reread; retain useful draft for deliberate comparison |
| Save → response lost | Outcome unknown until reread/reconciliation | Source `:1352` creates a fresh idempotency key per submit and generic catch `:1402` says “not saved.” This is a source-level uncertainty risk, not a proven duplicate revision or billing defect. Inject post-commit lost response and verify server behaviour before choosing a repair |
| Saved revision → activation eligible | Only server-listed approved target; show new-plan scope | A catalog record or reviewed image is insufficient eligibility |
| Activate → confirmed | Exact expected/current/target revisions and server activation match | `:1481` checks returned activation. Preserve prior request identity for outcome resolution if transport fails |
| Activate → response lost | Explicitly unconfirmed; reread authoritative selection before claiming rollback or unchanged state | Generic catch `:1510` currently asserts prior selection kept. Verify post-commit loss; do not claim definitive failure from a transport error |
| Activation while existing plan runs | Existing plan retains its pinned route; new plan shows current active revision | Test concurrent config changes, reload and old plan completion; no silent provider swap |
| Credential rotate/revoke or BYOK | Owner, stage scope, reference status and affected future work visible | Proposed contract. Define credential service, revocation, egress, billing and in-flight handling before enabling it |

The desired simpler settings UI can group these as **Connections → Stage choices → Test evidence → Active setup**, with advanced revision details collapsed. This is an information-architecture proposal, not a new backend model. Never collapse “configured”, “reachable”, “test completed”, “quality reviewed” and “active” into one green status.

## Testing and quality

`apps/admin-web/app/sales-xray/benchmark-center.tsx:114` explicitly says Admin test runs are unavailable. `:192` lists absent hosted benchmark/probe composition, `:201` identifies a supervised local runner. The displayed ₹0 ceiling is current page behaviour; it does not override existing user authorization or establish a future budget policy.

Proposed hosted test sequence: choose authorized fictional fixture and source revision → identify stage/model/schema → show declared cap and estimate provenance → execute one durable test identity → queued/running/unknown/failed/completed → inspect exact output, timestamps, usage and cost certainty → attach quality review → eligible activation. Configuration-only validation does not execute a provider. Unknown provider costs remain unknown. Cached/reused outputs must be identified rather than described as a fresh run.

Required test fixtures include malformed schema, truncated response, rejected credential, provider 5xx, completed call with lost response, expired approval, changed settings, missing clips and mismatched source. Each failure retains the same canonical run until a distinct fresh run is deliberately permitted. D02 defines which failures may incur cost; this document does not guess that answer.

## Account and profile

Mounted account source: `apps/sales-xray-web/app/account/page.tsx:1` and `apps/sales-xray-web/app/account-view.tsx:357`. Name/phone validation and expected revision exist; accepted update is followed by reread (`:379`, `:386`). Conflict (`:394`) and unknown outcome (`:404`) are distinct. Current editor validates a full phone value; whether it should be mandatory in the redesign is an updated product decision, not inferred from code.

| Edge | UI/data contract | Proof to collect |
| --- | --- | --- |
| Edit → save | Show field validation; preserve draft; submit expected profile revision | Invalid input no write; correct canonical response displayed |
| Save → accepted but reread failed | “Update status unconfirmed”; Check latest before another write | Inject successful PUT/failed GET; no false saved or unsaved claim |
| Two tabs edit | Conflict visible; compare/load latest without silently overwriting | Expected revision failure; user can recover intended field change |
| Session ends during draft | Sign-in and return tied to same account; draft not disclosed to another identity | Same-account re-entry and changed-account isolation |
| Avatar/preferences | Show only supported persistence, with crop/upload/save/remove steps where implemented | Existing component presence is not mount/synchronization proof; source ownership and canonical storage required |

Usage presentation must use the actual allowance projection. Do not split combined used/reserved values or manufacture a percentage when there is no meaningful finite denominator. Unlimited testing is an entitlement label, not evidence of unlimited provider budget. Calls and Account need separate navigation purposes.

## Minute grants, access requests and notifications

`apps/admin-web/app/sales-xray/minute-account-admin.tsx:450` recovers the original administrator's unresolved grant; `:458` blocks a competing grant under another administrator; `:559` refuses dispatch if recovery state cannot be retained. `:583` posts tenant/person-scoped intent with the same key (`:588`) and validates target/amount (`:598`). Clearing a recovery marker can fail after a confirmed ledger write (`:624`); that failure must not negate the confirmed grant.

| Edge | Required state and identity | Verification |
| --- | --- | --- |
| Choose account → review grant | Verified actor, tenant/person, amount and reason; target change clears unrelated draft | Changing target during lookup cannot apply the previous target's balance or intent |
| Review → dispatch | Durable original intent/key before send; submitting blocks duplicate dispatch | Double click and storage-unavailable cases |
| Lost response → original admin reload | Same target/amount/reason/key restored, result unknown, safe reconciliation | Replay must confirm original ledger grant, not mint another |
| Lost response → different admin | Read-only unresolved notice with legitimate resolution path | Do not invent a new key or tell second admin to bypass recovery |
| Confirmed grant → local marker cleanup failure | Ledger success retained; browser reconciliation problem shown separately | Refresh cannot accidentally grant twice |
| Access request resolved → notification | Request decision, grant receipt and notification delivery are distinct records | No “notified” from balance refresh; failed delivery does not reverse a confirmed grant |
| Tokens/unlimited testing | Typed entitlement and scope shown separately from minutes and money | D01 unresolved; no conversion or unrestricted-spend assumption |

Request and notification completion must be verified against their actual service contracts before implementing a polished success screen. This frontend grant inspection does not establish that the entire requested notification or request-management system is absent or present.

## Export and deletion

`apps/sales-xray-web/app/acquisition-studio.tsx:1639` performs a direct credentialed GET of `report.docx`, then triggers a Blob download (`:1658`). Proposed PDF, share links and asynchronous export queues must not be shown as current capabilities. `:1614` deletes the submission using an idempotency key; both `deleting` and `deleted` are accepted (`:1627`) and the component sets `deleted` (`:1634`). That state transition is not proof the derived-data cascade has finished.

| Edge | Design contract | Verification |
| --- | --- | --- |
| Overflow → export | Clear format, exact selected report/source; pending state local to action | Report remains readable; failed download has retry; no unsupported format menu |
| Export permission/session lost | Explain unavailable download without clearing report context incorrectly | Re-auth and source accessibility rechecked; no private payload leaked |
| Delete → confirmation | Consequences, affected item and current policy summary; cancel returns focus | Destructive action separated from main report CTA |
| Delete → accepted/in progress | “Deletion requested/in progress” when service returns deleting | Lost response reconciles same intent; do not show completed erasure yet |
| Delete → complete/partial | Completion tied to authoritative status for each affected artifact | Audio, transcript, report, prospect supports, reviewer copies and prior exports require D04 policy; existing downloaded copies cannot be silently recalled |

## Accessibility, observability and proof

Every dialog restores focus to its origin; errors link to the relevant field; asynchronous outcomes use non-disruptive status announcements; unknown states keep a useful recovery action. Preserve semantic state if reduced motion is enabled. Keyboard, narrow viewport and zoom are independent acceptance checks, not inferred from raster layouts.

Use sanitized operation/revision identifiers in support details. Never show credentials or full private payloads. Acceptance evidence must include expected result, observed result, source/runtime revision and whether provider spend occurred. This research made no provider calls, ran no test suite, and changed no application code.
