[CmdletBinding()]
param(
    [ValidateRange(1024, 65535)] [int]$Port = 55432,
    [switch]$Stop
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Local-RuntimeBootstrap.ps1')
if (Invoke-LocalRuntimeRelaunch -ScriptPath $PSCommandPath -Parameters $PSBoundParameters) { return }

# Disposable localhost development only. Never accepts a remote host, an
# arbitrary data directory, a production connection string, or an existing cluster.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Get-LocalTcpListeners.ps1')
if (-not $IsWindows) { throw 'This portable runtime launcher requires Windows PowerShell 7.' }

$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$StateRoot = Join-Path $RepositoryRoot '.tmp/local-platform'
$DataDirectory = Join-Path $StateRoot 'postgres'
$MarkerPath = Join-Path $StateRoot 'postgres-cluster.json'
$RoleContract = Join-Path $RepositoryRoot 'infra/local/postgres/init/001-roles.sql'
$RuntimeRoot = Join-Path $env:LOCALAPPDATA 'AuthorityClosers/local-postgres-runtime'
$VersionRoot = Join-Path $RuntimeRoot 'postgresql-18.6-3'
$BinaryRoot = Join-Path $VersionRoot 'pgsql/bin'
$ArchivePath = Join-Path $RuntimeRoot 'postgresql-18.6-3-windows-x64-binaries.zip'
$ArchiveUrl = 'https://get.enterprisedb.com/postgresql/postgresql-18.6-3-windows-x64-binaries.zip'
# Observed from the official HTTPS distribution, not a publisher signature.
$ArchiveHash = '59F8CE701C63C2ED623C665A5E51B3EF6F2E37CCF837B68FFEED0742D0AE6ABD'
$BinaryHashes = @{
    'postgres' = '45E0016B7D196ABB35F3060F906314BE42B1E8C29B35D56F840AE00A2C703F29'
    'initdb' = 'AE513176CF6DCC6E9817BD7EE1DF630E8E5B4F540468E3B0D602FFD0FD3A801A'
    'pg_ctl' = '11DA1CDE9C0A48DA53C72B20D1AFDF87BDD3EC7AF21B12211853773BC3713FFE'
    'psql' = '945EB0BBF8475A7FB0C863D85E36F2E15CF6B2D9FADB4D617BE4E59D4BB17BB0'
}

function Assert-NoReparseAncestor([string]$Path) {
    $Candidate = [IO.Path]::GetFullPath($Path)
    while ($Candidate) {
        if (Test-Path -LiteralPath $Candidate) {
            if ((Get-Item -LiteralPath $Candidate).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw 'The managed runtime and data paths must not contain reparse points.'
            }
        }
        $Candidate = [IO.Path]::GetDirectoryName($Candidate)
    }
}

function Assert-Runtime {
    New-Item -ItemType Directory -Path $RuntimeRoot -Force | Out-Null
    if (-not (Test-Path -LiteralPath $ArchivePath)) {
        Write-Host 'Downloading the pinned official PostgreSQL 18.6 portable runtime.'
        Invoke-WebRequest -Uri $ArchiveUrl -OutFile $ArchivePath -TimeoutSec 300
    }
    if ((Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash -ne $ArchiveHash) {
        throw 'Portable PostgreSQL archive checksum does not match the reviewed runtime.'
    }
    if (-not (Test-Path -LiteralPath $VersionRoot)) {
        New-Item -ItemType Directory -Path $VersionRoot | Out-Null
        $Archive = [IO.Compression.ZipFile]::OpenRead($ArchivePath)
        try {
            $Prefix = [IO.Path]::GetFullPath($VersionRoot) + [IO.Path]::DirectorySeparatorChar
            foreach ($Entry in $Archive.Entries) {
                if ($Entry.Name -and ($Entry.FullName -match '^pgsql/(bin|lib|share)/' -or
                    $Entry.FullName -in @('pgsql/server_license.txt', 'pgsql/commandlinetools_3rd_party_licenses.txt'))) {
                    $Destination = [IO.Path]::GetFullPath((Join-Path $VersionRoot $Entry.FullName))
                    if (-not $Destination.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) {
                        throw 'Archive entry escapes the isolated runtime directory.'
                    }
                    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($Destination)) -Force | Out-Null
                    [IO.Compression.ZipFileExtensions]::ExtractToFile($Entry, $Destination, $false)
                }
            }
        }
        finally { $Archive.Dispose() }
    }
    foreach ($Name in $BinaryHashes.Keys) {
        $Executable = Join-Path $BinaryRoot ($Name + '.exe')
        Assert-NoReparseAncestor $Executable
        if ((Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash -ne $BinaryHashes[$Name]) {
            throw "Portable PostgreSQL executable checksum failed: $Name"
        }
    }
}

function Invoke-Pg {
    param([string]$Name, [string[]]$Arguments, [string]$Password = '', [string]$InputText = '')
    $Info = [Diagnostics.ProcessStartInfo]::new()
    $Info.FileName = Join-Path $BinaryRoot ($Name + '.exe')
    $Info.WorkingDirectory = $BinaryRoot
    $Info.UseShellExecute = $false
    $Info.CreateNoWindow = $true
    $Info.RedirectStandardOutput = $true
    $Info.RedirectStandardError = $true
    $Info.RedirectStandardInput = $true
    # Do not inherit an unrelated host, service, password file or PGOPTIONS.
    foreach ($Key in @($Info.Environment.Keys)) {
        if ($Key.StartsWith('PG', [StringComparison]::OrdinalIgnoreCase)) {
            $Info.Environment.Remove($Key) | Out-Null
        }
    }
    if ($Password) { $Info.Environment['PGPASSWORD'] = $Password }
    foreach ($Argument in $Arguments) { $Info.ArgumentList.Add($Argument) }
    $Process = [Diagnostics.Process]::new()
    $Process.StartInfo = $Info
    try {
        $Process.Start() | Out-Null
        $OutputTask = $Process.StandardOutput.ReadToEndAsync()
        $ErrorTask = $Process.StandardError.ReadToEndAsync()
        if ($InputText) { $Process.StandardInput.WriteLine($InputText) }
        $Process.StandardInput.Close()
        if (-not $Process.WaitForExit(30000)) {
            $Process.Kill($true)
            throw "Local PostgreSQL command timed out: $Name"
        }
        # pg_ctl's detached Windows server can retain inherited pipe handles
        # after the controller exits. Do not wait indefinitely for pipe EOF.
        $Output = ''
        if ($OutputTask.Wait(2000)) { $Output = $OutputTask.GetAwaiter().GetResult() }
        if ($ErrorTask.Wait(2000)) { $null = $ErrorTask.GetAwaiter().GetResult() }
        if ($Process.ExitCode -ne 0) {
            # Never echo SQL, password material, inherited environment or raw stderr.
            throw "Local PostgreSQL command failed: $Name (exit $($Process.ExitCode))."
        }
        return $Output.Trim()
    }
    finally { $Process.Dispose() }
}

function Invoke-LocalQuery([string]$Role, [string]$Database, [string]$Sql) {
    $Passwords = @{
        ac_owner = 'local-owner-only'
        ac_migrator = 'local-migrator-only'
        ac_runtime = 'local-runtime-only'
        ac_backup = 'local-backup-only'
    }
    return Invoke-Pg -Name psql -Arguments @(
        '-X', '-w', '-h', '127.0.0.1', '-p', "$Port", '-U', $Role, '-d', $Database,
        '-v', 'ON_ERROR_STOP=1', '-A', '-t'
    ) -Password $Passwords[$Role] -InputText $Sql
}

Assert-NoReparseAncestor $StateRoot
Assert-NoReparseAncestor $RuntimeRoot
Assert-NoReparseAncestor $RoleContract
if (-not (Test-Path -LiteralPath $RoleContract)) { throw 'The local role initialization contract is missing.' }
$RoleContractHash = (Get-FileHash -LiteralPath $RoleContract -Algorithm SHA256).Hash
$Marker = $null
if (Test-Path -LiteralPath $MarkerPath) {
    Assert-NoReparseAncestor $MarkerPath
    $Marker = Get-Content -LiteralPath $MarkerPath -Raw | ConvertFrom-Json -AsHashtable
    if ($Marker.repository -ne $RepositoryRoot -or $Marker.data_directory -ne $DataDirectory -or
        $Marker.port -ne $Port -or $Marker.runtime_sha256 -ne $ArchiveHash -or
        $Marker.role_contract_sha256 -ne $RoleContractHash) {
        throw 'Existing local cluster marker does not match this worktree/runtime/role contract.'
    }
}
elseif (Test-Path -LiteralPath $DataDirectory) {
    throw 'Refusing to adopt an existing unmarked PostgreSQL directory.'
}
if ($Stop -and -not $Marker) { throw 'No managed local PostgreSQL cluster exists to stop.' }
Assert-Runtime
if ($Stop) {
    $null = Invoke-Pg -Name pg_ctl -Arguments @('stop', '-D', $DataDirectory, '-m', 'fast', '-w', '-t', '20')
    Write-Host 'Stopped only the managed localhost PostgreSQL cluster. Its data remains preserved.'
    return
}

New-Item -ItemType Directory -Path $StateRoot -Force | Out-Null
$Listeners = @(Get-LocalTcpListeners -Port $Port)
if ($Listeners.Count -gt 0 -and -not $Marker) {
    throw 'The requested port is already occupied; no existing service will be changed.'
}
if (-not $Marker) {
    $PasswordPath = Join-Path $StateRoot 'postgres-init-password.tmp'
    if (Test-Path -LiteralPath $PasswordPath) { throw 'A prior initialization file exists; inspect it first.' }
    try {
        [IO.File]::WriteAllText($PasswordPath, 'local-owner-only', [Text.Encoding]::ASCII)
        $null = Invoke-Pg -Name initdb -Arguments @(
            '-D', $DataDirectory, '-U', 'ac_owner', '--encoding=UTF8', '--no-locale',
            '--auth=scram-sha-256', "--pwfile=$PasswordPath",
            '-c', 'listen_addresses=127.0.0.1', '-c', "port=$Port"
        )
    }
    finally { if (Test-Path -LiteralPath $PasswordPath) { Remove-Item -LiteralPath $PasswordPath } }
    $Marker = [ordered]@{
        repository = $RepositoryRoot
        data_directory = $DataDirectory
        port = $Port
        runtime_sha256 = $ArchiveHash
        role_contract_sha256 = $RoleContractHash
        initialized = $false
    }
    [IO.File]::WriteAllText($MarkerPath, ($Marker | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}
Assert-NoReparseAncestor $DataDirectory
if ($Listeners.Count -eq 0) {
    $LogPath = Join-Path $StateRoot 'postgres.log'
    $null = Invoke-Pg -Name pg_ctl -Arguments @(
        'start', '-D', $DataDirectory, '-l', $LogPath, '-w', '-t', '20',
        '-o', "-h 127.0.0.1 -p $Port"
    )
}
$ActualDirectory = Invoke-LocalQuery ac_owner postgres "SHOW data_directory;"
if ([IO.Path]::GetFullPath($ActualDirectory) -ne [IO.Path]::GetFullPath($DataDirectory)) {
    throw 'The listener is not the managed local cluster; no schema changes were made.'
}
if (-not $Marker.initialized) {
    $Existing = Invoke-LocalQuery ac_owner postgres "SELECT count(*) FROM pg_database WHERE datname='ac_platform';"
    if ($Existing -ne '0') { throw 'An incomplete initialization already created the database; inspect without overwriting it.' }
    $null = Invoke-LocalQuery ac_owner postgres 'CREATE DATABASE ac_platform OWNER ac_owner;'
    $null = Invoke-Pg -Name psql -Arguments @(
        '-X', '-w', '-h', '127.0.0.1', '-p', "$Port", '-U', 'ac_owner', '-d', 'ac_platform',
        '-v', 'ON_ERROR_STOP=1', '--single-transaction', '-f', $RoleContract
    ) -Password 'local-owner-only'
    $Marker.initialized = $true
    [IO.File]::WriteAllText($MarkerPath, ($Marker | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}
# Preserve ac_platform's local publication-policy migration. A separate NEW
# database is the only target for the explicitly test-configured API sandbox.
if (-not $Marker['sandbox_initialized']) {
    $ExistingSandbox = Invoke-LocalQuery ac_owner postgres "SELECT count(*) FROM pg_database WHERE datname='ac_local_sandbox';"
    if ($ExistingSandbox -ne '0') {
        throw 'An unmarked sandbox database already exists; inspect without modifying it.'
    }
    $RoleSource = Get-Content -LiteralPath $RoleContract -Raw
    $GrantStart = $RoleSource.IndexOf('REVOKE CONNECT ON DATABASE ac_platform FROM PUBLIC;', [StringComparison]::Ordinal)
    if ($GrantStart -lt 0) { throw 'The reviewed local database grant contract is unavailable.' }
    # Reuse the exact checked-in database/schema/default-privilege statements,
    # not its CREATE ROLE statements. The roles already exist in this cluster.
    $SandboxGrants = $RoleSource.Substring($GrantStart).Replace('ON DATABASE ac_platform', 'ON DATABASE ac_local_sandbox')
    if ($SandboxGrants -match '(?i)\b(?:CREATE|ALTER|DROP)\s+ROLE\b') {
        throw 'Sandbox initialization must not change existing cluster roles.'
    }
    $null = Invoke-LocalQuery ac_owner postgres 'CREATE DATABASE ac_local_sandbox OWNER ac_owner;'
    $null = Invoke-Pg -Name psql -Arguments @(
        '-X', '-w', '-h', '127.0.0.1', '-p', "$Port", '-U', 'ac_owner', '-d', 'ac_local_sandbox',
        '-v', 'ON_ERROR_STOP=1', '--single-transaction', '-f', '-'
    ) -Password 'local-owner-only' -InputText $SandboxGrants
    $Marker['sandbox_initialized'] = $true
    [IO.File]::WriteAllText($MarkerPath, ($Marker | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
}
foreach ($Role in @('ac_migrator', 'ac_runtime', 'ac_backup')) {
    $Result = Invoke-LocalQuery $Role ac_platform 'SELECT current_user;'
    if ($Result -ne $Role) { throw 'Local database role readiness failed.' }
    $SandboxResult = Invoke-LocalQuery $Role ac_local_sandbox 'SELECT current_user;'
    if ($SandboxResult -ne $Role) { throw 'Local sandbox database role readiness failed.' }
}
$Listeners = @(Get-LocalTcpListeners -Port $Port)
if ($Listeners.Count -ne 1 -or $Listeners[0].LocalAddress -ne '127.0.0.1') {
    throw 'The managed local database is not exclusively loopback-bound.'
}
[pscustomobject]@{
    ready = $true
    host = '127.0.0.1'
    port = $Port
    database = 'ac_platform'
    test_content_database = 'ac_local_sandbox'
    runtime_role_verified = $true
    migrator_role_verified = $true
    backup_role_verified = $true
    data_directory = $DataDirectory
} | ConvertTo-Json
