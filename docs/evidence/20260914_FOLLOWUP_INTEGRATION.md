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
