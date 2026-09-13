from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER_PATH = ROOT / "scripts" / "Deploy-Staging.ps1"
CONTROLLER = CONTROLLER_PATH.read_text(encoding="utf-8")


def test_staging_controller_is_exact_sha_and_idempotent() -> None:
    assert CONTROLLER.startswith("#requires -Version 7.4")
    assert 'ValidatePattern("^[0-9a-f]{40}$")' in CONTROLLER
    assert "[switch]$ReapplyConfiguration" in CONTROLLER
    assert (
        "if ($currentRelease -eq $expectedReleasePath -and -not $ReapplyConfiguration)"
        in CONTROLLER
    )
    assert "running read-only proof only" in CONTROLLER
    assert "Re-running the exact release to load reviewed secret references" in CONTROLLER
    assert "RecoveryWorkflowSha" in CONTROLLER
    assert "reviewed recovery workflow run" in CONTROLLER
    assert '".github/workflows/application-recovery.yml"' in CONTROLLER
    assert '".github/workflows/application.yml"' in CONTROLLER
    assert '"sha256:$artifactDigest" -ne $artifact.digest' in CONTROLLER
    assert '$run.conclusion -ne "success"' in CONTROLLER
    assert "verify-release-archive.py" in CONTROLLER
    assert "sha256sum --check --status" in CONTROLLER
    assert "Fresh exact-commit Git archive creation" in CONTROLLER
    assert "gh run download" not in CONTROLLER
    assert '$process.StandardInput.NewLine = "`n"' in CONTROLLER
    assert '$normalized = $Script -replace "`r", ""' in CONTROLLER
    assert "| & ssh $SshHost bash -s" not in CONTROLLER


def test_staging_controller_preserves_environment_and_provider_gates() -> None:
    assert '[ValidateSet("staging", "production")]' in CONTROLLER
    assert '[string]$TargetEnvironment = "staging"' in CONTROLLER
    assert "AC_TARGET_ENVIRONMENT=$TargetEnvironment" in CONTROLLER
    assert "install-application-release.sh" in CONTROLLER
    assert "AC_RELEASE_ARCHIVE_SHA256" in CONTROLLER
    assert "AC_IMAGE_BUNDLE_DIR" in CONTROLLER
    assert "accounts.google.com" in CONTROLLER
    assert "/o/oauth2/v2/auth" in CONTROLLER
    assert "/v1/auth/google/callback" in CONTROLLER
    assert '"Secure", "HttpOnly", "SameSite=Lax", "Path=/"' in CONTROLLER
    assert "__Host-ac_oauth_transaction" in CONTROLLER
    assert "compatibility and state-keyed cookies" in CONTROLLER
    assert "[A-Za-z0-9_-]{22}" in CONTROLLER
    assert "bind the same signed transaction" in CONTROLLER
    assert "must not set Domain" in CONTROLLER


def test_staging_controller_has_compact_security_smoke() -> None:
    required_urls = (
        "https://$learnerHost/",
        "https://$learnerHost/$asset",
        "https://$learnerHost/sales-xray",
        "https://$coachHost/",
        "https://$coachHost/login",
        "https://$apiHost/health/live",
        "https://$apiHost/health/ready",
        "https://$apiHost/v1/programs",
        "https://$apiHost/docs",
        "https://$apiHost/openapi.json",
        "https://$adminHost/",
        "https://authorityclosers.com/",
        "https://www.authorityclosers.com/",
    )
    for url in required_urls:
        assert url in CONTROLLER
    assert '"learner-$TargetEnvironment"' in CONTROLLER
    assert '"api-$TargetEnvironment"' in CONTROLLER
    assert "ac-application-$TargetEnvironment-worker-1" in CONTROLLER
    assert 'test "`$(readlink -f "`$current")" = "`$release_dir"' in CONTROLLER
    for asset in (
        "apple-touch-icon.png",
        "auth-workspace-lake-v1.png",
        "icon-192.png",
        "icon-512.png",
        "icon.svg",
        "sw.js",
    ):
        assert f'"{asset}"' in CONTROLLER
    assert "RELEASE-FILES.sha256" in CONTROLLER
    assert "{{.Image}}" in CONTROLLER
    assert "restless-cherry-c46f.cloudflareaccess.com" in CONTROLLER
    assert '"/cdn-cgi/access/login/$adminHost"' in CONTROLLER
    assert "wp-content|wp-includes" in CONTROLLER
    assert "162.210.70.199" in CONTROLLER
    assert "ac-application-$TargetEnvironment-coach-web-1" in CONTROLLER
    assert "AC_COACH_IMAGE" in CONTROLLER


@pytest.mark.parametrize(
    "location,status,accepted",
    [
        ("/login", 307, True),
        ("https://coach-staging.authorityclosers.com/login", 307, True),
        ("https://other.example/login", 307, False),
        ("/login?token=synthetic", 307, False),
        ("/login", 302, False),
    ],
)
def test_staging_coach_probe_only_accepts_same_host_login(
    location: str, status: int, accepted: bool
) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell is required for the Windows controller behavior test")
    function = (
        "function Assert-CoachSignInBoundary"
        + CONTROLLER.split("function Assert-CoachSignInBoundary", 1)[1].split(
            "function Assert-LegacyLearnerTransition", 1
        )[0]
    )
    script = f'''$ErrorActionPreference = "Stop"
$TargetEnvironment = "staging"
$environmentLabel = "Staging"
$coachHost = "coach-staging.authorityclosers.com"
function Get-HttpResult {{
    param([string]$Url)
    if ($Url -cne "https://coach-staging.authorityclosers.com/") {{ throw "unexpected request" }}
    return [pscustomobject]@{{Status={status}; Route="coach-staging"; Location="{location}"}}
}}
function Assert-HttpRoute {{
    param([string]$Url, [int]$Status, [string]$Route)
    if (
        $Url -cne "https://coach-staging.authorityclosers.com/login" -or
        $Status -ne 200 -or $Route -cne "coach-staging"
    ) {{ throw "unexpected login probe" }}
}}
{function}
Assert-CoachSignInBoundary
'''
    result = subprocess.run(  # noqa: S603 - only extracted function and no-network fixture
        [pwsh, "-NoProfile", "-Command", script], capture_output=True, text=True, check=False
    )
    assert (result.returncode == 0) is accepted, result.stderr


def test_staging_controller_does_not_embed_secrets_or_enable_side_effects() -> None:
    assert "password=" not in CONTROLLER.lower()
    assert "client_secret=" not in CONTROLLER.lower()
    assert "external_side_effects_hold=false" not in CONTROLLER.lower()
    assert "email_provider=resend" not in CONTROLLER.lower()


def test_staging_controller_uses_private_bounded_stages_and_read_only_noop() -> None:
    assert "mktemp -d /var/tmp/ac-release-$ReleaseSha.XXXXXX" in CONTROLLER
    assert 'if ($remoteDirectory -match "^/var/tmp/ac-release-$ReleaseSha' in CONTROLLER
    assert "Remove-PrivateStage -StagePath $stageDirectory" in CONTROLLER
    assert "Refusing cleanup outside the release-transfer root" in CONTROLLER
    assert "Refusing cleanup of a reparse-point staging directory" in CONTROLLER
    assert "Protect-PrivateStage -StagePath $stageDirectory" in CONTROLLER
    assert "Protect-PrivateStage -StagePath $TransferRoot" in CONTROLLER
    assert "Protect-PrivateStage -StagePath $trustedTransferParent" in CONTROLLER
    assert "SpecialFolder]::LocalApplicationData" in CONTROLLER
    assert "LocalApplicationData must be a real trusted directory" in CONTROLLER
    assert "[string]$TransferRoot" not in CONTROLLER
    assert "SetAccessRuleProtection($true, $false)" in CONTROLLER
    assert "FileShare]::None" in CONTROLLER
    assert "Expand-ExactArtifact -ZipStream $artifactStream" in CONTROLLER
    assert "assert_container ac-application-$TargetEnvironment-postgres-1" in CONTROLLER
    assert "function Invoke-RetriableNative" in CONTROLLER
    assert "[ValidateRange(1, 5)][int]$MaxAttempts = 4" in CONTROLLER
    assert "$exitCode -ne 255" in CONTROLLER
    assert '" after $attempt transport attempts"' in CONTROLLER
    assert "$startInfo.RedirectStandardOutput = $true" in CONTROLLER
    assert "$startInfo.RedirectStandardError = $true" in CONTROLLER
    assert "return $standardOutput" in CONTROLLER
    assert "return $output" not in CONTROLLER
    assert '"Current $TargetEnvironment release lookup"' in CONTROLLER
    assert "Release archive transfer" in CONTROLLER
    assert "Release bundle transfer: $name" in CONTROLLER
    assert "Private remote staging cleanup" in CONTROLLER
    assert "Invoke-SshScript -Script $deployRemote" in CONTROLLER
    deploy = CONTROLLER.split('$deployRemote = @"', maxsplit=1)[1].split(
        "Invoke-SshScript -Script $deployRemote", maxsplit=1
    )[0]
    assert "Invoke-RetriableNative" not in deploy
    noop = CONTROLLER.split(
        "if ($currentRelease -eq $expectedReleasePath -and -not $ReapplyConfiguration)",
        maxsplit=1,
    )[1].split("$artifactName", maxsplit=1)[0]
    assert "Test-Deployment" in noop
    assert "ProbeOAuth" not in noop
    assert (
        "Get-Command scp"
        not in CONTROLLER.split(
            "if ($currentRelease -eq $expectedReleasePath -and -not $ReapplyConfiguration)",
            maxsplit=1,
        )[0]
    )


def test_staging_controller_chunks_and_verifies_the_large_image_bundle() -> None:
    assert "$imagePartSizeBytes = 16 * 1024 * 1024" in CONTROLLER
    assert "function New-DeterministicImageParts" in CONTROLLER
    assert '"application-images.tar.gz.part-{0:D8}"' in CONTROLLER
    assert '"application-images.parts.manifest"' in CONTROLLER
    assert "WriteAllText" in CONTROLLER
    assert "WriteAllLines" not in CONTROLLER
    assert '($manifestLines.ToArray() -join "`n") + "`n"' in CONTROLLER
    assert "Application image part manifest transfer" in CONTROLLER
    assert "Application image part transfer:" in CONTROLLER
    assert "part_limit='$imagePartSizeBytes'" in CONTROLLER
    assert "sha256sum --check --strict SHA256SUMS" in CONTROLLER
    assert 'mv -f -- "`$reassembled" "`$image_archive"' in CONTROLLER

    transfer_section = CONTROLLER.split(
        'foreach ($name in @("SHA256SUMS", "release-images.env"))', maxsplit=1
    )[1].split('$deployRemote = @"', maxsplit=1)[0]
    assert "$imagePartManifestPath" in transfer_section
    assert "$imageParts" in transfer_section
    assert "$imageArchivePath" not in transfer_section
    assert 'application-images.tar.gz"' not in transfer_section
    assert ".application-images.parts/$($part.Name).partial" in transfer_section

    verify_part = CONTROLLER.split("function New-ImagePartVerificationScript", maxsplit=1)[1].split(
        "function Invoke-SshScript", maxsplit=1
    )[0]
    for guard in (
        'test -f "`$verify_path" || return 1',
        'test ! -L "`$verify_path" || return 1',
        '"`$(stat --format=\'%s\' -- "`$verify_path")" || return 1',
        'test "`$part_actual_size" = "`$part_size" || return 1',
        "sha256sum --check --status || return 1",
    ):
        assert guard in verify_part
    assert 'partial_path="`$part_path.partial"' in verify_part
    assert 'test ! -L "`$partial_path"' in verify_part
    assert 'mv -- "`$partial_path" "`$part_path"' in verify_part

    deploy = CONTROLLER.split('$deployRemote = @"', maxsplit=1)[1].split(
        "Invoke-SshScript -Script $deployRemote", maxsplit=1
    )[0]
    assert 'test ! -L "`$part_path"' in deploy
    assert 'partial_path="`$part_path.partial"' not in deploy
    bundle_verification = '(cd "`$bundle_dir" && sha256sum --check --strict SHA256SUMS)'
    installer_invocation = (
        "'$remoteDirectory/source/infra/application/scripts/install-application-release.sh'"
    )
    assert 'rm -rf -- "`$parts_dir"' in deploy
    assert 'rm -- "`$parts_manifest"' in deploy
    assert deploy.index(bundle_verification) < deploy.index('rm -rf -- "`$parts_dir"')
    assert deploy.index('rm -rf -- "`$parts_dir"') < deploy.index(installer_invocation)
    assert deploy.index('rm -- "`$parts_manifest"') < deploy.index(installer_invocation)
    assert "function Invoke-RetriableImagePartTransfer" in CONTROLLER
    assert "-RemoteVerificationScript $verifyPartRemote" in CONTROLLER
    part_helper = CONTROLLER.split("function Invoke-RetriableImagePartTransfer", maxsplit=1)[
        1
    ].split("function Invoke-SshScript", maxsplit=1)[0]
    assert "$exitCode -notin @(1, 255)" in part_helper
    assert "; stderr: $stderrDetail" in part_helper
    generic_helper = CONTROLLER.split("function Invoke-RetriableNative", maxsplit=1)[1].split(
        "function Invoke-RetriableImagePartTransfer", maxsplit=1
    )[0]
    assert "$exitCode -ne 255" in generic_helper
    assert "$exitCode -notin @(1, 255)" not in generic_helper
    assert "Application image part transfer" in CONTROLLER


def test_staging_controller_bounds_native_stderr_and_preserves_primary_errors() -> None:
    assert "function Get-BoundedNativeDetail" in CONTROLLER
    assert "Substring(0, 509)" in CONTROLLER
    assert "$null -ne $standardOutputTask" in CONTROLLER
    assert "$null -ne $standardErrorTask" in CONTROLLER
    assert "; stderr: $stderrDetail" in CONTROLLER
    assert "$primaryError = $null" in CONTROLLER
    assert "$primaryError = $_" in CONTROLLER
    assert "cleanup failed after the primary deployment error" in CONTROLLER
    assert "https?://" in CONTROLLER
    assert "[REDACTED]" in CONTROLLER
    assert "[REDACTED_JWT]" in CONTROLLER
    ssh_helper = CONTROLLER.split("function Invoke-SshScript", maxsplit=1)[1].split(
        "function Get-HttpResult", maxsplit=1
    )[0]
    assert "[switch]$ReturnResult" in ssh_helper
    assert "$startInfo.RedirectStandardError = $true" in ssh_helper
    assert "$standardErrorTask.GetAwaiter().GetResult()" in ssh_helper
    assert "StandardError = $stderrDetail" in ssh_helper
    assert 'Write-Warning "Remote command stderr: $stderrDetail"' in ssh_helper
    assert 'throw "Remote command failed with exit code $exitCode$detailSuffix."' in ssh_helper
    assert "Bearer [REDACTED]" in CONTROLLER
    assert "$cleanupFailures = [System.Collections.Generic.List[object]]::new()" in CONTROLLER
    assert 'Scope = "remote"' in CONTROLLER
    assert 'Scope = "local"' in CONTROLLER
    assert CONTROLLER.count("Remove-PrivateStage -StagePath $stageDirectory") == 1
    cleanup = CONTROLLER.rsplit("finally {", maxsplit=1)[1]
    assert cleanup.index('Scope = "remote"') < cleanup.index('Scope = "local"')
    assert cleanup.index('Scope = "remote"') < cleanup.index(
        "Remove-PrivateStage -StagePath $stageDirectory"
    )
    assert "$remoteDirectory = (& ssh" not in CONTROLLER
    assert '"Private remote staging directory creation"' in CONTROLLER


def test_staging_controller_writes_lf_manifest_and_bash_parses_it(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    bash = None
    git = shutil.which("git")
    candidates: list[Path] = []
    if git is not None and sys.platform == "win32":
        candidates.append(Path(git).parent.parent / "bin" / "bash.exe")
    discovered_bash = shutil.which("bash")
    if discovered_bash is not None:
        candidates.append(Path(discovered_bash))
    for candidate in candidates:
        if candidate.is_file():
            bash = str(candidate)
            break
    if pwsh is None or bash is None:
        if sys.platform == "win32":
            pytest.fail("pwsh and Git Bash are required on the Windows staging lane")
        pytest.skip("pwsh and bash are required for manifest behavior coverage")

    image_path = tmp_path / "application-images.tar.gz"
    image_bytes = (bytes(range(256)) * ((16 * 1024 * 1024 // 256) + 1)) + b"tail"
    image_path.write_bytes(image_bytes)
    parts_directory = tmp_path / "parts"
    parts_directory.mkdir()
    manifest_path = tmp_path / "application-images.parts.manifest"
    harness_path = tmp_path / "invoke-parts.ps1"
    harness_path.write_text(
        """
param([string]$ControllerPath, [string]$ImagePath, [string]$PartsDirectory, [string]$ManifestPath)
$text = [System.IO.File]::ReadAllText($ControllerPath)
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw $errors[0] }
$functionAst = $ast.Find(
    { param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'New-DeterministicImageParts'
    },
    $true
)
Invoke-Expression $functionAst.Extent.Text
New-DeterministicImageParts `
    -ImagePath $ImagePath `
    -PartsDirectory $PartsDirectory `
    -ManifestPath $ManifestPath `
    -PartSizeBytes (16 * 1024 * 1024)
$detailAst = $ast.Find(
    { param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-BoundedNativeDetail'
    },
    $true
)
Invoke-Expression $detailAst.Extent.Text
$sanitized = Get-BoundedNativeDetail (
    'https://restless-cherry-c46f.cloudflareaccess.com/callback?token=TOPSECRET&state=SAFE ' +
    'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.' +
    'abcdefghijklmnopqrstuvwxyz0123456789_-'
)
if (
    $sanitized.Contains('TOPSECRET') -or
    $sanitized.Contains('eyJhbGciOiJIUzI1NiJ9') -or
    $sanitized.Contains('abcdefghijklmnopqrstuvwxyz0123456789_-')
) {
    throw "redaction leaked: $sanitized"
}
""".strip(),
        encoding="utf-8",
        newline="\n",
    )
    result = subprocess.run(  # noqa: S603 - fixed test harness and temporary paths
        [
            pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(harness_path),
            str(CONTROLLER_PATH),
            str(image_path),
            str(parts_directory),
            str(manifest_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    manifest_bytes = manifest_path.read_bytes()
    assert b"\r" not in manifest_bytes
    assert manifest_bytes.endswith(b"\n")
    manifest_lines = manifest_bytes.decode("utf-8").splitlines()
    assert manifest_lines
    assert all(len(line.split("\t")) == 3 for line in manifest_lines)
    parts = sorted(parts_directory.glob("application-images.tar.gz.part-*"))
    assert len(parts) == 2
    assert parts[0].stat().st_size == 16 * 1024 * 1024
    assert b"".join(part.read_bytes() for part in parts) == image_bytes

    bash_script = r"""
set -euo pipefail
expected_index=0
while IFS= read -r manifest_line; do
  IFS=$'\t' read -r part_name part_size part_digest extra <<< "$manifest_line"
  test -n "$part_name" && test -n "$part_size" && test -n "$part_digest"
  test -z "${extra:-}"
  expected_part_name="$(printf 'application-images.tar.gz.part-%08d' "$expected_index")"
  test "$part_name" = "$expected_part_name"
  expected_index=$((expected_index + 1))
done
test "$expected_index" -gt 0
"""
    bash_result = subprocess.run(  # noqa: S603 - fixed parser script and generated manifest
        [bash, "-c", bash_script],
        input=manifest_bytes,
        capture_output=True,
        check=False,
    )
    assert bash_result.returncode == 0, bash_result.stderr.decode(errors="replace")


def test_staging_controller_verifier_handles_partial_and_final_states(tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    bash = None
    git = shutil.which("git")
    candidates: list[Path] = []
    if git is not None and sys.platform == "win32":
        candidates.append(Path(git).parent.parent / "bin" / "bash.exe")
    discovered_bash = shutil.which("bash")
    if discovered_bash is not None:
        candidates.append(Path(discovered_bash))
    for candidate in candidates:
        if candidate.is_file():
            bash = str(candidate)
            break
    if pwsh is None or bash is None:
        if sys.platform == "win32":
            pytest.fail("pwsh and Git Bash are required on the Windows staging lane")
        pytest.skip("pwsh and bash are required for verifier behavior coverage")

    parts_directory = tmp_path / "parts"
    parts_directory.mkdir()
    part_name = "application-images.tar.gz.part-00000000"
    part_path = parts_directory / part_name
    partial_path = parts_directory / f"{part_name}.partial"
    payload = b"verified image part payload\n"
    part_digest = hashlib.sha256(payload).hexdigest()
    verifier_path = tmp_path / "verify-part.sh"
    harness_path = tmp_path / "invoke-verifier.ps1"
    harness_path.write_text(
        """
param(
    [string]$ControllerPath,
    [string]$PartsDirectory,
    [string]$OutputPath,
    [long]$PartSize,
    [string]$PartDigest
)
$text = [System.IO.File]::ReadAllText($ControllerPath)
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw $errors[0] }
$functionAst = $ast.Find(
    { param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'New-ImagePartVerificationScript'
    },
    $true
)
Invoke-Expression $functionAst.Extent.Text
$scriptText = New-ImagePartVerificationScript `
    -PartsDirectory $PartsDirectory `
    -PartName 'application-images.tar.gz.part-00000000' `
    -PartSize $PartSize `
    -PartDigest $PartDigest
[System.IO.File]::WriteAllText($OutputPath, $scriptText, [System.Text.UTF8Encoding]::new($false))
""".strip(),
        encoding="utf-8",
        newline="\n",
    )
    result = subprocess.run(  # noqa: S603 - fixed test harness and temporary paths
        [
            pwsh,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(harness_path),
            str(CONTROLLER_PATH),
            parts_directory.as_posix(),
            str(verifier_path),
            str(len(payload)),
            part_digest,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    verifier = verifier_path.read_text(encoding="utf-8")
    assert "|| return 1" in verifier

    def run_verifier() -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - fixed verifier script and temporary paths
            [bash, "-c", verifier],
            capture_output=True,
            check=False,
        )

    partial_path.write_bytes(payload)
    first = run_verifier()
    assert first.returncode == 0, first.stderr.decode(errors="replace")
    assert part_path.read_bytes() == payload
    assert not partial_path.exists()

    idempotent = run_verifier()
    assert idempotent.returncode == 0, idempotent.stderr.decode(errors="replace")
    assert part_path.read_bytes() == payload

    partial_path.write_bytes(b"corrupt")
    corrupt_with_valid_final = run_verifier()
    assert corrupt_with_valid_final.returncode == 0
    assert part_path.read_bytes() == payload
    assert not partial_path.exists()

    part_path.unlink()
    partial_path.write_bytes(b"corrupt")
    corrupt = run_verifier()
    assert corrupt.returncode != 0
    assert not part_path.exists()
    assert not partial_path.exists()

    link_target = tmp_path / "valid-target"
    link_target.write_bytes(payload)
    try:
        partial_path.symlink_to(link_target)
    except OSError as error:
        pytest.fail(f"symlink verifier coverage is required: {error}")
    symlink = run_verifier()
    assert symlink.returncode != 0
    assert not part_path.exists()
    assert not partial_path.exists()


def test_staging_controller_retries_part_transaction_for_scp_and_ssh_statuses(
    tmp_path: Path,
) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        if sys.platform == "win32":
            pytest.fail("pwsh is required on the Windows staging lane")
        pytest.skip("pwsh is required for helper behavior coverage")

    harness_path = tmp_path / "invoke-part-helper.ps1"
    harness_path.write_text(
        r"""
param([string]$ControllerPath)
$text = [System.IO.File]::ReadAllText($ControllerPath)
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($text, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw $errors[0] }
$detailAst = $ast.Find(
    { param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Get-BoundedNativeDetail'
    },
    $true
)
$helperAst = $ast.Find(
    { param($node)
        $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq 'Invoke-RetriableImagePartTransfer'
    },
    $true
)
Invoke-Expression $detailAst.Extent.Text
Invoke-Expression $helperAst.Extent.Text
$global:SshHost = 'ac'
function Start-Sleep { param([int]$Seconds) }
$script:scpCodes = [System.Collections.Generic.Queue[int]]::new()
$script:sshCodes = [System.Collections.Generic.Queue[int]]::new()
$script:scpCalls = 0
$script:sshCalls = 0
function Invoke-NativeAttempt {
    param([string]$FilePath, [string[]]$NativeArguments, [string]$Operation)
    $script:scpCalls++
    $code = $script:scpCodes.Dequeue()
    $errorDetail = if ($code) { 'checksum=TOPSECRET' } else { '' }
    [pscustomobject]@{ ExitCode = $code; Output = ''; StandardError = $errorDetail }
}
function Invoke-SshScript {
    param([string]$Script, [switch]$ReturnResult)
    $script:sshCalls++
    $code = $script:sshCodes.Dequeue()
    $errorDetail = if ($code -eq 255) {
        'disconnect after rename'
    } elseif ($code) {
        'checksum=TOPSECRET'
    } else {
        ''
    }
    [pscustomobject]@{ ExitCode = $code; Output = ''; StandardError = $errorDetail }
}
function Set-Sequence {
    param([int[]]$Scp, [int[]]$Ssh)
    $script:scpCodes = [System.Collections.Generic.Queue[int]]::new()
    $script:sshCodes = [System.Collections.Generic.Queue[int]]::new()
    foreach ($code in $Scp) { $script:scpCodes.Enqueue($code) }
    foreach ($code in $Ssh) { $script:sshCodes.Enqueue($code) }
    $script:scpCalls = 0
    $script:sshCalls = 0
}
function Assert-Case {
    param(
        [int[]]$Scp,
        [int[]]$Ssh,
        [int]$ExpectedScpCalls,
        [int]$ExpectedSshCalls,
        [bool]$ShouldFail
    )
    Set-Sequence -Scp $Scp -Ssh $Ssh
    $failed = $false
    try {
        Invoke-RetriableImagePartTransfer `
            -ScpPath 'fake-scp' `
            -PartPath 'C:\part-00000000' `
            -RemotePartialPath '/var/tmp/part.partial' `
            -RemoteVerificationScript 'true' `
            -MaxAttempts 3
    }
    catch { $failed = $true }
    if ($failed -ne $ShouldFail) { throw "unexpected helper result" }
    if ($script:scpCalls -ne $ExpectedScpCalls) { throw "unexpected scp calls: $script:scpCalls" }
    if ($script:sshCalls -ne $ExpectedSshCalls) { throw "unexpected ssh calls: $script:sshCalls" }
}
Assert-Case -Scp @(1, 0) -Ssh @(0) -ExpectedScpCalls 2 -ExpectedSshCalls 1 -ShouldFail $false
Assert-Case -Scp @(255, 0) -Ssh @(0) -ExpectedScpCalls 2 -ExpectedSshCalls 1 -ShouldFail $false
Assert-Case -Scp @(0, 0) -Ssh @(1, 0) -ExpectedScpCalls 2 -ExpectedSshCalls 2 -ShouldFail $false
Assert-Case -Scp @(0, 0) -Ssh @(255, 0) -ExpectedScpCalls 2 -ExpectedSshCalls 2 -ShouldFail $false
Assert-Case -Scp @(2) -Ssh @() -ExpectedScpCalls 1 -ExpectedSshCalls 0 -ShouldFail $true
""".strip(),
        encoding="utf-8",
        newline="\n",
    )
    result = subprocess.run(  # noqa: S603 - fixed test harness and temporary path
        [pwsh, "-NoProfile", "-NonInteractive", "-File", str(harness_path), str(CONTROLLER_PATH)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
