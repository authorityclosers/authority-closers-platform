"""Offline contract checks for the isolated Windows localhost database launcher."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts/Start-LocalPostgres.ps1"


def test_runtime_source_is_exact_official_https_and_checksum_pinned() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert (
        "https://get.enterprisedb.com/postgresql/postgresql-18.6-3-windows-x64-binaries.zip"
        in source
    )
    assert re.search(r"\$ArchiveHash = '[A-F0-9]{64}'", source)
    assert "Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256" in source
    assert "executable checksum failed" in source
    assert "not a publisher signature" in source


def test_data_and_roles_are_local_and_not_user_supplied_authorities() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    parameters = source.split("# Disposable", 1)[0]
    assert "$Port = 55432" in parameters
    assert "$DataDirectory" not in parameters and "$Host" not in parameters
    assert "'.tmp/local-platform'" in source
    assert "infra/local/postgres/init/001-roles.sql" in source
    assert "Refusing to adopt an existing unmarked PostgreSQL directory" in source
    assert "$Marker.repository -ne $RepositoryRoot" in source
    assert "$Marker.role_contract_sha256 -ne $RoleContractHash" in source
    assert "listen_addresses=127.0.0.1" in source
    assert "'--auth=scram-sha-256'" in source
    assert "-h', '127.0.0.1'" in source
    assert "$Listeners[0].LocalAddress -ne '127.0.0.1'" in source
    assert "Program Files" not in source
    assert "DROP DATABASE" not in source and "ALTER ROLE" not in source


def test_child_process_arguments_environment_and_windows_pipes_are_bounded() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "$Info.CreateNoWindow = $true" in source
    assert "$Info.ArgumentList.Add($Argument)" in source
    assert "$Info.Environment.Remove($Key)" in source
    assert "$Process.WaitForExit(30000)" in source
    assert "$OutputTask.Wait(2000)" in source and "$ErrorTask.Wait(2000)" in source
    assert "$ActualDirectory = Invoke-LocalQuery ac_owner postgres" in source
    assert source.index("$ActualDirectory =") < source.index("'CREATE DATABASE ac_platform")


def test_archive_extraction_and_existing_paths_cannot_escape_isolation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Assert-NoReparseAncestor $StateRoot" in source
    assert "Assert-NoReparseAncestor $RuntimeRoot" in source
    assert "Assert-NoReparseAncestor $DataDirectory" in source
    assert "Archive entry escapes the isolated runtime directory" in source
    assert "^pgsql/(bin|lib|share)/" in source
    assert "pgsql/server_license.txt" in source
    assert "Remove-Item -LiteralPath $PasswordPath" in source
    assert not re.search(r"Remove-Item[^\n]+-(?:Recurse|Force)", source)


def test_test_content_uses_a_second_new_database_without_repairing_existing_policy() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "CREATE DATABASE ac_local_sandbox OWNER ac_owner;" in source
    assert "An unmarked sandbox database already exists" in source
    assert "$Marker['sandbox_initialized'] = $true" in source
    assert "Replace('ON DATABASE ac_platform', 'ON DATABASE ac_local_sandbox')" in source
    assert "Sandbox initialization must not change existing cluster roles" in source
    assert "'-d', 'ac_local_sandbox'" in source
    assert "'--single-transaction', '-f', '-'" in source
    assert "ALTER FUNCTION" not in source and "DISABLE TRIGGER" not in source


def test_launcher_is_valid_powershell_without_starting_a_database() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is unavailable for syntax validation")
    command = (
        "$errors = $null; $tokens = $null; "
        "[System.Management.Automation.Language.Parser]::ParseFile("
        f"'{str(SCRIPT).replace(chr(39), chr(39) * 2)}', "
        "[ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count) { exit 1 }"
    )
    result = subprocess.run(  # noqa: S603 - parse tracked source without executing it
        [pwsh, "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
