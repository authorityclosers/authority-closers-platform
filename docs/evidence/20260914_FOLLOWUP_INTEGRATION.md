# Follow-up integration after the 0847 report release

This branch integrates accepted follow-up fixes on application source `0847db5d3ca1ed825b68c226713d0f52d11683b1`. It is not the frozen report release currently being deployed, and this document does not assert a staging or production result for these changes.

## Included behavior

- Admin recording inventory exposes provider/model/request and usage metadata. Usage-based estimates are separate from invoice-confirmed costs; unknown usage remains unknown. Configuration provenance does not claim the serving release matches a pricing evidence release.
- Coach video uploads use bounded 16 MiB resumable requests while retaining the existing 2,000,000,000-byte source ceiling. Completion verifies the complete source hash, capacity admission is serialized, progress is monotonic, and canonical source deletion also removes its bound partial upload.
- The native runtime installer provides checked-in installation and verification for the reviewed systemd units and image bindings.
- Learners can accept the current consent document through a canonical authenticated endpoint. The displayed version is bound to the submitted acceptance; version changes return a conflict and refresh the form. Acceptance requires JSON boolean true, and only the current matching projection can replay a prior audit decision.
- Sales Xray audio admission and its displayed policy use the provider's supported 32 MiB ceiling. Existing 128 MiB approval descriptors remain readable; they do not override the stricter admission ceiling. This is distinct from Coach video uploads.

## Root integration checks

- Combined cost/inventory, resumable upload HTTP/storage and native installer checks: 45 passed before consent and audio-limit integration. Receipt: `D:/AC-authority-closers-release-audit/activation-20260914/followup-combined-f4b259d.xml`.
- Combined Admin inventory and upload frontend checks: 34 passed. Receipt: `D:/AC-authority-closers-release-audit/activation-20260914/followup-combined-f4b259d-ui.xml`.
- Consent routes after the version-binding repair was integrated: 12 passed. Receipt: `D:/AC-authority-closers-release-audit/activation-20260914/followup-consent-c257bbb.xml`.
- Audio-limit lane reports 87 focused Python checks and 27 frontend checks passed, plus type/lint checks. Its descriptor compatibility follow-up passed 87 focused Python checks. These are lane results, not a claim of full combined CI.

Full combined CI, immutable image publication, browser verification and deployment of this follow-up remain pending. Admin provider activation and contextual training clips are separate in-progress work and are not claimed by this integration.

## Admin activation integration under review

Initial activation leaf45cf1d4 is integrated asf069a1f for combined work, not approved for deployment. Independent review found legacy Quote snapshot/fingerprint compatibility and complete-plan C4 budget fan-out defects; the author is correcting both and implementing finite approved alternative model profiles.

The control center now links directly to the recording inventory and provider settings. It distinguishes the latest saved revision from the selected future-plan revision and reads the approved budget ceiling from the API instead of hard-coding a zero spend ceiling. Missing approval remains unavailable, not zero. Three focused UI tests and Admin TypeScript passed; no live result is asserted for these UI changes.

## Subsequent combined verification

- Integrated profile and legacy snapshot corrections from ca12d5b, followed by136fcca: a save-only draft no longer changes the release-approved default, and the full-plan ceiling counts C2 once, C4 fan-out and C5 once. Root checked the actual default and pinned-route call sites. Root focused activation/policy/entitlement/hosted checks passed77 after integration; receipt `D:/AC-authority-closers-release-audit/activation-20260914/activation-caf94aa-root.xml`.
- Integrated peer plan403 UI correction0d6df6: safe approval or allowance copy, sign-in offered for401, saved audio retained and no automatic paid retry. Root combined Sales UI checks passed146 across17 files; receipt `D:/AC-authority-closers-release-audit/activation-20260914/followup-a9c91a1-sales-ui.xml`.
- Actual staging0847 Admin browser inventory showed the newly uploaded retained call while its report remained unavailable. The source checks were labelled Completed. This follow-up now labels that case Report pending / Audio checks complete, reserving the success state for an available report. Two mounted inventory tests and Admin TypeScript passed. This label correction is local, not yet deployed.

Migration0039 backup/restore parity and a fully cost-bounded alternative Gemini profile remain in progress before the combined release freeze. A complete real staging report and production acceptance are still outstanding.

- Migration0039 parity/rehearsal support is now integrated as c36c7b2 across the application restore controller and both foundation backup/restore helpers. Lane validation:1087 passed,2 environment-dependent skips; live PostgreSQL checks remain assigned to combined CI. Root applied the CI formatter to its new regression.
- Gemini3.1 Pro facts / Gemini3.8 Flash coaching preparation and source-backed Pro usage estimates are integrated. The corrected bound uses at most one billing token per input byte plus128 overhead and1400 output tokens:559paise, rounded to a700paise request ceiling. This alternative has not been funded separately or activated. Default Flash remains the staging report-test route.
- Root integration typecheck found an implicit MAX_AUDIO_BYTES re-export and a nullable job-id lookup. The explicit compatibility export and UUID-guarded lookup now pass mypy across286 source files. Admin inventory/profile checks passed16; receipt `D:/AC-authority-closers-release-audit/activation-20260914/cost-3aa4c8c-root.xml`.

## Authenticated learner acquisition integration

The shared AcquisitionStudio now mounts inside the learner shell, with Saved calls and earlier-recording continuity. The API admits the exact learner host only after resolving an existing actor in the public Academy; guest session issuance, claiming and challenge origin remain exclusive to the standalone Sales Xray host.

Root integration caught a contract mismatch before release: learner entry deliberately returns auth_mode=account with null guest challenge fields, but the shared client parser required a guest site key. The parser and mounted learner fixture now use the actual account response; guest responses still require their challenge fields. Root mounted learner journey checks passed6. Earlier combined learner route checks passed31 and TypeScript passed. Backend learner-host and runtime checks are recorded separately; none of these local checks claims hosted availability.

## Trial allowance decision — 14 September 2026

The owner instructed the Build AC conversation analysis task: “dipak said that make the credits to be 60 mins and not 100 mins so make this live on production not just staging”. This supersedes the earlier 100-minute free trial. The shared server quota is now3600 seconds for future admission. Existing reservations, unsettled work and immutable claims still count; an account over the new allowance shows zero remaining. Historical source limits and database bounds stay readable so completed work and exact-source replay remain usable. No account, usage or budget rows were reset. A PostgreSQL regression covers an existing4000-second reservation, claim, replay and settlement under the lower limit; combined CI must execute it. HTTP/runtime focused checks passed10; client20; learnerTypeScript and mypy286sourcefiles passed locally.

## Workflow and PostgreSQL integration review

The standalone app shell, drag/drop selection, processing state copy, Saved calls continuity and report-ready semantics from af95a18 are integrated. Root ran all148 Sales Xray UI tests and8 mounted learner/shell tests successfully. Independent browser preview used synthetic fixtures at390x844, verified one main region, no horizontal overflow, keyboard report-tab navigation and reduced motion. It is not real provider or production evidence.

Actual disposable PostgreSQL acquisition checks exposed seven stale100-minute response expectations and migration0039 constraint-name drift. The migration now uses canonical Alembic names and a positive_config_revision check name below PostgreSQL's identifier limit, matching ORM metadata. No0039 hosted deployment has occurred. The15 behavioral acquisition cases passed in `D:/AC-authority-closers-release-audit/sales-sixty-minute-pg-r2.junit.xml`; after the remaining constraint-name repair, the forward-migration parity test passed in `sales-sixty-minute-pg-r3.junit.xml`. The original failed receipts remain available. Existing4000-second history remains preserved under the60-minute admission limit.
