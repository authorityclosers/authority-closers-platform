[CmdletBinding()]
param(
    [int]$Port = 3000,
    [switch]$CaptureScreenshots,
    [string]$TestFilter = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$learnerApp = Join-Path $repoRoot "apps\learner-web"

$env:AC_LEARNER_E2E_BASE_URL = "http://localhost:$Port"
$artifactDirectory = Join-Path $repoRoot ".artifacts\learner-web-qa"
New-Item -ItemType Directory -Force -Path $artifactDirectory | Out-Null
if ($CaptureScreenshots) {
    $env:AC_LEARNER_QA_SCREENSHOT_DIR = $artifactDirectory
}

Push-Location $repoRoot
$serverProcess = $null
try {
    $serverLog = Join-Path $artifactDirectory "server.stdout.log"
    $serverErrorLog = Join-Path $artifactDirectory "server.stderr.log"
    $serverArguments = @(
        "exec", "next", "dev", "--webpack", "--port", "$Port"
    )
    $serverProcess = Start-Process `
        -FilePath "pnpm.cmd" `
        -ArgumentList $serverArguments `
        -WorkingDirectory $learnerApp `
        -RedirectStandardOutput $serverLog `
        -RedirectStandardError $serverErrorLog `
        -WindowStyle Hidden `
        -PassThru

    $ready = $false
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        if ($serverProcess.HasExited) {
            throw "Learner server exited before readiness. See $serverLog and $serverErrorLog."
        }
        $tcpClient = $null
        try {
            $tcpClient = [System.Net.Sockets.TcpClient]::new()
            $tcpClient.Connect("localhost", $Port)
            if ($tcpClient.Connected) {
                $ready = $true
                break
            }
        }
        catch {
            # Next may still be starting its listener.
        }
        finally {
            if ($null -ne $tcpClient) {
                $tcpClient.Dispose()
            }
        }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ready) {
        throw "Learner server did not become HTTP-ready on port $Port. See $serverLog and $serverErrorLog."
    }

    $pytestArguments = @("-m", "e2e", "tests/e2e/test_learner_web_qa.py")
    if ($TestFilter) {
        $pytestArguments += @("-k", $TestFilter)
    }
    & uv run pytest @pytestArguments
    exit $LASTEXITCODE
}
finally {
    if ($null -ne $serverProcess -and -not $serverProcess.HasExited) {
        taskkill.exe /PID $serverProcess.Id /T /F | Out-Null
    }
    Pop-Location
}
