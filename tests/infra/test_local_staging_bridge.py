import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
START = (ROOT / "scripts" / "Start-LocalStagingBridge.ps1").read_text(encoding="utf-8")
STOP = (ROOT / "scripts" / "Stop-LocalStagingBridge.ps1").read_text(encoding="utf-8")
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
LEARNER_PACKAGE = json.loads(
    (ROOT / "apps" / "learner-web" / "package.json").read_text(encoding="utf-8")
)
ADMIN_PACKAGE = json.loads(
    (ROOT / "apps" / "admin-web" / "package.json").read_text(encoding="utf-8")
)


def test_package_exposes_small_start_and_stop_commands() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert package["scripts"]["dev:staging"].endswith("scripts/Start-LocalStagingBridge.ps1")
    assert package["scripts"]["dev:staging:down"].endswith("scripts/Stop-LocalStagingBridge.ps1")


def test_launcher_binds_both_next_servers_to_loopback_and_checks_health() -> None:
    assert "Find-NodeMajor -RequiredMajor 24" in START
    assert 'Parameters.ContainsKey("Environment")' in START
    assert '$env:PATH = "$NodeDirectory' in START
    assert START.count('"--hostname", "127.0.0.1"') == 2
    assert "[int]$LearnerPort = 3000" in START
    assert "[int]$AdminPort = 3001" in START
    assert '"--port", "$LearnerPort"' in START
    assert '"--port", "$AdminPort"' in START
    assert '"$LearnerOrigin/v1/programs?limit=1"' in START
    assert '"$AdminOrigin/v1/dev-bridge/health"' in START
    assert 'Response.transport -eq "connected"' in START


def test_launcher_uses_distinct_loopback_hosts_for_browser_cookie_isolation() -> None:
    learner_origin = "http://learner.localhost:3000"
    admin_origin = "http://admin.localhost:3001"

    assert '$LearnerOrigin = "http://learner.localhost:$LearnerPort"' in START
    assert '$AdminOrigin = "http://admin.localhost:$AdminPort"' in START
    assert "$LearnerPort -eq $AdminPort" in START
    assert urlparse(learner_origin).hostname != urlparse(admin_origin).hostname
    assert urlparse(learner_origin).hostname.endswith(".localhost")
    assert urlparse(admin_origin).hostname.endswith(".localhost")


def test_launcher_keeps_virtual_browser_hosts_out_of_node_dns_and_hosts_file() -> None:
    # The browser aliases are a cookie-isolation surface only. Next itself
    # still binds to a literal loopback address, and startup must not mutate a
    # machine-wide hosts file to make Node resolve the aliases.
    assert START.count('"--hostname", "127.0.0.1"') == 2
    assert "System32\\drivers\\etc\\hosts" not in START
    assert "etc/hosts" not in START


def test_launcher_allows_free_alternate_ports_without_widening_hosts() -> None:
    assert "Where-Object { $_.LocalPort -in @($LearnerPort, $AdminPort) }" in START
    assert "select free -LearnerPort and -AdminPort values" in START
    assert START.count("[ValidateRange(1024, 65535)]") == 2


def test_launcher_refuses_to_orphan_an_existing_tracked_bridge() -> None:
    assert "[IO.FileShare]::None" in START
    assert "[IO.FileShare]::None" in STOP
    assert 'Join-Path $RuntimeDirectory "startup.lock"' in START
    assert 'Join-Path $RuntimeDirectory "startup.lock"' in STOP
    assert "$StartupLock.Dispose()" in START
    assert "$StartupLock.Dispose()" in STOP
    assert "Get-LiveTrackedProcesses" in START
    assert "A tracked local staging bridge is already running" in START
    assert "$PidFileCreatedByThisRun = $true" in START
    assert "$PidFileCreatedByThisRun -and" in START


def test_ordinary_app_dev_commands_are_also_loopback_only() -> None:
    assert "--hostname 127.0.0.1" in LEARNER_PACKAGE["scripts"]["dev"]
    assert "--hostname 127.0.0.1" in ADMIN_PACKAGE["scripts"]["dev"]


def test_launcher_uses_only_exact_staging_origins_and_no_database_path() -> None:
    assert "https://staging.authorityclosers.com" in START
    assert "https://admin-staging.authorityclosers.com" in START
    assert "authorityclosers.com" not in START.replace("staging.authorityclosers.com", "")
    assert "DATABASE" not in START.upper()
    assert "docker" not in START.lower()
    assert "sql" not in START.lower()


def test_access_user_token_is_process_only_and_never_documented_as_a_value() -> None:
    assert "access login --quiet --auto-close" in START
    assert '$AdminEnvironment["AC_DEV_ADMIN_ACCESS_JWT"] = $AccessJwt' in START
    assert '$AdminEnvironment.Remove("AC_DEV_ADMIN_ACCESS_JWT")' in START
    assert "AC_DEV_ADMIN_ACCESS_JWT" not in STOP
    assert not any(line.startswith("AC_DEV_ADMIN_ACCESS_JWT=") for line in ENV_EXAMPLE.splitlines())


def test_stop_targets_only_recorded_processes_from_this_workspace() -> None:
    assert "$Record.repository -ne $RepositoryRoot" in STOP
    assert "$Process.StartTime.ToFileTimeUtc()" in STOP
    assert "started_at_file_time_utc" in STOP
    assert "taskkill.exe /PID $Process.Id /T /F" in STOP
    assert "Remove-Item -LiteralPath $ResolvedPidFile" in STOP
    assert "Remove-Item -Recurse" not in STOP
