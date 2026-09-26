# Reading-view history interrupts the previous jump

Opus identified a race during review of the staging navigation increment:
browser toolbar Back can fire while a smooth section jump is unfinished,
without sending pointer or keyboard input to the page. Reading-section links
do not create an in-report return point. The old correction could therefore
survive Back and snap to the abandoned destination after the URL was restored.

Every `popstate` now cancels the previous correction before handling any exact
return-point restoration. The regression drives real component navigation and
browser history with controlled animation frames; before the fix, the URL was
restored but the scroller snapped to 1892 rather than zero. The fixed path must
preserve the restored scroll position without invoking the old correction.

Verification on Node 24.19.0: the new regression failed before the fix with
scroll position 1892; after the fix, all 26 report-mode and shell-preview tests
passed. Sales Xray TypeScript checking, focused ESLint and whitespace checks
passed. No provider requests or database changes were made.

This follow-up is separate from the already built 13ac5242 staging image. It
must pass its own source checks and artifact/browser acceptance before release.
