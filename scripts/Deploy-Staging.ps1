#requires -Version 7.4

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[0-9a-f]{40}$")]
    [string]$ReleaseSha,

    [ValidateSet("staging", "production")]
    [string]$TargetEnvironment = "staging",

    [ValidatePattern("^[A-Za-z0-9._-]+$")]
    [string]$SshHost = "ac",

    [ValidatePattern("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    [string]$GitHubRepository = "authorityclosers/authority-closers-platform",

    [ValidatePattern("^(|[0-9a-f]{40})$")]
    [string]$RecoveryWorkflowSha = "",

    [switch]$ReapplyConfiguration
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$expectedAccessTeamHost = "restless-cherry-c46f.cloudflareaccess.com"
$environmentLabel = (Get-Culture).TextInfo.ToTitleCase($TargetEnvironment)
$applicationHostSuffix = if ($TargetEnvironment -eq "staging") { "-staging" } else { "" }
$learnerHost = "learner$applicationHostSuffix.authorityclosers.com"
$adminHost = "admin$applicationHostSuffix.authorityclosers.com"
$coachHost = "coach$applicationHostSuffix.authorityclosers.com"
$apiHost = "api$applicationHostSuffix.authorityclosers.com"
$legacyLearnerHost = if ($TargetEnvironment -eq "staging") {
    "staging.authorityclosers.com"
}
else {
    "app.authorityclosers.com"
}
$imagePartSizeBytes = 16 * 1024 * 1024
if (-not $IsWindows) {
    throw "The application release controller requires the trusted Windows operator host."
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

function Get-BoundedNativeDetail {
    param([AllowNull()][object]$Value)
    if ($null -eq $Value) {
        return ""
    }
    $detail = ([string]$Value) -replace "[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", " "
    $detail = ($detail -replace "\s+", " ").Trim()
    $detail = $detail -replace "(?i)(https?://[^\s?#]+)\?[^\s#]*", '$1?[REDACTED]'
    $detail = $detail -replace "(?i)(https?://[^\s#]+)#\S*", '$1#[REDACTED]'
    $detail = $detail -replace (
        "(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}" +
        "(?![A-Za-z0-9_-])"
    ), '[REDACTED_JWT]'
    $detail = $detail -replace "(?i)\b(authorization)(\s*[:=]\s*)Bearer\s+[^\s,;]+", '$1$2[REDACTED]'
    $detail = $detail -replace "(?i)\b(authorization)\s+Bearer\s+[^\s,;]+", '$1 Bearer [REDACTED]'
    $detail = $detail -replace (
        "(?i)\b(token|secret|password|authorization|api[_-]?key|access[_-]?token|refresh[_-]?token)" +
        "\b(\s*[:=]\s*)(?:'[^']*'|`"[^`"]*`"|[^\s,;]+)"
    ), '$1$2[REDACTED]'
    if ($detail.Length -gt 512) {
        return $detail.Substring(0, 509) + "..."
    }
    return $detail
}

function Invoke-NativeAttempt {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$NativeArguments,
        [Parameter(Mandatory = $true)][string]$Operation
    )
    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $FilePath
    foreach ($argument in $NativeArguments) {
        $startInfo.ArgumentList.Add($argument)
    }
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $standardOutput = ""
    $standardError = ""
    $exitCode = -1
    $standardOutputTask = $null
    $standardErrorTask = $null
    try {
        if (-not $process.Start()) {
            throw "$Operation could not start."
        }
        $standardOutputTask = $process.StandardOutput.ReadToEndAsync()
        $standardErrorTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        if ($null -ne $standardOutputTask) {
            $standardOutput = [string]$standardOutputTask.GetAwaiter().GetResult()
        }
        if ($null -ne $standardErrorTask) {
            $standardError = [string]$standardErrorTask.GetAwaiter().GetResult()
        }
        $exitCode = $process.ExitCode
    }
    catch {
        $standardError = $_.Exception.Message
    }
    finally {
        $process.Dispose()
    }
    return [pscustomobject]@{
        Output = $standardOutput
        StandardError = $standardError
        ExitCode = $exitCode
    }
}

function Invoke-RetriableNative {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$NativeArguments,
        [Parameter(Mandatory = $true)][string]$Operation,
        [ValidateRange(1, 5)][int]$MaxAttempts = 4
    )
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $attemptResult = Invoke-NativeAttempt `
            -FilePath $FilePath `
            -NativeArguments $NativeArguments `
            -Operation $Operation
        $exitCode = $attemptResult.ExitCode
        $standardOutput = $attemptResult.Output
        $stderrDetail = Get-BoundedNativeDetail -Value $attemptResult.StandardError
        if ($exitCode -eq 0) {
            return $standardOutput
        }
        $detailSuffix = if ($stderrDetail) { "; stderr: $stderrDetail" } else { "" }
        if ($exitCode -ne 255 -or $attempt -eq $MaxAttempts) {
            $attemptSummary = if ($exitCode -eq 255) {
                " after $attempt transport attempts"
            }
            else {
                ""
            }
            throw "$Operation failed with exit code $exitCode$attemptSummary$detailSuffix."
        }
        Write-Warning (
            "$Operation connection attempt $attempt of $MaxAttempts failed with exit code " +
            "$exitCode$detailSuffix; retrying."
        )
        Start-Sleep -Seconds 2
    }
}

function Invoke-RetriableImagePartTransfer {
    param(
        [Parameter(Mandatory = $true)][string]$ScpPath,
        [Parameter(Mandatory = $true)][string]$PartPath,
        [Parameter(Mandatory = $true)][string]$RemotePartialPath,
        [Parameter(Mandatory = $true)][string]$RemoteVerificationScript,
        [ValidateRange(1, 5)][int]$MaxAttempts = 4
    )
    $operation = "Application image part transfer: $([System.IO.Path]::GetFileName($PartPath))"
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $attemptResult = Invoke-NativeAttempt `
            -FilePath $ScpPath `
            -NativeArguments @($PartPath, "${SshHost}:$RemotePartialPath") `
            -Operation $operation
        $exitCode = $attemptResult.ExitCode
        $stderrDetail = Get-BoundedNativeDetail -Value $attemptResult.StandardError
        if ($exitCode -eq 0) {
            $verificationResult = Invoke-SshScript `
                -Script $RemoteVerificationScript `
                -ReturnResult
            $exitCode = $verificationResult.ExitCode
            $stderrDetail = Get-BoundedNativeDetail -Value $verificationResult.StandardError
            if ($exitCode -eq 0) {
                return
            }
        }
        $detailSuffix = if ($stderrDetail) { "; stderr: $stderrDetail" } else { "" }
        if ($exitCode -notin @(1, 255) -or $attempt -eq $MaxAttempts) {
            $attemptSummary = if ($exitCode -in @(1, 255)) {
                " after $attempt attempts"
            }
            else {
                ""
            }
            throw "$operation failed with exit code $exitCode$attemptSummary$detailSuffix."
        }
        Write-Warning (
            "$operation attempt $attempt of $MaxAttempts failed with exit code " +
            "$exitCode$detailSuffix; retrying."
        )
        Start-Sleep -Seconds 2
    }
}

function New-ImagePartVerificationScript {
    param(
        [Parameter(Mandatory = $true)][string]$PartsDirectory,
        [Parameter(Mandatory = $true)][string]$PartName,
        [Parameter(Mandatory = $true)][long]$PartSize,
        [Parameter(Mandatory = $true)][string]$PartDigest
    )
    @"
set -euo pipefail
parts_dir='$PartsDirectory'
part_name='$PartName'
part_size='$PartSize'
part_digest='$PartDigest'
part_path="`$parts_dir/`$part_name"
partial_path="`$part_path.partial"
verify_part_path() {
  verify_path="`$1"
  test -f "`$verify_path" || return 1
  test ! -L "`$verify_path" || return 1
  part_actual_size="`$(stat --format='%s' -- "`$verify_path")" || return 1
  test "`$part_actual_size" = "`$part_size" || return 1
  printf '%s  %s\n' "`$part_digest" "`$verify_path" | sha256sum --check --status || return 1
}
if test -e "`$part_path" || test -L "`$part_path"; then
  if test -e "`$partial_path" || test -L "`$partial_path"; then
    rm -f -- "`$partial_path"
  fi
  if verify_part_path "`$part_path"; then
    test ! -e "`$partial_path"
    test ! -L "`$partial_path"
    exit 0
  fi
  rm -f -- "`$part_path"
  exit 1
fi
if ! test -e "`$partial_path" && ! test -L "`$partial_path"; then
  exit 1
fi
if ! verify_part_path "`$partial_path"; then
  rm -f -- "`$partial_path"
  exit 1
fi
mv -- "`$partial_path" "`$part_path"
if ! verify_part_path "`$part_path"; then
  rm -f -- "`$part_path"
  exit 1
fi
test ! -e "`$partial_path"
test ! -L "`$partial_path"
"@
}

function Invoke-SshScript {
    param(
        [Parameter(Mandatory = $true)][string]$Script,
        [switch]$ReturnResult
    )
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
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    $standardOutput = ""
    $standardError = ""
    $exitCode = -1
    $standardOutputTask = $null
    $standardErrorTask = $null
    try {
        if (-not $process.Start()) {
            throw "Remote command could not start."
        }
        $process.StandardInput.NewLine = "`n"
        $process.StandardInput.Write($normalized)
        $process.StandardInput.Close()
        $standardOutputTask = $process.StandardOutput.ReadToEndAsync()
        $standardErrorTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        if ($null -ne $standardOutputTask) {
            $standardOutput = [string]$standardOutputTask.GetAwaiter().GetResult()
        }
        if ($null -ne $standardErrorTask) {
            $standardError = [string]$standardErrorTask.GetAwaiter().GetResult()
        }
        $exitCode = $process.ExitCode
    }
    catch {
        $standardError = $_.Exception.Message
    }
    finally {
        $process.Dispose()
    }
    $stderrDetail = Get-BoundedNativeDetail -Value $standardError
    $result = [pscustomobject]@{
        ExitCode = $exitCode
        Output = $standardOutput
        StandardError = $stderrDetail
    }
    if ($ReturnResult) {
        return $result
    }
    if ($exitCode -ne 0) {
        $detailSuffix = if ($stderrDetail) { "; stderr: $stderrDetail" } else { "" }
        throw "Remote command failed with exit code $exitCode$detailSuffix."
    }
    if ($stderrDetail) {
        Write-Warning "Remote command stderr: $stderrDetail"
    }
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
    $result = Get-HttpResult -Url "https://$adminHost/"
    if ($result.Status -ne 302 -or $null -eq $result.Location) {
        throw "$environmentLabel Admin is not redirecting through Cloudflare Access."
    }
    if (
        $result.Location.Scheme -ne "https" -or
        -not $result.Location.IsDefaultPort -or
        -not $result.Location.Host.Equals($expectedAccessTeamHost, [StringComparison]::OrdinalIgnoreCase) -or
        $result.Location.AbsolutePath -ne "/cdn-cgi/access/login/$adminHost"
    ) {
        throw "$environmentLabel Admin returned an unexpected Access destination."
    }
    Write-Output "PASS  $environmentLabel Admin is protected by the expected Cloudflare Access route."
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

function Assert-CoachSignInBoundary {
    $result = Get-HttpResult -Url "https://$coachHost/"
    $location = [string]$result.Location
    if (
        $result.Status -ne 307 -or
        $result.Route -ne "coach-$TargetEnvironment" -or
        $location -cnotin @("/login", "https://$coachHost/login")
    ) {
        throw "$environmentLabel Coach did not return its exact same-host sign-in boundary."
    }
    Assert-HttpRoute -Url "https://$coachHost/login" -Status 200 -Route "coach-$TargetEnvironment"
    Write-Output "PASS  $environmentLabel Coach requires normal same-host sign-in."
}

function Assert-LegacyLearnerTransition {
    $legacy = Get-HttpResult -Url "https://$legacyLearnerHost/"
    if (
        $legacy.Status -ne 302 -or
        [string]$legacy.Location -cne "https://$learnerHost/" -or
        $legacy.CacheControl -ne "no-store"
    ) {
        throw "$environmentLabel legacy learner did not return the reviewed temporary redirect."
    }
    $oldCallback = Get-HttpResult -Url "https://$legacyLearnerHost/v1/auth/google/callback"
    if ($oldCallback.Status -ne 410 -or $null -ne $oldCallback.Location -or $oldCallback.CacheControl -ne "no-store") {
        throw "Legacy learner callbacks must terminate without redirecting credentials."
    }
    Write-Output "PASS  Legacy learner pages redirect; old API sessions require sign-in again."
}

function Assert-GoogleOAuthStart {
    # The endpoint persists one transaction, so no-op verification never calls it.
    $oauth = Get-HttpResult -Url (
        "https://learner-staging.authorityclosers.com/v1/auth/google/start" +
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
    $compatibilityCookies = @(
        $oauth.SetCookies | Where-Object { $_ -match "^__Host-ac_oauth_transaction=" }
    )
    $stateCookies = @(
        $oauth.SetCookies |
            Where-Object { $_ -match "^__Host-ac_oauth_transaction\.[A-Za-z0-9_-]{22}=" }
    )
    if ($compatibilityCookies.Count -ne 1 -or $stateCookies.Count -ne 1) {
        throw "Google OAuth start did not set the exact compatibility and state-keyed cookies."
    }
    $transactionValues = @()
    foreach ($transactionCookie in @($compatibilityCookies[0], $stateCookies[0])) {
        $cookieParts = @($transactionCookie.Split(";") | ForEach-Object { $_.Trim() })
        if ($cookieParts[0] -notmatch "^__Host-ac_oauth_transaction(?:\.[A-Za-z0-9_-]{22})?=([A-Za-z0-9_-]{1,4000}\.[A-Za-z0-9_-]{43})$") {
            throw "Google OAuth transaction cookie has an invalid name or value contract."
        }
        $transactionValues += $Matches[1]
        foreach ($attribute in @("Secure", "HttpOnly", "SameSite=Lax", "Path=/")) {
            if (-not ($cookieParts | Where-Object { $_ -ieq $attribute })) {
                throw "Google OAuth transaction cookie lacks exact attribute $attribute."
            }
        }
        if ($cookieParts | Where-Object { $_ -imatch "^Domain=" }) {
            throw "Google OAuth __Host- transaction cookie must not set Domain."
        }
    }
    if ($transactionValues.Count -ne 2 -or $transactionValues[0] -cne $transactionValues[1]) {
        throw "Google OAuth transaction cookies do not bind the same signed transaction."
    }
    $query = [System.Web.HttpUtility]::ParseQueryString($oauth.Location.Query)
    $callback = [Uri]$query["redirect_uri"]
    if (
        $callback.Scheme -ne "https" -or
        -not $callback.IsDefaultPort -or
        $callback.Host -ne "learner-staging.authorityclosers.com" -or
        $callback.AbsolutePath -ne "/v1/auth/google/callback" -or
        $callback.Query -or
        $callback.Fragment -or
        [string]::IsNullOrWhiteSpace($query["state"])
    ) {
        throw "Google OAuth redirect is missing its exact callback or one-time state."
    }
    Write-Output "PASS  Google OAuth start is cookie-safe and exact-callback-bound."
}

function Test-Deployment {
    param([switch]$ProbeOAuth)
    $remoteProof = @"
set -euo pipefail
release_id='$ReleaseSha'
release_dir="/srv/authority-closers/application/releases/`$release_id"
current=/srv/authority-closers/application/current-$TargetEnvironment
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
coach_image="`$(expected_image AC_COACH_IMAGE)"
postgres_ref="`$(sed -n 's/^    image: `${AC_POSTGRES_IMAGE:-\(postgres@sha256:[0-9a-f]\{64\}\)}$/\1/p' "`$release_dir/compose.yaml")"
test -n "`$postgres_ref"
postgres_image="`$(sudo docker image inspect --format '{{.Id}}' "`$postgres_ref")"
assert_container ac-application-$TargetEnvironment-api-1 "`$api_image" healthy yes
assert_container ac-application-$TargetEnvironment-worker-1 "`$api_image" running yes
assert_container ac-application-$TargetEnvironment-learner-web-1 "`$learner_image" healthy no
assert_container ac-application-$TargetEnvironment-admin-web-1 "`$admin_image" healthy no
assert_container ac-application-$TargetEnvironment-coach-web-1 "`$coach_image" healthy no
assert_container ac-application-$TargetEnvironment-postgres-1 "`$postgres_image" healthy no
printf 'PASS  $environmentLabel release files and running images match exact release %s.\n' "`$release_id"
"@
    Invoke-SshScript -Script $remoteProof
    Assert-HttpRoute -Url "https://$learnerHost/" -Status 200 -Route "learner-$TargetEnvironment"
    Assert-HttpRoute -Url "https://$learnerHost/healthz" -Status 200
    Assert-HttpRoute -Url "https://$learnerHost/sales-xray" -Status 200 -Route "learner-$TargetEnvironment"
    foreach ($asset in @(
            "apple-touch-icon.png",
            "auth-workspace-lake-v1.png",
            "icon-192.png",
            "icon-512.png",
            "icon.svg",
            "sw.js"
        )) {
        Assert-HttpRoute `
            -Url "https://$learnerHost/$asset" `
            -Status 200 `
            -Route "learner-$TargetEnvironment"
    }
    Assert-HttpRoute -Url "https://$apiHost/health/live" -Status 200 -Route "api-$TargetEnvironment"
    Assert-HttpRoute -Url "https://$apiHost/health/ready" -Status 200 -Route "api-$TargetEnvironment"
    Assert-HttpRoute -Url "https://$apiHost/v1/programs" -Status 200 -Route "api-$TargetEnvironment"
    Assert-HttpRoute -Url "https://$apiHost/docs" -Status 404 -Route "api-$TargetEnvironment"
    Assert-HttpRoute -Url "https://$apiHost/openapi.json" -Status 404 -Route "api-$TargetEnvironment"
    Assert-AdminAccessBoundary
    Assert-CoachSignInBoundary
    Assert-LegacyLearnerTransition
    Assert-LegacyWordPressBoundary
    if ($ProbeOAuth) {
        if ($TargetEnvironment -ne "staging") {
            throw "Stateful OAuth probing is restricted to staging."
        }
        Assert-GoogleOAuthStart
    }
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

function New-DeterministicImageParts {
    param(
        [Parameter(Mandatory = $true)][string]$ImagePath,
        [Parameter(Mandatory = $true)][string]$PartsDirectory,
        [Parameter(Mandatory = $true)][string]$ManifestPath,
        [Parameter(Mandatory = $true)][long]$PartSizeBytes
    )
    if ($PartSizeBytes -ne (16 * 1024 * 1024)) {
        throw "Application image part size must remain exactly 16 MiB."
    }
    $image = Get-Item -LiteralPath $ImagePath -Force
    if ($image.PSIsContainer -or ($image.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw "Application image archive must be a real local file."
    }
    if ($image.Length -le 0) {
        throw "Application image archive must not be empty."
    }
    $manifestLines = [System.Collections.Generic.List[string]]::new()
    $buffer = [byte[]]::new(1024 * 1024)
    $inputStream = [System.IO.File]::Open(
        $ImagePath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::Read
    )
    try {
        $partIndex = 0
        while ($inputStream.Position -lt $inputStream.Length) {
            $partName = "application-images.tar.gz.part-{0:D8}" -f $partIndex
            $partPath = Join-Path $PartsDirectory $partName
            $partStream = [System.IO.File]::Open(
                $partPath,
                [System.IO.FileMode]::CreateNew,
                [System.IO.FileAccess]::Write,
                [System.IO.FileShare]::None
            )
            try {
                $remaining = [Math]::Min(
                    [int64]$PartSizeBytes,
                    $inputStream.Length - $inputStream.Position
                )
                while ($remaining -gt 0) {
                    $readLength = [int][Math]::Min([int64]$buffer.Length, $remaining)
                    $read = $inputStream.Read($buffer, 0, $readLength)
                    if ($read -le 0) {
                        throw "Application image archive ended before a deterministic part was complete."
                    }
                    $partStream.Write($buffer, 0, $read)
                    $remaining -= $read
                }
            }
            finally {
                $partStream.Dispose()
            }
            $partSize = (Get-Item -LiteralPath $partPath -Force).Length
            if ($partSize -le 0 -or $partSize -gt $PartSizeBytes) {
                throw "Generated application image part has an invalid size."
            }
            $partDigest = (Get-FileHash -LiteralPath $partPath -Algorithm SHA256).Hash.ToLowerInvariant()
            $manifestLines.Add("$partName`t$partSize`t$partDigest")
            $partIndex++
        }
    }
    finally {
        $inputStream.Dispose()
    }
    if ($manifestLines.Count -eq 0) {
        throw "Application image part manifest must not be empty."
    }
    $manifestText = ($manifestLines.ToArray() -join "`n") + "`n"
    [System.IO.File]::WriteAllText(
        $ManifestPath,
        $manifestText,
        [System.Text.UTF8Encoding]::new($false)
    )
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
$recoveryWorkflowRequested = -not [string]::IsNullOrWhiteSpace($RecoveryWorkflowSha)
if ($recoveryWorkflowRequested) {
    $resolvedRecoveryWorkflowCommit = (& git -C $repositoryRoot rev-parse "$RecoveryWorkflowSha`^{commit}").Trim()
    Assert-NativeSuccess "Recovery workflow commit lookup"
    if ($resolvedRecoveryWorkflowCommit -ne $RecoveryWorkflowSha) {
        throw "RecoveryWorkflowSha does not resolve to the exact requested commit."
    }
    $recoveryWorkflowText = (& git -C $repositoryRoot show "$RecoveryWorkflowSha`:.github/workflows/application-recovery.yml" | Out-String)
    Assert-NativeSuccess "Recovery workflow source lookup"
    foreach ($requiredRecoveryMarker in @(
            "release_sha",
            "validation_run_id",
            "published_registry_digests",
            "Validate published-image recovery proof",
            "Pull and verify published release images",
            "REUSE_VALIDATION_RUN_ID"
        )) {
        if (-not $recoveryWorkflowText.Contains($requiredRecoveryMarker)) {
            throw "Recovery workflow commit is missing the reviewed package-recovery contract."
        }
    }
}

$expectedReleasePath = "/srv/authority-closers/application/releases/$ReleaseSha"
$currentReleaseCommand = "readlink -f /srv/authority-closers/application/current-$TargetEnvironment 2>/dev/null || true"
$sshPath = (Get-Command ssh -ErrorAction Stop).Source
$currentRelease = ([string](
        Invoke-RetriableNative `
            -FilePath $sshPath `
            -NativeArguments @($SshHost, $currentReleaseCommand) `
            -Operation "Current $TargetEnvironment release lookup"
    )).Trim()
if ($currentRelease -eq $expectedReleasePath -and -not $ReapplyConfiguration) {
    Write-Output "SKIP  $environmentLabel already targets $ReleaseSha; running read-only proof only."
    Test-Deployment
    exit 0
}
if ($currentRelease -eq $expectedReleasePath) {
    Write-Output "REAPPLY  Re-running the exact release to load reviewed secret references."
}
$scpPath = (Get-Command scp -ErrorAction Stop).Source

$artifactName = "ac-application-$ReleaseSha"
$artifactResponse = & gh api "repos/$GitHubRepository/actions/artifacts?name=$artifactName"
Assert-NativeSuccess "GitHub artifact lookup"
$artifacts = @(($artifactResponse | ConvertFrom-Json).artifacts | Where-Object {
        -not $_.expired -and
        $_.name -eq $artifactName -and
        $_.digest -match "^sha256:[0-9a-f]{64}$"
    } | Sort-Object created_at -Descending)
$boundArtifacts = @($artifacts | Where-Object {
        $_.workflow_run.head_sha -eq $ReleaseSha -or
        ($recoveryWorkflowRequested -and $_.workflow_run.head_sha -eq $RecoveryWorkflowSha)
    })
if ($boundArtifacts.Count -ne 1) {
    throw "Expected exactly one unexpired digest-bound release artifact bound to the exact release or reviewed recovery SHA; found $($boundArtifacts.Count)."
}
$artifact = $boundArtifacts[0]
$run = (& gh api "repos/$GitHubRepository/actions/runs/$($artifact.workflow_run.id)" | ConvertFrom-Json)
Assert-NativeSuccess "GitHub release run lookup"
if ($run.status -ne "completed" -or $run.conclusion -ne "success") {
    throw "The exact-SHA packaging run is not successful."
}
$runHeadSha = [string]$run.head_sha
$standardReleaseRun = $runHeadSha -eq $ReleaseSha
$recoveryReleaseRun = (
    $recoveryWorkflowRequested -and
    $runHeadSha -eq $RecoveryWorkflowSha -and
    [string]$run.event -eq "workflow_dispatch" -and
    [string]$run.path -eq ".github/workflows/application-recovery.yml"
)
if (-not $standardReleaseRun -and -not $recoveryReleaseRun) {
    throw "The artifact is not bound to the exact release SHA or a reviewed recovery workflow run."
}
if ($recoveryReleaseRun) {
    Write-Output "PASS  Accepted reviewed package-recovery run $runHeadSha for release $ReleaseSha."
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
$primaryError = $null
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
    $imageArchivePath = Join-Path $bundleDirectory "application-images.tar.gz"
    $imagePartsDirectory = Join-Path $stageDirectory "application-image-parts"
    $imagePartManifestPath = Join-Path $stageDirectory "application-images.parts.manifest"
    New-Item -ItemType Directory -Path $imagePartsDirectory | Out-Null
    New-DeterministicImageParts `
        -ImagePath $imageArchivePath `
        -PartsDirectory $imagePartsDirectory `
        -ManifestPath $imagePartManifestPath `
        -PartSizeBytes $imagePartSizeBytes
    $imageParts = @(Get-ChildItem -LiteralPath $imagePartsDirectory -File -Force | Sort-Object Name)
    if ($imageParts.Count -eq 0) {
        throw "Application image part transfer set must not be empty."
    }
    foreach ($part in $imageParts) {
        if ($part.Name -notmatch "^application-images\.tar\.gz\.part-[0-9]{8}$") {
            throw "Application image part has an unsafe deterministic name."
        }
    }

    $archivePath = Join-Path $stageDirectory "ac-application-$ReleaseSha.tar"
    & git -C $repositoryRoot archive --format=tar "--output=$archivePath" $ReleaseSha -- infra/application
    Assert-NativeSuccess "Fresh exact-commit Git archive creation"
    $archiveDigest = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    & python (Join-Path $repositoryRoot "infra/application/scripts/verify-release-archive.py") `
        $archivePath $archiveDigest $ReleaseSha
    Assert-NativeSuccess "Exact-commit release archive verification"

    $remoteDirectory = ([string](
            Invoke-RetriableNative `
                -FilePath $sshPath `
                -NativeArguments @(
                    $SshHost,
                    "umask 077; mktemp -d /var/tmp/ac-release-$ReleaseSha.XXXXXX"
                ) `
                -Operation "Private remote staging directory creation"
        )).Trim()
    if ($remoteDirectory -notmatch "^/var/tmp/ac-release-$ReleaseSha\.[A-Za-z0-9]+$") {
        throw "Remote staging directory is outside the validated private pattern."
    }
    Invoke-RetriableNative `
        -FilePath $sshPath `
        -NativeArguments @(
            $SshHost,
            "install -d -m 0700 '$remoteDirectory/bundle' '$remoteDirectory/bundle/.application-images.parts' '$remoteDirectory/source'"
        ) `
        -Operation "Private remote staging layout creation" | Out-Null
    Invoke-RetriableNative `
        -FilePath $scpPath `
        -NativeArguments @($archivePath, "${SshHost}:$remoteDirectory/") `
        -Operation "Release archive transfer" | Out-Null
    foreach ($name in @("SHA256SUMS", "release-images.env")) {
        Invoke-RetriableNative `
            -FilePath $scpPath `
            -NativeArguments @(
                (Join-Path $bundleDirectory $name),
                "${SshHost}:$remoteDirectory/bundle/"
            ) `
            -Operation "Release bundle transfer: $name" | Out-Null
    }
    Invoke-RetriableNative `
        -FilePath $scpPath `
        -NativeArguments @(
            $imagePartManifestPath,
            "${SshHost}:$remoteDirectory/bundle/"
        ) `
        -Operation "Application image part manifest transfer" | Out-Null
    foreach ($part in $imageParts) {
        $partDigest = (Get-FileHash -LiteralPath $part.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        $verifyPartRemote = New-ImagePartVerificationScript `
            -PartsDirectory "$remoteDirectory/bundle/.application-images.parts" `
            -PartName $part.Name `
            -PartSize $part.Length `
            -PartDigest $partDigest
        Invoke-RetriableImagePartTransfer `
            -ScpPath $scpPath `
            -PartPath $part.FullName `
            -RemotePartialPath "$remoteDirectory/bundle/.application-images.parts/$($part.Name).partial" `
            -RemoteVerificationScript $verifyPartRemote | Out-Null
    }

    $deployRemote = @"
set -euo pipefail
release_id='$ReleaseSha'
release_archive='$remoteDirectory/ac-application-$ReleaseSha.tar'
bundle_dir='$remoteDirectory/bundle'
parts_dir="`$bundle_dir/.application-images.parts"
parts_manifest="`$bundle_dir/application-images.parts.manifest"
image_archive="`$bundle_dir/application-images.tar.gz"
checksum_file="`$bundle_dir/SHA256SUMS"
part_limit='$imagePartSizeBytes'
test -f "`$parts_manifest"
test -f "`$checksum_file"
manifest_count=0
expected_index=0
while IFS= read -r manifest_line; do
  IFS=`$'\t' read -r part_name part_size part_digest extra <<< "`$manifest_line"
  canonical_line="`$part_name"`$'\t'"`$part_size"`$'\t'"`$part_digest"
  test "`$manifest_line" = "`$canonical_line"
  if test -z "`$part_name" || test -z "`$part_size" || test -z "`$part_digest" || test -n "`$extra"; then
    echo 'invalid application image part manifest entry' >&2
    exit 1
  fi
  if ! [[ "`$part_name" =~ ^application-images\.tar\.gz\.part-[0-9]{8}`$ ]]; then
    echo 'unsafe application image part name' >&2
    exit 1
  fi
  expected_part_name="`$(printf 'application-images.tar.gz.part-%08d' "`$expected_index")"
  test "`$part_name" = "`$expected_part_name"
  if ! [[ "`$part_size" =~ ^[1-9][0-9]*`$ ]] || test "`$part_size" -gt "`$part_limit"; then
    echo 'invalid application image part size' >&2
    exit 1
  fi
  if ! [[ "`$part_digest" =~ ^[0-9a-f]{64}`$ ]]; then
    echo 'invalid application image part digest' >&2
    exit 1
  fi
  part_path="`$parts_dir/`$part_name"
  test ! -L "`$part_path"
  test -f "`$part_path"
  part_actual_size="`$(stat --format='%s' -- "`$part_path")"
  test "`$part_actual_size" = "`$part_size"
  printf '%s  %s\n' "`$part_digest" "`$part_path" | sha256sum --check --status
  manifest_count=`$((manifest_count + 1))
  expected_index=`$((expected_index + 1))
done < "`$parts_manifest"
test "`$manifest_count" -gt 0
test "`$manifest_count" = "`$expected_index"
actual_part_count="`$(find "`$parts_dir" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | wc -l)"
test "`$actual_part_count" = "`$manifest_count"
actual_part_entry_count="`$(find "`$parts_dir" -mindepth 1 -maxdepth 1 | wc -l)"
test "`$actual_part_entry_count" = "`$manifest_count"
reassembled="`$bundle_dir/.application-images.tar.gz.reassembled"
rm -f -- "`$reassembled"
concat_index=0
while IFS= read -r manifest_line; do
  IFS=`$'\t' read -r part_name part_size part_digest extra <<< "`$manifest_line"
  canonical_line="`$part_name"`$'\t'"`$part_size"`$'\t'"`$part_digest"
  test "`$manifest_line" = "`$canonical_line"
  expected_part_name="`$(printf 'application-images.tar.gz.part-%08d' "`$concat_index")"
  test "`$part_name" = "`$expected_part_name"
  cat -- "`$parts_dir/`$part_name" >> "`$reassembled"
  concat_index=`$((concat_index + 1))
done < "`$parts_manifest"
test "`$concat_index" = "`$manifest_count"
image_digest_count="`$(grep -Ec '^[0-9a-f]{64}[[:space:]]+\*?application-images\.tar\.gz$' "`$checksum_file")"
test "`$image_digest_count" = 1
expected_image_digest="`$(grep -E '^[0-9a-f]{64}[[:space:]]+\*?application-images\.tar\.gz$' "`$checksum_file" | awk '{print `$1}')"
printf '%s  %s\n' "`$expected_image_digest" "`$reassembled" | sha256sum --check --status
mv -f -- "`$reassembled" "`$image_archive"
(cd "`$bundle_dir" && sha256sum --check --strict SHA256SUMS)
# The installer stages an exact three-file image-bundle contract. The chunk
# transport metadata is private transfer state, not part of that reviewed
# bundle, so remove it only after the reassembled archive has passed its
# digest and manifest checks.
rm -rf -- "`$parts_dir"
rm -- "`$parts_manifest"
printf '%s  %s\n' '$archiveDigest' "`$release_archive" | sha256sum --check --status
tar --extract --file "`$release_archive" --directory '$remoteDirectory/source' infra/application
sudo env \
  AC_TARGET_ENVIRONMENT=$TargetEnvironment \
  AC_RELEASE_ID="`$release_id" \
  AC_RELEASE_ARCHIVE="`$release_archive" \
  AC_RELEASE_ARCHIVE_SHA256='$archiveDigest' \
  AC_IMAGE_BUNDLE_DIR='$remoteDirectory/bundle' \
  '$remoteDirectory/source/infra/application/scripts/install-application-release.sh'
"@
    Invoke-SshScript -Script $deployRemote
    if ($TargetEnvironment -eq "staging") {
        Test-Deployment -ProbeOAuth
    }
    else {
        Test-Deployment
    }
    Write-Output "PASS  $environmentLabel deployment and compact smoke completed for $ReleaseSha."
}
catch {
    $primaryError = $_
    throw
}
finally {
    $cleanupFailures = [System.Collections.Generic.List[object]]::new()
    try {
        if ($remoteDirectory -match "^/var/tmp/ac-release-$ReleaseSha\.[A-Za-z0-9]+$") {
            Invoke-RetriableNative `
                -FilePath $sshPath `
                -NativeArguments @($SshHost, "rm -rf -- '$remoteDirectory'") `
                -Operation "Private remote staging cleanup" | Out-Null
        }
    }
    catch {
        $cleanupFailures.Add([pscustomobject]@{ Scope = "remote"; Error = $_ })
    }
    try {
        Remove-PrivateStage -StagePath $stageDirectory
    }
    catch {
        $cleanupFailures.Add([pscustomobject]@{ Scope = "local"; Error = $_ })
    }
    if ($cleanupFailures.Count -gt 0) {
        if ($null -ne $primaryError) {
            foreach ($cleanupFailure in $cleanupFailures) {
                $cleanupDetail = Get-BoundedNativeDetail -Value $cleanupFailure.Error.Exception.Message
                $cleanupMessage = "$environmentLabel $($cleanupFailure.Scope) cleanup failed after the primary deployment error"
                if ($cleanupDetail) {
                    Write-Warning "${cleanupMessage}: $cleanupDetail"
                }
                else {
                    Write-Warning "$cleanupMessage."
                }
            }
        }
        else {
            throw $cleanupFailures[0].Error
        }
    }
}
