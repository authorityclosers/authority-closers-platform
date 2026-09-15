# Sales Xray navigation

Learners can open the integrated `/sales-xray` workspace from the desktop sidebar, the mobile More menu and keyboard search. The public homepage, footer and Free Course page provide an entry without creating enrollment or carrying credentials or identity selectors in the URL.

Admin navigation names the provider page separately and marks it current. Its presentation hint requires the already verified control account, current owner/admin membership and Admin surface permission. The existing provider API independently enforces authorization; showing a link grants no authority and enables no provider execution.

This follow-on is authored in the release owner's isolated integration tree against `0bf1c97950afdefab8f234870f10445c5167008a`, which already includes the Sales Xray routes. No backend, schema, package lock, credentials or deployment configuration is changed. It must not be applied to a release without those routes.

Focused validation covers the existing Arcade admission condition, public and Free Course links, the five-tab mobile layout and menu close behavior, keyboard search, and verified Admin account/role/permission boundaries. Execution receipts and browser acceptance are appended after validation; this initial record is not a pass or deployment claim.

## Executed validation

Supported Node 24: 74 learner tests in five files and 34 Admin tests in three
files passed. Learner/Admin TypeScript and scoped ESLint passed. The initial
root-level ESLint invocation had no root config; corrected app-scoped runs
passed without changing product code. Prettier and diff checks passed.

Final UI-only browser receipt:
`D:/Projects/authority-closers-release-transfer/2026-09-11-recovery/sales-xray-nav-browser-20260912T233136Z/proof.json`.
It exercises the integrated Next route from the public homepage, Free Course,
desktop sidebar, mobile More menu and keyboard palette. Public/course/workspace
screens fit 320/390/1440, mobile More closes on selection, and route URLs contain
no navigation identity. Zero page errors and zero mutations. Browser API reads
are explicitly synthetic fixtures; real authentication and provider acceptance
are not claimed. Screenshots were inspected.

Visual review of the first navigation pass found the new third homepage action
could shrink the primary button until its text clipped at 320 pixels. Its flex
basis now preserves intrinsic width, allowing the third action to wrap. The
final probe additionally checks actual text bounds inside every homepage button.
A rerun hit the local 640 MiB Next development heap limit; that failed receipt
is retained. After stopping the accepted Admin runtime and increasing only this
local process heap to 1280 MiB, the complete final browser run passed.

Independent Luna xhigh review found no additional navigation defect, but did
identify the existing Sales Xray sign-in destination being dropped by learner
auth. The separately owned, strictly allowlisted `/sales-xray` auth continuation
must accompany combined release acceptance. This navigation commit alone does
not claim that authentication return is fixed, or that any provider is enabled.
