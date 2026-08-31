#requires -Version 7.4

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ReleaseSha,

    [ValidatePattern("^[A-Za-z0-9._-]+$")]
    [string]$SshHost = "ac",

    [ValidatePattern("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    [string]$GitHubRepository = "authorityclosers/authority-closers-platform",

    [switch]$ReapplyConfiguration
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$expectedAccessTeamHost = "restless-cherry-c46f.cloudflareaccess.com"
if (-not $IsWindows) {
    throw "The staging controller requires the trusted Windows operator host."
}

$repositoryRoot = Split-Path -Parent $PSScriptRoot
$localApplicationData = [System.Environment]::GetFolderPath(
    [System.Environment+SpecialFolder]::LocalApplicationData
)
if ([string]::IsNullOrWhiteSpace($localApplicationData)) {
    throw "The current Windows identity has no LocalApplicationData boundary."
}
$trustedTransferParent = Join-Path $localApplicationData "AuthorityClosers"
$TransferRoot = Join-Path $trustedTransferParent "authority-closers-release-transfer"
$TransferRoot = [System.IO.Path]::GetFullPath($TransferRoot)

function Assert-NativeSuccess {
    param([Parameter(Mandatory = $true)][string]$Operation)
    if ($LASTEXITCODE -ne 0) {
        throw "$Operation failed with exit code $LASTEXITCODE."
    }
}

function Invoke-SshScript {
    param([Parameter(Mandatory = $true)][string]$Script)
    $normalized = $Script -replace "`r", ""
    if (-not $normalized.EndsWith("`n", [StringComparison]::Ordinal)) {
        $normalized += "`n"
    }
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = (Get-Command ssh -ErrorAction Stop).Source
    $startInfo.ArgumentList.Add($SshHost)
    $startInfo.ArgumentList.Add("bash")
    $startInfo.ArgumentList.Add("-s")
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardInput = $true
    $startInfo.CreateNoWindow = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    try {
        if (-not $process.Start()) {
            throw "Remote command could not start."
        }
        $process.StandardInput.NewLine = "`n"
        $process.StandardInput.Write($normalized)
        $process.StandardInput.Close()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "Remote command failed with exit code $($process.ExitCode)."
        }
    }
    finally { $process.Dispose() }
}

function Get-HttpResult {
    param([Parameter(Mandatory = $true)][string]$Url)
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    try {
        $response = $client.GetAsync($Url).GetAwaiter().GetResult()
        return [pscustomobject]@{
            Status = [int]$response.StatusCode
            Route = if ($response.Headers.Contains("X-Authority-Closers-Route")) {
                ($response.Headers.GetValues("X-Authority-Closers-Route") | Select-Object -First 1)
            }
            else { "" }
            Location = $response.Headers.Location
            CacheControl = [string]$response.Headers.CacheControl
            SetCookies = if ($response.Headers.Contains("Set-Cookie")) {
                @($response.Headers.GetValues("Set-Cookie"))
            }
            else { @() }
            Body = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        }
    }
    finally {
        $client.Dispose()
        $handler.Dispose()
    }
}

function Assert-HttpRoute {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][int]$Status,
        [string]$Route = ""
    )
    $result = Get-HttpResult -Url $Url
    if ($result.Status -ne $Status) {
        throw "$Url returned $($result.Status), expected $Status."
    }
    if ($Route -and $result.Route -ne $Route) {
        throw "$Url used route '$($result.Route)', expected '$Route'."
    }
    Write-Output "PASS  $Url -> $Status$(if ($Route) { " [$Route]" })"
}

function Assert-AdminAccessBoundary {
    $result = Get-HttpResult -Url "https://admin-staging.authorityclosers.com/"
    if ($result.Status -ne 302 -or $null -eq $result.Location) {
        throw "Admin staging is not redirecting through Cloudflare Access."
    }
    if (
        $result.Location.Scheme -ne "https" -or
        -not $result.Location.IsDefaultPort -or
        -not $result.Location.Host.Equals($expectedAccessTeamHost, [StringComparison]::OrdinalIgnoreCase) -or
        $result.Location.AbsolutePath -ne "/cdn-cgi/access/login/admin-staging.authorityclosers.com"
    ) {
        throw "Admin staging returned an unexpected Access destination."
    }
    Write-Output "PASS  Admin staging is protected by the expected Cloudflare Access route."
}

function Assert-LegacyWordPressBoundary {
    foreach ($url in @("https://authorityclosers.com/", "https://www.authorityclosers.com/")) {
        $result = Get-HttpResult -Url $url
        if ($result.Status -ne 200 -or $result.Body -notmatch "wp-content|wp-includes") {
            throw "$url no longer proves the legacy WordPress boundary."
        }
    }
    $addresses = @(
        Resolve-DnsName authorityclosers.com -Type A -ErrorAction Stop |
            Where-Object Type -eq "A" |
            Select-Object -ExpandProperty IPAddress
    )
    if ($addresses -notcontains "162.210.70.199") {
        throw "The WordPress apex no longer resolves to the reviewed legacy origin."
    }
    Write-Output "PASS  WordPress apex and www remain on the reviewed legacy boundary."
}

function Assert-GoogleOAuthStart {
    # The endpoint persists one transaction, so no-op verification never calls it.
    $oauth = Get-HttpResult -Url (
        "https://staging.authorityclosers.com/v1/auth/google/start" +
        "?action=authenticate&surface=learner&return_path=%2Fhome"
    )
    if ($oauth.Status -ne 303 -or $null -eq $oauth.Location) {
        throw "Google OAuth start did not return a provider redirect."
    }
    if (
        $oauth.Location.Scheme -ne "https" -or
        -not $oauth.Location.IsDefaultPort -or
        $oauth.Location.Host -ne "accounts.google.com" -or
        $oauth.Location.AbsolutePath -ne "/o/oauth2/v2/auth" -or
        $oauth.CacheControl -ne "no-store"
    ) {
        throw "Google OAuth start returned an unexpected provider, path, port, or cache policy."
    }
    $transactionCookies = @(
        $oauth.SetCookies | Where-Object { $_ -match "^__Host-ac_oauth_transaction=" }
    )
    if ($transactionCookies.Count -ne 1) {
        throw "Google OAuth start did not set exactly one transaction cookie."
    }
    $cookieParts = @($transactionCookies[0].Split(";") | ForEach-Object { $_.Trim() })
    if ($cookieParts[0] -notmatch "^__Host-ac_oauth_transaction=[A-Za-z0-9_-]{1,4000}\.[A-Za-z0-9_-]{43}$") {
        throw "Google OAuth transaction cookie has an invalid name or value contract."
    }
    foreach ($attribute in @("Secure", "HttpOnly", "SameSite=Lax", "Path=/")) {
        if (-not ($cookieParts | Where-Object { $_ -ieq $attribute })) {
            throw "Google OAuth transaction cookie lacks exact attribute $attribute."
        }
    }
    if ($cookieParts | Where-Object { $_ -imatch "^Domain=" }) {
        throw "Google OAuth __Host- transaction cookie must not set Domain."
    }
    $query = [System.Web.HttpUtility]::ParseQueryString($oauth.Location.Query)
    $callback = [Uri]$query["redirect_uri"]
    if (
        $callback.Scheme -ne "https" -or
        -not $callback.IsDefaultPort -or
        $callback.Host -ne "staging.authorityclosers.com" -or
        $callback.AbsolutePath -ne "/v1/auth/google/callback" -or
        $callback.Query -or
        $callback.Fragment -or
        [string]::IsNullOrWhiteSpace($query["state"])
    ) {
        throw "Google OAuth redirect is missing its exact callback or one-time state."
    }
    Write-Output "PASS  Google OAuth start is cookie-safe and exact-callback-bound."
}

function Test-Staging {
    param([switch]$ProbeOAuth)
    $remoteProof = @"
set -euo pipefail
release_id='$ReleaseSha'
release_dir="/srv/authority-closers/application/releases/`$release_id"
current=/srv/authority-closers/application/current-staging
test -L "`$current"
test "`$(readlink -f "`$current")" = "`$release_dir"
test -f "`$release_dir/RELEASE-FILES.sha256"
(cd "`$release_dir" && sha256sum --check --quiet RELEASE-FILES.sha256)
images="`$release_dir/release-images.env"
test -f "`$images"
expected_image() {
  key="`$1"
  test "`$(grep -c "^`$key=" "`$images")" = 1
  sed -n "s/^`$key=//p" "`$images"
}
assert_container() {
  container="`$1"
  expected="`$2"
  expected_health="`$3"
  require_release_env="`$4"
  test "`$(sudo docker inspect --format '{{.State.Status}}' "`$container")" = running
  if test "`$expected_health" = healthy; then
    test "`$(sudo docker inspect --format '{{.State.Health.Status}}' "`$container")" = healthy
  fi
  test "`$(sudo docker inspect --format '{{.Image}}' "`$container")" = "`$expected"
  if test "`$require_release_env" = yes; then
    sudo docker inspect --format '{{range .Config.Env}}{{println .}}{{end}}' "`$container" |
      grep -Fx "AC_RELEASE_ID=`$release_id" >/dev/null
  fi
}
api_image="`$(expected_image AC_API_IMAGE)"
learner_image="`$(expected_image AC_LEARNER_IMAGE)"
admin_image="`$(expected_image AC_ADMIN_IMAGE)"
postgres_ref="`$(sed -n 's/^    image: `${AC_POSTGRES_IMAGE:-\(postgres@sha256:[0-9a-f]\{64\}\)}$/\1/p' "`$release_dir/compose.yaml")"
test -n "`$postgres_ref"
postgres_image="`$(sudo docker image inspect --format '{{.Id}}' "`$postgres_ref")"
assert_container ac-application-staging-api-1 "`$api_image" healthy yes
assert_container ac-application-staging-worker-1 "`$api_image" running yes
assert_container ac-application-staging-learner-web-1 "`$learner_image" healthy no
assert_container ac-application-staging-admin-web-1 "`$admin_image" healthy no
assert_container ac-application-staging-postgres-1 "`$postgres_image" healthy no
printf 'PASS  Staging release files and running images match exact release %s.\n' "`$release_id"
"@
    Invoke-SshScript -Script $remoteProof
    Assert-HttpRoute -Url "https://staging.authorityclosers.com/" -Status 200 -Route "learner-staging"
    Assert-HttpRoute -Url "https://staging.authorityclosers.com/healthz" -Status 200
    Assert-HttpRoute -Url "https://api-staging.authorityclosers.com/health/live" -Status 200 -Route "api-staging"
    Assert-HttpRoute -Url "https://api-staging.authorityclosers.com/health/ready" -Status 200 -Route "api-staging"
    Assert-HttpRoute -Url "https://api-staging.authorityclosers.com/v1/programs" -Status 200 -Route "api-staging"
    Assert-HttpRoute -Url "https://api-staging.authorityclosers.com/docs" -Status 404 -Route "api-staging"
    Assert-HttpRoute -Url "https://api-staging.authorityclosers.com/openapi.json" -Status 404 -Route "api-staging"
    Assert-AdminAccessBoundary
    Assert-LegacyWordPressBoundary
    if ($ProbeOAuth) { Assert-GoogleOAuthStart }
}

function Expand-ExactArtifact {
    param(
        [Parameter(Mandatory = $true)][System.IO.Stream]$ZipStream,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $expected = @("SHA256SUMS", "application-images.tar.gz", "release-images.env")
    $archive = [System.IO.Compression.ZipArchive]::new(
        $ZipStream,
        [System.IO.Compression.ZipArchiveMode]::Read,
        $true
    )
    try {
        $entries = @($archive.Entries)
        if ($entries.Count -ne $expected.Count) {
            throw "GitHub artifact ZIP has an unexpected entry count."
        }
        foreach ($entry in $entries) {
            if ($entry.FullName -ne $entry.Name -or $entry.Name -notin $expected) {
                throw "GitHub artifact ZIP contains an unsafe or unexpected entry."
            }
            $destinationPath = Join-Path $Destination $entry.Name
            $inputStream = $entry.Open()
            $outputStream = [System.IO.File]::Open(
                $destinationPath,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try { $inputStream.CopyTo($outputStream) }
            finally {
                $outputStream.Dispose()
                $inputStream.Dispose()
            }
        }
    }
    finally { $archive.Dispose() }
}

function Protect-PrivateStage {
    param([Parameter(Mandatory = $true)][string]$StagePath)
    $directory = Get-Item -LiteralPath $StagePath -Force
    if (-not $directory.PSIsContainer -or ($directory.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw "Local staging path must be a real directory."
    }
    if ($IsWindows) {
        $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        $security = [System.Security.AccessControl.DirectorySecurity]::new()
        $security.SetOwner($identity.User)
        $security.SetAccessRuleProtection($true, $false)
        $rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
            $identity.User,
            [System.Security.AccessControl.FileSystemRights]::FullControl,
            [System.Security.AccessControl.InheritanceFlags]"ContainerInherit, ObjectInherit",
            [System.Security.AccessControl.PropagationFlags]::None,
            [System.Security.AccessControl.AccessControlType]::Allow
        )
        $security.SetAccessRule($rule)
        [System.IO.FileSystemAclExtensions]::SetAccessControl($directory, $security)
        $verified = [System.IO.FileSystemAclExtensions]::GetAccessControl($directory)
        $rules = @($verified.GetAccessRules(
                $true,
                $true,
                [System.Security.Principal.SecurityIdentifier]
            ))
        if (
            -not $verified.AreAccessRulesProtected -or
            $rules.Count -ne 1 -or
            $rules[0].IdentityReference -ne $identity.User -or
            $rules[0].AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow -or
            ($rules[0].FileSystemRights -band [System.Security.AccessControl.FileSystemRights]::FullControl) -eq 0
        ) {
            throw "Local staging ACL is not private to the current identity."
        }
    }
    else {
        & chmod 700 -- $StagePath
        Assert-NativeSuccess "Private local staging permissions"
        $mode = [System.IO.File]::GetUnixFileMode($StagePath)
        $forbidden = (
            [System.IO.UnixFileMode]::GroupRead -bor
            [System.IO.UnixFileMode]::GroupWrite -bor
            [System.IO.UnixFileMode]::GroupExecute -bor
            [System.IO.UnixFileMode]::OtherRead -bor
            [System.IO.UnixFileMode]::OtherWrite -bor
            [System.IO.UnixFileMode]::OtherExecute
        )
        if (($mode -band $forbidden) -ne 0) {
            throw "Local staging permissions are not private to the current identity."
        }
    }
}

function Remove-PrivateStage {
    param([Parameter(Mandatory = $true)][string]$StagePath)
    $resolvedStage = [System.IO.Path]::GetFullPath($StagePath)
    $rootPrefix = $TransferRoot.TrimEnd(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    ) + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolvedStage.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing cleanup outside the release-transfer root."
    }
    $leaf = [System.IO.Path]::GetFileName($resolvedStage)
    if ($leaf -notmatch "^\.stage-$ReleaseSha-[0-9a-f]{32}$") {
        throw "Refusing cleanup of an unexpected local staging path."
    }
    if (Test-Path -LiteralPath $resolvedStage) {
        $item = Get-Item -LiteralPath $resolvedStage -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Refusing cleanup of a reparse-point staging directory."
        }
        Remove-Item -LiteralPath $resolvedStage -Recurse -Force
    }
}

$resolvedCommit = (& git -C $repositoryRoot rev-parse "$ReleaseSha`^{commit}").Trim()
Assert-NativeSuccess "Git commit lookup"
if ($resolvedCommit -ne $ReleaseSha) {
    throw "ReleaseSha does not resolve to the exact requested commit."
}

$expectedReleasePath = "/srv/authority-closers/application/releases/$ReleaseSha"
$currentReleaseCommand = 'readlink -f /srv/authority-closers/application/current-staging 2>/dev/null || true'
$currentRelease = ([string](& ssh $SshHost $currentReleaseCommand)).Trim()
Assert-NativeSuccess "Current staging release lookup"
if ($currentRelease -eq $expectedReleasePath -and -not $ReapplyConfiguration) {
    Write-Output "SKIP  Staging already targets $ReleaseSha; running read-only proof only."
    Test-Staging
    exit 0
}
if ($currentRelease -eq $expectedReleasePath) {
    Write-Output "REAPPLY  Re-running the exact release to load reviewed secret references."
}

$artifactName = "ac-application-$ReleaseSha"
$artifactResponse = & gh api "repos/$GitHubRepository/actions/artifacts?name=$artifactName"
Assert-NativeSuccess "GitHub artifact lookup"
$artifacts = @(($artifactResponse | ConvertFrom-Json).artifacts | Where-Object {
        -not $_.expired -and
        $_.name -eq $artifactName -and
        $_.workflow_run.head_sha -eq $ReleaseSha -and
        $_.digest -match "^sha256:[0-9a-f]{64}$"
    } | Sort-Object created_at -Descending)
if ($artifacts.Count -ne 1) {
    throw "Expected exactly one unexpired digest-bound exact-SHA artifact; found $($artifacts.Count)."
}
$artifact = $artifacts[0]
$run = (& gh run view $artifact.workflow_run.id --repo $GitHubRepository --json status,conclusion,headSha | ConvertFrom-Json)
Assert-NativeSuccess "GitHub release run lookup"
if ($run.status -ne "completed" -or $run.conclusion -ne "success" -or $run.headSha -ne $ReleaseSha) {
    throw "The exact-SHA packaging run is not successful."
}

$localApplicationDataItem = Get-Item -LiteralPath $localApplicationData -Force
if (
    -not $localApplicationDataItem.PSIsContainer -or
    ($localApplicationDataItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)
) {
    throw "LocalApplicationData must be a real trusted directory."
}
New-Item -ItemType Directory -Force -Path $trustedTransferParent | Out-Null
Protect-PrivateStage -StagePath $trustedTransferParent
New-Item -ItemType Directory -Force -Path $TransferRoot | Out-Null
$transferRootItem = Get-Item -LiteralPath $TransferRoot -Force
if (-not $transferRootItem.PSIsContainer -or ($transferRootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
    throw "TransferRoot must be a real local directory, not a reparse point."
}
Protect-PrivateStage -StagePath $TransferRoot
$stageDirectory = Join-Path $TransferRoot ".stage-$ReleaseSha-$([Guid]::NewGuid().ToString('N'))"
$remoteDirectory = ""
New-Item -ItemType Directory -Path $stageDirectory | Out-Null
Protect-PrivateStage -StagePath $stageDirectory
try {
    $bundleDirectory = Join-Path $stageDirectory "bundle"
    New-Item -ItemType Directory -Path $bundleDirectory | Out-Null
    $artifactZip = Join-Path $stageDirectory "artifact.zip"
    & gh api "repos/$GitHubRepository/actions/artifacts/$($artifact.id)/zip" > $artifactZip
    Assert-NativeSuccess "Digest-bound GitHub artifact download"
    $artifactStream = [System.IO.File]::Open(
        $artifactZip,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::None
    )
    try {
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        try {
            $artifactDigest = [System.Convert]::ToHexString(
                $hasher.ComputeHash($artifactStream)
            ).ToLowerInvariant()
        }
        finally { $hasher.Dispose() }
        if ("sha256:$artifactDigest" -ne $artifact.digest) {
            throw "Downloaded GitHub artifact does not match its API digest."
        }
        $artifactStream.Position = 0
        Expand-ExactArtifact -ZipStream $artifactStream -Destination $bundleDirectory
    }
    finally { $artifactStream.Dispose() }

    $checksumFile = Join-Path $bundleDirectory "SHA256SUMS"
    $expectedBundleFiles = @("application-images.tar.gz", "release-images.env")
    $seenBundleFiles = @{}
    foreach ($line in Get-Content -LiteralPath $checksumFile) {
        if ($line -notmatch "^([0-9a-f]{64})\s+\*?([^/\\]+)$") {
            throw "SHA256SUMS contains an unsafe or malformed entry."
        }
        $expectedDigest = $Matches[1]
        $name = $Matches[2]
        if ($name -notin $expectedBundleFiles -or $seenBundleFiles.ContainsKey($name)) {
            throw "SHA256SUMS has an unexpected or duplicate file: $name"
        }
        $path = Join-Path $bundleDirectory $name
        $actualDigest = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualDigest -ne $expectedDigest) {
            throw "Release artifact checksum failed for $name."
        }
        $seenBundleFiles[$name] = $true
    }
    if ($seenBundleFiles.Count -ne $expectedBundleFiles.Count) {
        throw "SHA256SUMS does not cover the complete release bundle."
    }

    $archivePath = Join-Path $stageDirectory "ac-application-$ReleaseSha.tar"
    & git -C $repositoryRoot archive --format=tar "--output=$archivePath" $ReleaseSha -- infra/application
    Assert-NativeSuccess "Fresh exact-commit Git archive creation"
    $archiveDigest = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    & python (Join-Path $repositoryRoot "infra/application/scripts/verify-release-archive.py") `
        $archivePath $archiveDigest $ReleaseSha
    Assert-NativeSuccess "Exact-commit release archive verification"

    $remoteDirectory = (& ssh $SshHost "umask 077; mktemp -d /var/tmp/ac-release-$ReleaseSha.XXXXXX").Trim()
    Assert-NativeSuccess "Private remote staging directory creation"
    if ($remoteDirectory -notmatch "^/var/tmp/ac-release-$ReleaseSha\.[A-Za-z0-9]+$") {
        throw "Remote staging directory is outside the validated private pattern."
    }
    & ssh $SshHost "install -d -m 0700 '$remoteDirectory/bundle' '$remoteDirectory/source'"
    Assert-NativeSuccess "Private remote staging layout creation"
    & scp $archivePath "${SshHost}:$remoteDirectory/"
    Assert-NativeSuccess "Release archive transfer"
    foreach ($name in @("SHA256SUMS", "application-images.tar.gz", "release-images.env")) {
        & scp (Join-Path $bundleDirectory $name) "${SshHost}:$remoteDirectory/bundle/"
        Assert-NativeSuccess "Release bundle transfer: $name"
    }

    $deployRemote = @"
set -euo pipefail
release_id='$ReleaseSha'
release_archive='$remoteDirectory/ac-application-$ReleaseSha.tar'
printf '%s  %s\n' '$archiveDigest' "`$release_archive" | sha256sum --check --status
tar --extract --file "`$release_archive" --directory '$remoteDirectory/source' infra/application
sudo env \
  AC_TARGET_ENVIRONMENT=staging \
  AC_RELEASE_ID="`$release_id" \
  AC_RELEASE_ARCHIVE="`$release_archive" \
  AC_RELEASE_ARCHIVE_SHA256='$archiveDigest' \
  AC_IMAGE_BUNDLE_DIR='$remoteDirectory/bundle' \
  '$remoteDirectory/source/infra/application/scripts/install-application-release.sh'
"@
    Invoke-SshScript -Script $deployRemote
    Test-Staging -ProbeOAuth
    Write-Output "PASS  Staging deployment and compact smoke completed for $ReleaseSha."
}
finally {
    if ($remoteDirectory -match "^/var/tmp/ac-release-$ReleaseSha\.[A-Za-z0-9]+$") {
        & ssh $SshHost "rm -rf -- '$remoteDirectory'"
        Assert-NativeSuccess "Private remote staging cleanup"
    }
    Remove-PrivateStage -StagePath $stageDirectory
}
