[CmdletBinding()]
param([Parameter(Mandatory)][ValidatePattern('^[a-z0-9-]{1,48}$')][string]$Label)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$Repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Runtime = Join-Path $Repository '.tmp/local-platform'
$Marker = Get-Content -LiteralPath (Join-Path $Runtime 'postgres-cluster.json') -Raw | ConvertFrom-Json
if ($Marker.repository -ne $Repository -or $Marker.port -ne 55432 -or -not $Marker.sandbox_initialized) {
    throw 'Only the marked disposable local sandbox can be backed up.'
}
$BackupDirectory = Join-Path $Runtime 'backups'
New-Item -ItemType Directory -Path $BackupDirectory -Force | Out-Null
$Archive = Join-Path $BackupDirectory ($Label + '-' + [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ') + '.dump')
foreach ($Target in @($BackupDirectory, $Archive)) {
    $Ancestor = [IO.Path]::GetFullPath($Target)
    if (-not $Ancestor.StartsWith($Runtime + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Backup target must stay inside the local runtime.'
    }
    while ($Ancestor) {
        if ((Test-Path -LiteralPath $Ancestor) -and ((Get-Item -LiteralPath $Ancestor).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw 'Backup target cannot pass through a reparse point.'
        }
        $Ancestor = [IO.Path]::GetDirectoryName($Ancestor)
    }
}
if (Test-Path -LiteralPath $Archive) { throw 'Backup target already exists.' }
$BinaryRoot = Join-Path $env:LOCALAPPDATA 'AuthorityClosers/local-postgres-runtime/postgresql-18.6-3/pgsql/bin'
$PreviousPassword = [Environment]::GetEnvironmentVariable('PGPASSWORD', 'Process')
try {
    $env:PGPASSWORD = 'local-backup-only'
    & (Join-Path $BinaryRoot 'pg_dump.exe') -h 127.0.0.1 -p 55432 -U ac_backup -d ac_local_sandbox -Fc -f $Archive
    if ($LASTEXITCODE -ne 0) { throw 'Local backup failed; any partial archive is preserved for diagnosis.' }
    $Entries = & (Join-Path $BinaryRoot 'pg_restore.exe') --list $Archive
    if ($LASTEXITCODE -ne 0) { throw 'Backup archive could not be listed.' }
    [ordered]@{ archive=$Archive; bytes=(Get-Item -LiteralPath $Archive).Length; sha256=(Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash; archive_entries=$Entries.Count } | ConvertTo-Json
}
finally { [Environment]::SetEnvironmentVariable('PGPASSWORD', $PreviousPassword, 'Process') }
