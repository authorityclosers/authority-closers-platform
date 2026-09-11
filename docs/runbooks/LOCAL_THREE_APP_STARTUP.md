# Managed local Learner, Admin and Coach

This is the preferred **isolated local** workflow. It does not use staging
credentials or data, modify WordPress, or deploy an application.

From the implementation worktree, in an ordinary terminal:

```powershell
& .\scripts\Start-LocalPlatform.ps1
```

The launcher automatically hands Windows PowerShell 5.1 over to an installed
PowerShell 7.4+ and locates an existing Node 24 executable. It first checks PATH,
then the installed Codex runtime under the current user's `.cache`. No manual
PATH prefix or administrator terminal is needed for a healthy, provisioned
local environment. Nothing is downloaded or installed by this compatibility
bootstrap, and User/Machine PATH and Windows security settings stay unchanged.

The existing managed PostgreSQL launcher retains its pinned runtime provisioning
and private data-directory checks. Python and workspace dependencies must already
be installed as documented in the local alpha runbook.

| App | Local address |
| --- | --- |
| Learner | http://learner.localhost:3100/login |
| Platform Admin | http://admin.localhost:3101/login |
| Coach / Academy Studio | http://coach.localhost:3102/login |

Running the command again reuses healthy, identity-verified managed processes.
It verifies API readiness and each requested login page rather than stopping them.
If only one app needs starting, use `-SurfaceSelection learner`, `admin` or `coach`.
For an intentional UI restart, call the same launcher with `-Stop` first. This
stops only its verified selected UI processes, not another workspace or the
database. The API and database launchers also support automatic PowerShell handoff.

`-StudioVideo` remains an explicit opt-in and still requires the existing scanner
proof and private runtime setup. A second start cannot silently upgrade an API
that was launched without Studio video support.

## When startup must stop

Unknown port owners, mismatched process identities, unsafe/reparse state paths,
missing supported tools, and OS permission denials remain errors. Do not change
the firewall, disable security controls, kill unknown processes, delete database
files, or use direct SQL to work around these failures.

The 10 September incident included a self-referential Windows forwarding rule on
3100. The user removed that rule; the agent subsequently started the full stack
under ordinary PowerShell 7 without elevation. The compatibility launcher does
not create or remove portproxy rules, and cannot promise to repair future
administrator-owned network changes automatically.

## Verification

- `tests/unit/test_local_runtime_bootstrap.py` runs isolated fixture scripts under
  Windows PowerShell 5.1 and installed PowerShell 7. It checks argument types,
  failures, existing Node selection, and unchanged process/User/Machine PATH.
- `tests/unit/test_local_platform_launcher.py`,
  `tests/infra/test_local_tcp_listeners.py`, and
  `tests/infra/test_local_postgres_launcher.py` cover the existing local boundaries.
- `scripts/prove-local-profile-photo.py` uses fresh headless browser sessions and
  normal sign-in for the three synthetic local accounts. It replaces only the
  synthetic learner's avatar with the existing academy icon, verifies server
  persistence and decoded image after reload, and saves value-free request status
  evidence. Its password must be supplied in process memory, never a CLI argument
  or committed file. Do not point this fixed-local proof at staging/production.
