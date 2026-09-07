# Local bridge cookie browser selection — 2026-09-07

Status: bounded test-infrastructure change; explicit Chrome browser proof passed.
Scope: `tests/e2e/test_local_bridge_cookie_isolation.py` only, plus this evidence.
No learner/admin source, cookie policy, server deployment or production data was changed.

## Observations and diagnosis limits

The consolidation validation reported this test failing, but its original
traceback was not retained. The failure could not be reproduced by the focused
command with the same bundled Node 24 PATH prefix. Both focused default runs
instead skipped because the expected Playwright Chromium executable is absent:
`chromium-1208/chrome-win64/chrome.exe`. The project environment has Playwright
`1.58.0`; installed Google Chrome reports `152.0.7977.82`.

A separate diagnostic ran the unchanged two-host cookie sequence in installed
Chrome and both original assertions passed. This does not establish the cause of
the earlier full-suite failure.

The test did contain a browser-selection mismatch: it checked the full Chromium
executable but launched unspecified headless Chromium, which uses a separately
installed headless shell. Playwright documents that distinction and its explicit
`chromium`, `chrome` and `msedge` channels:
[Playwright browser guidance](https://playwright.dev/python/docs/browsers).

## Bounded change

- Default launch explicitly selects `channel="chromium"`, aligning the launch with
  the executable already checked by the test.
- `AC_BRIDGE_COOKIE_BROWSER_CHANNEL` optionally selects a declared installed
  channel, such as `chrome` or `msedge`. Explicit-channel launch failures remain
  failures; no exception-to-skip catch was added.
- The existing default skip for an absent Playwright Chromium binary is retained.
- Both cookie assertions are unchanged: the learner request must contain only
  its learner cookie and the admin request only its admin cookie. Hostnames,
  `__Host-` names, Secure/HttpOnly/SameSite/Path attributes and shared browser
  context are unchanged. No insecure browser flags were introduced.

## Verification

With the bundled Node directory first on the process PATH:

```powershell
$env:AC_BRIDGE_COOKIE_BROWSER_CHANNEL = 'chrome'
uv run pytest tests/e2e/test_local_bridge_cookie_isolation.py -x -q
```

Observed: **1 passed** in 36.31 seconds using Chrome `152.0.7977.82`.
This duration is test execution time, not an application performance measurement.

Without the override: **1 skipped**, with the explicit reason that Playwright
Chromium is not installed. This result is not counted as browser isolation proof.

`uv run ruff check`, `uv run ruff format --check`, and `git diff --check` passed for
the changed test. The broader validation must be rerun by the consolidation owner
with the explicit Chrome channel if this test is to execute in this environment.
No full application build, process termination, commit or deployment was performed
for this diagnostic.

## Superseding full-collection diagnosis and fix — later on 2026-09-07

The subsequently retained full-suite log
`.tmp/alpha-python-validation-20260907.log` establishes a separate failure before
browser launch: `NotImplementedError` from
`asyncio.base_events._make_subprocess_transport`. This supersedes the earlier
diagnosis limit; explicit browser selection alone does not fix the full-suite
failure.

Exact cause: `tests/database/test_operations_postgresql.py` installs
`WindowsSelectorEventLoopPolicy` at module import on Windows. Full pytest
collection imports that module even when its database-dependent tests are
skipped or deselected. Installed Playwright's synchronous context creates its
event loop with `asyncio.new_event_loop()` and starts a subprocess driver. The
Windows selector loop lacks the required subprocess transport; the installed
Python 3.12 Proactor implementation supports it.

The failure was independently reproduced before this fix while collecting the
whole suite and executing only the cookie test, with the explicit Chrome
override: **1 failed, 1,342 deselected** in 9.90 seconds. Thus the earlier focused
file-only pass did not exercise the collection-time policy interaction.

The bounded test-only correction adds `_playwright_subprocess_policy()`. On
Windows it installs `WindowsProactorEventLoopPolicy` immediately around the
Playwright context and restores the exact preceding policy object in `finally`,
after Playwright cleanup. On other platforms it does not change the policy.
There is no production runtime, global fixture, database-test policy, or cookie
behavior change. No exception is converted into a skip.

Two parameterized regression cases install the collection-like selector policy,
verify the temporary policy creates a real Proactor event loop, and verify the
original policy object is restored after normal completion and after an injected
failure. Their own setup also restores its preceding policy in `finally`.

Verification with all test modules collected:

```powershell
$env:AC_BRIDGE_COOKIE_BROWSER_CHANNEL = 'chrome'
uv run pytest -k 'distinct_loopback_hosts_isolate_host_only_bridge_cookies or playwright_subprocess_policy_restores_previous_policy' -x -q --tb=short
```

Observed after the fix: **3 passed, 1,352 deselected, no skips** in 10.90 seconds.
This includes both unchanged real-browser cookie assertions. The deselected
count increased while the shared consolidation lane added other tests; it is
not a claim that those deselected tests executed. One existing Starlette/httpx
deprecation warning was reported. Full-suite execution remains the main lane's
separate validation gate.

`uv run ruff check`, `uv run ruff format --check`, and `git diff --check` passed
again for this bounded change. The existing default missing-Chromium skip remains
only an environment-availability guard; the explicit Chrome proof above did not
skip. Original diagnostic history is retained above rather than overwritten.
