# Password navigation readiness

The server-rendered password-choice button was enabled before React attached
its click handler. A user could click it while the page was still hydrating and
see no change. The existing hostname external store already supplies an empty
server snapshot and the real browser hostname after hydration; both password
choices now stay disabled during that interval. Loading authentication settings
does not prevent password navigation after hydration.

The regression renders server HTML, attempts the early click, hydrates while
the configuration request remains pending, and verifies the first enabled click
opens the password form without authenticating. It fails against the previous
enabled server markup. The two auth suites passed 15 tests under Node 24.21.0;
Sales Xray TypeScript, targeted ESLint and Prettier checks passed. A separate
read-only review found no blocking issue.

On frozen predecessor `539f440f347aa9a0470f399463c0398f341c5c21`, the complete
application dispatch workflow 36086619292 passed, including the password browser
test. The parallel PR workflow 36086609863 initially failed that browser test
waiting for the password form after its click. Hydration timing is a plausible
explanation, not a proven diagnosis of that CI run. Its one bounded failed-job
retry remains separate evidence. This patch is queued for the next increment;
it does not change the frozen 539f release artifact or establish hosted success.
