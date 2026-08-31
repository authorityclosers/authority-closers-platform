from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = (ROOT / "scripts" / "Deploy-Staging.ps1").read_text(encoding="utf-8")


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
    assert "workflow_run.head_sha -eq $ReleaseSha" in CONTROLLER
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
    assert "AC_TARGET_ENVIRONMENT=staging" in CONTROLLER
    assert "AC_TARGET_ENVIRONMENT=production" not in CONTROLLER
    assert "install-application-release.sh" in CONTROLLER
    assert "AC_RELEASE_ARCHIVE_SHA256" in CONTROLLER
    assert "AC_IMAGE_BUNDLE_DIR" in CONTROLLER
    assert "accounts.google.com" in CONTROLLER
    assert "/o/oauth2/v2/auth" in CONTROLLER
    assert "/v1/auth/google/callback" in CONTROLLER
    assert '"Secure", "HttpOnly", "SameSite=Lax", "Path=/"' in CONTROLLER
    assert "__Host-ac_oauth_transaction" in CONTROLLER
    assert "must not set Domain" in CONTROLLER


def test_staging_controller_has_compact_security_smoke() -> None:
    required_urls = (
        "https://staging.authorityclosers.com/",
        "https://staging.authorityclosers.com/$asset",
        "https://api-staging.authorityclosers.com/health/live",
        "https://api-staging.authorityclosers.com/health/ready",
        "https://api-staging.authorityclosers.com/v1/programs",
        "https://api-staging.authorityclosers.com/docs",
        "https://api-staging.authorityclosers.com/openapi.json",
        "https://admin-staging.authorityclosers.com/",
        "https://authorityclosers.com/",
        "https://www.authorityclosers.com/",
    )
    for url in required_urls:
        assert url in CONTROLLER
    assert '"learner-staging"' in CONTROLLER
    assert '"api-staging"' in CONTROLLER
    assert "ac-application-staging-worker-1" in CONTROLLER
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
    assert "/cdn-cgi/access/login/admin-staging.authorityclosers.com" in CONTROLLER
    assert "wp-content|wp-includes" in CONTROLLER
    assert "162.210.70.199" in CONTROLLER


def test_staging_controller_does_not_embed_secrets_or_enable_side_effects() -> None:
    assert "password" not in CONTROLLER.lower()
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
    assert "assert_container ac-application-staging-postgres-1" in CONTROLLER
    assert "([string](& ssh $SshHost $currentReleaseCommand)).Trim()" in CONTROLLER
    noop = CONTROLLER.split(
        "if ($currentRelease -eq $expectedReleasePath -and -not $ReapplyConfiguration)",
        maxsplit=1,
    )[1].split("$artifactName", maxsplit=1)[0]
    assert "Test-Staging" in noop
    assert "ProbeOAuth" not in noop
