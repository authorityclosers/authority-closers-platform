[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{40}$')][string]$ReleaseSha,
    [Parameter(Mandatory)][ValidatePattern('^[a-f0-9]{64}$')][string]$ArchiveSha256
)

# Uses a pre-installed, reviewed scanner release. This never installs services,
# changes DNS, sends media files, or stops an unknown process.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Repository '.tmp/local-platform'
$RecordPath = Join-Path $Runtime 'scanner-tunnel.json'
$ProofPath = Join-Path $Runtime 'studio-video-scanner-readiness.json'
$Ssh = (Get-Command ssh.exe -ErrorAction Stop).Source
$LogPath = Join-Path $Runtime 'scanner-tunnel.stderr.log'
foreach ($ManagedPath in @($Runtime, $RecordPath, $ProofPath, $LogPath)) {
    $Ancestor = [IO.Path]::GetFullPath($ManagedPath)
    while ($Ancestor) {
        if ((Test-Path -LiteralPath $Ancestor) -and
            ((Get-Item -LiteralPath $Ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Scanner state cannot pass through a reparse point.'
        }
        $Ancestor = [IO.Path]::GetDirectoryName($Ancestor)
    }
}
New-Item -ItemType Directory -Path $Runtime -Force | Out-Null
$Tunnel = $null
if (Test-Path -LiteralPath $RecordPath) {
    $Record = Get-Content -LiteralPath $RecordPath -Raw | ConvertFrom-Json
    if ($Record.repository -ne $Repository) { throw 'Scanner tunnel belongs to another tree.' }
    $Tracked = Get-Process -Id $Record.id -ErrorAction SilentlyContinue
    if ($Tracked -and $Tracked.StartTime.ToFileTimeUtc() -eq $Record.started_at) {
        if ($Tracked.Path -ne $Ssh) { throw 'Scanner tunnel executable changed.' }
        $Tunnel = $Tracked
    }
}
if (-not $Tunnel) {
    if (Get-NetTCPConnection -LocalPort 13310 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Scanner port is occupied by an untracked process; nothing was stopped.'
    }
    $Tunnel = Start-Process -FilePath $Ssh -WindowStyle Hidden -PassThru -ArgumentList @(
        '-N', '-T', '-o', 'BatchMode=yes', '-o', 'ExitOnForwardFailure=yes',
        '-o', 'ServerAliveInterval=20', '-o', 'ServerAliveCountMax=3',
        '-L', '127.0.0.1:13310:127.0.0.1:13310', 'ac'
    ) -RedirectStandardError $LogPath
    @{ repository = $Repository; id = $Tunnel.Id; started_at = $Tunnel.StartTime.ToFileTimeUtc() } |
        ConvertTo-Json | Set-Content -LiteralPath $RecordPath
}
$Deadline = [DateTime]::UtcNow.AddSeconds(20)
do {
    $Tunnel.Refresh()
    if ($Tunnel.HasExited) { throw 'Scanner tunnel exited; no upload capability was enabled.' }
    $Listener = Get-NetTCPConnection -LocalPort 13310 -State Listen -ErrorAction SilentlyContinue
    if ($Listener) {
        if (@($Listener | Where-Object { $_.OwningProcess -ne $Tunnel.Id -or $_.LocalAddress -ne '127.0.0.1' }).Count) {
            throw 'Scanner listener does not match the managed loopback tunnel.'
        }
        break
    }
    Start-Sleep -Milliseconds 200
} while ([DateTime]::UtcNow -lt $Deadline)
if (-not $Listener) { throw 'Scanner tunnel did not start.' }
$RemoteRoot = '/srv/authority-closers/media-safety'
$Proof = & $Ssh -o BatchMode=yes -o ConnectTimeout=10 ac `
    "sudo -n python3 $RemoteRoot/releases/$ReleaseSha/manage.py prove $RemoteRoot/archives/$ReleaseSha.tar $ReleaseSha $ArchiveSha256"
if ($LASTEXITCODE -ne 0) { throw 'Scanner policy proof failed. Existing proof was not replaced.' }
$Parsed = ($Proof -join "`n") | ConvertFrom-Json
if ($Parsed.schema_version -ne 'ac.local-studio-video-scanner-readiness.v1' -or
    $Parsed.host -ne '127.0.0.1' -or $Parsed.port -ne 13310 -or
    [DateTimeOffset]::Parse($Parsed.expires_at) -le [DateTimeOffset]::UtcNow) {
    throw 'Scanner returned invalid readiness evidence.'
}
# Generated runtime evidence, not a source-file edit. The app independently
# validates every field and probes this exact tunnel before accepting uploads.
$Parsed | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $ProofPath -Encoding utf8NoBOM
Write-Host 'Private scanner connection and fresh readiness proof are available for local Studio uploads.'
