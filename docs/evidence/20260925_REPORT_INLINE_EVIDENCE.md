# Report evidence and section navigation

Source: integration branch based on `962e21f24977d10ac4eb046131c39143809bfebc`.

## Problem and change

The report's section tabs still placed source quotations behind disclosures and
opened some findings in a second review dialog. Opening only the evidence child
did not help when its containing review point was hidden.

The report now separates the chosen navigation mode from inline content
presentation. Both reading and tabbed views show the selected content inline;
reading view keeps all sections available in sequence. All 14 overview points,
skill details, next-call coaching, prospect findings and moments retain their
existing content. The transcript remains open in either mode, with search,
speaker filtering and pagination preserved in the tabbed view.

Evidence groups show complete quotations and direct playback controls without a
disclosure. Empty groups remain omitted. Review links focus the destination
within the user's current report view. No second dialog, provider request,
score, speaker attribution or timestamp is introduced by this change.

This implements the visible-evidence and inline-section portion of the accepted
AC Orchestra P3 handoff. It does not establish completion of every P3 design,
the full v0.2 acceptance scope or live report quality.

## Verification

- Node `24.21.0`: 101 tests passed across finding evidence, overview, call studio,
  report modes, transcript, moments, skills, next-call plan and prospect snapshot.
- After independent review, 88 tests passed across acquisition studio and
  Moments, including the real report-mode wrapper. Another 24 tests passed
  across Moments, design tokens and the synthetic report preview.
- TypeScript `tsc --noEmit` passed again after the review corrections.
- ESLint passed with zero warnings.
- Integrated overview regression checks every review point for hidden ancestors,
  immediate playback with the actual evidence object, focus navigation and no
  dialog after switching to the tabbed view.
- Transcript regression verifies the open tabbed presentation still filters and
  selects the actual source segment. Long and mixed-script quotes are preserved.

The broad local run was not green: three tests exceeded their 5-second timeout,
three workers could not read installed dependency files on Windows, and two
assertions needed updating (decimal formatting and an obsolete review-dialog
expectation). The assertions were corrected and the timed-out acquisition
cases passed in the subsequent 88-test run. No timeout or required gate was
weakened. A complete exact-source CI result is still required.

Source review caught the Moments tab inheriting the reading-only display branch.
The correction keeps source filtering, previous/next controls and the full quote
in the tabbed browser; its transcript action opens the existing Transcript tab.
The duplicate review popup is suppressed only in the integrated inline mode.
Standalone legacy readers retain their established fallback behaviour.

The development-only synthetic preview was inspected in the Authority Closers
Chrome profile at its normal desktop viewport, then at 390×844 and 320×844. Skill
quotes and direct listen buttons remained visible in tabbed mode, with no
dialog; selecting a source displayed its exact invented quote and time. Narrow
layouts stacked and wrapped without observed overlap. The viewport override
was reset. This preview contains skills and next-call-plan sections; it does
not establish full-report geometry, real audio playback, print acceptance or
production report quality.

## Release check corrections

The prior integration CI run identified two stale assertions. The token
preservation test now compares numerically identical decimals despite Prettier
adding leading zeroes to alpha/easing values; contrast checks remain active.
The compiled account journey now selects the current `Calls` link within the
`Workspace` navigation instead of the replaced `Saved calls` link. The saved
library heading and the complete account/upload/report/relogin/deletion
journey assertions remain in place. The corrected compiled journey must pass
before release; its previous failure is not treated as a pass.

No staging or production change, external provider execution or additional
credential creation is performed by this patch.
