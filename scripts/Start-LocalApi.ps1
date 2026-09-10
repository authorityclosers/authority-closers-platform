[CmdletBinding()]
param([switch]$Stop)

# Private disposable localhost API. Leaves the existing staging UI bridge alone.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Repository '.tmp/local-platform'
$PidPath = Join-Path $Runtime 'api-process.json'
$AccountsPath = Join-Path $Runtime 'test-account.credential.xml'
$StatePath = Join-Path $Runtime 'sandbox.json'
$AvatarRoot = Join-Path $Runtime 'avatar-objects'
$Python = Join-Path $Repository '.venv/Scripts/python.exe'
$ApiPort = 8000
$FilmRoot = Join-Path $Repository 'tools/media-player-stress/.artifacts/staging-alpha-public-films-12s-v1'

foreach ($ManagedPath in @($Runtime, $PidPath, $AccountsPath, $StatePath, $AvatarRoot)) {
    $Ancestor = [IO.Path]::GetFullPath($ManagedPath)
    while ($Ancestor) {
        if ((Test-Path -LiteralPath $Ancestor) -and
            ((Get-Item -LiteralPath $Ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Local API state must not pass through a reparse point.'
        }
        $Ancestor = [IO.Path]::GetDirectoryName($Ancestor)
    }
}

if (Test-Path -LiteralPath $PidPath) {
    $Record = Get-Content -LiteralPath $PidPath -Raw | ConvertFrom-Json
    if ($Record.repository -ne $Repository) { throw 'API process record belongs to another tree.' }
    $Tracked = Get-Process -Id $Record.id -ErrorAction SilentlyContinue
    if ($Tracked -and $Tracked.StartTime.ToFileTimeUtc() -eq $Record.started_at) {
        if ($Tracked.Path -ne $Python) { throw 'Tracked API executable changed; refusing to stop it.' }
        if ($Stop) {
            Stop-Process -InputObject $Tracked
            Write-Host 'Stopped only the managed local API; database and UI are preserved.'
            return
        }
        Write-Host 'Managed local API is already running at http://127.0.0.1:8000.'
        return
    }
}
if ($Stop) { Write-Host 'No managed local API is running.'; return }
if (Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue) {
    throw 'Port 8000 is occupied; no existing process will be stopped.'
}
if (-not (Test-Path -LiteralPath $Python)) { throw 'Run uv sync before starting the local API.' }
& (Join-Path $PSScriptRoot 'Start-LocalPostgres.ps1') | Out-Null
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
if (-not (Test-Path -LiteralPath $AccountsPath)) {
    $RandomPassword = [Convert]::ToBase64String([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    $Credential = [Management.Automation.PSCredential]::new(
        'local-test-accounts', (ConvertTo-SecureString $RandomPassword -AsPlainText -Force)
    )
    $Credential | Export-Clixml -LiteralPath $AccountsPath
    $RandomPassword = $null
}
$Credential = Import-Clixml -LiteralPath $AccountsPath
$Release = (& git -C $Repository rev-parse HEAD).Trim()
if ($Release -notmatch '^[a-f0-9]{40}$') { throw 'A local source revision is required.' }
$LocalEnvironment = @{
    AC_ENVIRONMENT = 'local'
    AC_RELEASE_ID = $Release
    AC_DATABASE_URL = 'postgresql+psycopg://ac_runtime:local-runtime-only@127.0.0.1:55432/ac_local_sandbox'
    AC_DATABASE_MIGRATOR_URL = 'postgresql+psycopg://ac_migrator:local-migrator-only@127.0.0.1:55432/ac_local_sandbox'
    AC_SESSION_TOKEN_PEPPER = 'local-session-token-pepper-change-before-production'
    AC_OAUTH_TRANSACTION_SECRET = 'local-oauth-transaction-secret-change-before-production'
    AC_EMAIL_CHALLENGE_SECRET = 'local-email-challenge-secret-change-before-production'
    AC_EXTERNAL_SIDE_EFFECTS_HOLD = 'true'
    AC_EMAIL_PROVIDER = 'fake'
    AC_MEDIA_PROVIDER_ENABLED = 'false'
    AC_MEDIA_STRESS_FIXTURES_ENABLED = 'false'
    AC_MEDIA_STAGING_PUBLIC_FILMS_DELIVERY_ENABLED = 'false'
    AC_MEDIA_LOCAL_PUBLIC_FILMS_DELIVERY_ENABLED = 'false'
    AC_MEDIA_LOCAL_AVATAR_ENABLED = 'false'
    AC_MEDIA_LOCAL_AVATAR_STORAGE_ROOT = $AvatarRoot
    AC_PRACTICE_ARCADE_PREVIEW_ENABLED = 'true'
    AC_LOCAL_FILM_ROOT = $FilmRoot
    AC_PUBLIC_APP_URL = 'http://learner.localhost:3100'
    AC_ADMIN_APP_URL = 'http://admin.localhost:3101'
    AC_API_URL = 'http://127.0.0.1:8000'
    AC_INTERNAL_API_HOST = '127.0.0.1'
    AC_LEARNER_CONSENT_VERSION = 'disposable-local-test-v1'
    AC_LOCAL_TEST_PASSWORD = $Credential.GetNetworkCredential().Password
}
$Previous = @{}
try {
    foreach ($Entry in Get-ChildItem Env: | Where-Object { $_.Name -like 'AC_*' -or $_.Name -like 'PG*' }) {
        $Previous[$Entry.Name] = $Entry.Value
        # PowerShell 7.6/.NET 10 can bind $null as an empty string here.
        # The local guard rejects even empty PG names, so remove the entry.
        Remove-Item -LiteralPath ('Env:' + $Entry.Name)
    }
    foreach ($Key in $LocalEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($Key, $LocalEnvironment[$Key], 'Process')
    }
    Push-Location $Repository
    try {
        # This dedicated disposable DB accepts isolated technical catalog
        # fixtures using the existing test migration policy. No live DB or
        # previously initialized production-mode trigger is modified.
        $env:AC_ENVIRONMENT = 'test'
        & $Python -m alembic upgrade head
        $env:AC_ENVIRONMENT = 'local'
        if ($LASTEXITCODE -ne 0) { throw 'Local migrations failed; API was not started.' }
        if (Test-Path -LiteralPath $StatePath) {
            # Once users start developing, their local accounts and content
            # are not fixture-reset or recreated on each restart.
            $Sandbox = Get-Content -LiteralPath $StatePath -Raw | ConvertFrom-Json
        }
        else {
            $Summary = & $Python -m ac_platform.development.seed --acknowledge-disposable-local
            if ($LASTEXITCODE -ne 0) { throw 'Local sandbox setup failed; API was not started.' }
            $Sandbox = $Summary | ConvertFrom-Json
            $Sandbox | ConvertTo-Json | Set-Content -LiteralPath $StatePath
        }
        $env:AC_PUBLIC_LEARNER_TENANT_ID = $Sandbox.academy_tenant_id
        $env:AC_OPERATIONS_TENANT_ID = $Sandbox.operations_tenant_id
        $env:AC_MEDIA_STRESS_FIXTURES_ENABLED = 'true'
        $env:AC_MEDIA_STRESS_FIXTURES_CACHE_ROOT = $FilmRoot
        $env:AC_MEDIA_LOCAL_PUBLIC_FILMS_DELIVERY_ENABLED = 'true'
        $env:AC_MEDIA_LOCAL_AVATAR_ENABLED = 'true'
        Remove-Item Env:AC_LOCAL_TEST_PASSWORD
        # Tokens and signed media locators must never enter the HTTP access log.
        $Api = Start-Process -FilePath $Python -ArgumentList @(
            '-m', 'uvicorn', 'ac_platform.http.app:app', '--host', '127.0.0.1', '--port', "$ApiPort",
            '--no-access-log', '--loop', 'ac_platform.application.asyncio_runtime:compatible_event_loop_factory'
        ) -WorkingDirectory $Repository -WindowStyle Hidden -PassThru `
            -RedirectStandardOutput (Join-Path $Runtime 'api.stdout.log') `
            -RedirectStandardError (Join-Path $Runtime 'api.stderr.log')
        [ordered]@{
            repository = $Repository
            id = $Api.Id
            started_at = $Api.StartTime.ToFileTimeUtc()
            source_revision = $Release
        } | ConvertTo-Json | Set-Content -LiteralPath $PidPath
    }
    finally { Pop-Location }
}
finally {
    foreach ($Entry in Get-ChildItem Env: | Where-Object { $_.Name -like 'AC_*' -or $_.Name -like 'PG*' }) {
        Remove-Item -LiteralPath ('Env:' + $Entry.Name)
    }
    foreach ($Key in $Previous.Keys) {
        [Environment]::SetEnvironmentVariable($Key, $Previous[$Key], 'Process')
    }
    $LocalEnvironment.AC_LOCAL_TEST_PASSWORD = $null
    $Credential = $null
}
$Deadline = [DateTime]::UtcNow.AddSeconds(25)
while ([DateTime]::UtcNow -lt $Deadline) {
    $Api.Refresh()
    if ($Api.HasExited) { throw 'Local API exited; inspect its local error log.' }
    try {
        $Health = Invoke-RestMethod 'http://127.0.0.1:8000/health/ready' -TimeoutSec 2
        Write-Host 'Local API and database ready at http://127.0.0.1:8000. Existing UI bridge is unchanged.'
        return
    }
    catch { Start-Sleep -Milliseconds 500 }
}
throw 'Local API did not become ready; its managed process is preserved for diagnosis.'
