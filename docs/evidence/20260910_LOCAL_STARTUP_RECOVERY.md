# Local startup recovery and real profile-photo verification

Date: 10 September 2026. Scope: the existing `d2de` implementation worktree,
ordinary Windows user, isolated local data. These are uncommitted candidate
changes, not an accepted staging/production release.

## Outcome

- The user removed the self-referential portproxy rule on 3100. A subsequent
  read-only listing contained no forwarding rules. The agent did not elevate,
  change Windows security settings, or automate a terminal window.
- Installed PowerShell 7.6.5 started the managed PostgreSQL/API and all three
  Next applications successfully. PostgreSQL performed its normal crash recovery;
  no database files were deleted and no direct SQL recovery was used. Its earlier
  bind denial no longer reproduced, but its original OS-level cause was not
  established by these checks.
- The managed migration runner applied `20260910_0028` to the local sandbox.
  This does not demonstrate that the migration is activated in any remote environment.
- Learner, Platform Admin and Coach login pages were opened as deliverables in
  the controlled in-app browser. Initial server-rendered disabled form controls
  became enabled after hydration. These tabs are login screens, not a claim that
  the user's real production account is authenticated.

## Startup change

`scripts/Local-RuntimeBootstrap.ps1` is Windows PowerShell 5.1-compatible and
hands older shells to an already-installed PowerShell 7.4+. Only typed switch,
surface-enum and numeric-port parameters are forwarded as native arguments.
There is no generated command evaluation, installation, execution-policy bypass,
elevation, persistent PATH edit, or portproxy mutation.

The UI launcher resolves an existing Node 24 executable from PATH or the installed
Codex runtime. Only its child process PATH is prefixed. API and PostgreSQL launchers
also support the same PowerShell handoff. Existing file, process, unknown-listener,
loopback, explicit Studio-video opt-in and environment-isolation guards remain.

A repeated start verifies and reuses healthy owned processes. It rejects duplicate
surface/PID records, unexpected ports and incomplete ownership sets before claiming
readiness; HTTP 200 alone is not ownership proof. A read-only independent review
identified the initial count-only weakness, and the candidate was tightened before
acceptance. A partial-running or unhealthy configuration still fails without
stopping unrelated processes.

Actual invocation after the change, from **Windows PowerShell 5.1**, with no PATH
setup and no elevated shell:

```powershell
& .\scripts\Start-LocalPlatform.ps1
```

Result: automatic PowerShell handoff, API already running, all three local login
checks ready. The installed apps were not restarted by this repeated invocation.
The same invocation succeeded again after the ownership-set hardening.

## Real profile save, not just a preview

`scripts/prove-local-profile-photo.py` opens fresh, isolated headless Chromium
contexts, signs in normally to all three synthetic local accounts, then changes
only the synthetic learner avatar to the existing academy icon. Credentials are
supplied through ephemeral process memory and excluded from output/screenshots.
The script aborts off-origin page requests and uses no SQL, mocked APIs, auth
bypass or real learner data.

Accepted proof directory:
`.tmp/local-platform/new/profile-photo/20260910T080833589680Z/`

- Learner/Admin/Coach: normal sign-in and authenticated `/v1/me` all passed.
- Avatar intent POST: 201; private byte PUT: 204; completion POST: 200.
- Canonical avatar state: new ready version, unchanged version after page reload.
- The reloaded profile image was visible and decoded with nonzero natural dimensions.
- `preview.png`, `saved-reloaded.png` and `proof.json` were saved locally. Root
  visually inspected the preceding successful run's reloaded mobile screenshot;
  the icon rendered in the profile and app header.
- Two initial proof attempts stopped before sign-in because the new test harness
  bound Playwright's callback argument incorrectly. The harness was corrected;
  these were not product authentication failures. No avatar write occurred in them.

This establishes that the current small-PNG local save works. It does **not**
identify the cause of every previously reported photo error or verify large phone
photos, production provider configuration, or remote persistence.

## Verification and remaining release work

The compatibility tests exercise actual Windows PowerShell 5.1 to PowerShell 7
handoff using temporary fixtures, typed/invalid arguments, child failure, no
recursive handoff, existing Node selection, and unchanged process/User/Machine
PATH. Already-running tests mock API/HTTP and never operate real services. The
existing launcher/TCP/PostgreSQL tests remain required with the new tests.

Ruff check/format passed for the proof script and compatibility test file. The
initial combined launcher run passed 34 tests; the later independent ownership
regressions are recorded below when complete. No skipped integration test is
being treated as a production acceptance result.

Independent final bootstrap/ownership suite: **19 passed**; existing UI launcher
suite: **10 passed**. Review reported no remaining Critical/Important findings in
this bounded launcher scope after duplicate/missing ownership and unavailable
health regressions. Root also confirmed its actual shell was **not elevated**
and fresh no-proxy API-ready plus all three login probes returned 200. The real
profile proof above includes the decoded-image-after-reload assertion.

Root's final combined bootstrap, UI launcher, native TCP listener and PostgreSQL
launcher run: **37 passed in 56.26 seconds**. Final scoped Ruff check/format and
`git diff --check` passed.

No staging/production deployment, Cloudflare change, WordPress change, or long
video attachment was performed in this recovery slice. The earlier production
configuration and controlled video/publication gates remain separate work.

Follow-up after the user's pasted Windows PowerShell error: root invoked the
same launcher using `C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe`
with `-NoProfile -NonInteractive -File`. Automatic handoff succeeded and all
three managed apps were reused as ready. Fresh no-proxy API/login probes were
200; the four startup suites were rerun with **37 passed in 29.58 seconds**.
The user does not need another PATH prefix or portproxy operation for the
currently healthy local environment. No additional service restart occurred.
