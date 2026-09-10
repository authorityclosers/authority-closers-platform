# This file must also parse and run in Windows PowerShell 5.1. It only selects
# already-installed tools. It does not elevate, install, or change machine state.

function Invoke-LocalRuntimeRelaunch {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][System.Collections.IDictionary]$Parameters
    )

    if ($PSVersionTable.PSVersion -ge [version]'7.4') { return $false }

    $Candidates = @()
    foreach ($InstallRoot in @($env:ProgramW6432, $env:ProgramFiles)) {
        if ($InstallRoot) { $Candidates += Join-Path $InstallRoot 'PowerShell/7/pwsh.exe' }
    }
    $Available = Get-Command pwsh.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($Available) { $Candidates += $Available.Source }
    $PowerShellPath = $null
    foreach ($Candidate in @($Candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { continue }
        $ReportedVersion = & $Candidate -NoProfile -NonInteractive -Command '$PSVersionTable.PSVersion.ToString()'
        $ParsedVersion = $null
        if ($LASTEXITCODE -eq 0 -and [version]::TryParse([string]$ReportedVersion, [ref]$ParsedVersion) -and
            $ParsedVersion -ge [version]'7.4') {
            $PowerShellPath = $Candidate
            break
        }
    }
    if (-not $PowerShellPath) {
        throw 'Install PowerShell 7.4 or later, then run this same launcher again. No administrator shell is required for normal local startup.'
    }

    # Forward argument values as native arguments, never as generated code.
    # Only these typed launcher parameters are allowed across the shell boundary.
    $ForwardArguments = @('-NoProfile', '-NonInteractive', '-File', $ScriptPath)
    foreach ($Name in $Parameters.Keys) {
        $Value = $Parameters[$Name]
        switch -Exact ($Name) {
            { $_ -in @('Stop', 'StudioVideo') } {
                if ($Value -isnot [System.Management.Automation.SwitchParameter] -and $Value -isnot [bool]) {
                    throw "The $Name launcher argument must be a switch."
                }
                $ForwardArguments += '-{0}:${1}' -f $Name, ([bool]$Value).ToString().ToLowerInvariant()
            }
            'SurfaceSelection' {
                if ($Value -notin @('all', 'both', 'learner', 'admin', 'coach')) {
                    throw 'The local app selection is invalid.'
                }
                $ForwardArguments += @('-SurfaceSelection', [string]$Value)
            }
            'Port' {
                if ($Value -isnot [int] -or $Value -lt 1024 -or $Value -gt 65535) {
                    throw 'The local database port is invalid.'
                }
                $ForwardArguments += @('-Port', $Value.ToString([Globalization.CultureInfo]::InvariantCulture))
            }
            default { throw "Unsupported local launcher argument: $Name" }
        }
    }
    Write-Host 'Using the installed PowerShell 7 runtime for local startup.'
    & $PowerShellPath @ForwardArguments | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "Local startup failed in PowerShell 7 (exit $LASTEXITCODE). See the preceding error." }
    return $true
}

function Get-LocalNodeExecutable {
    [CmdletBinding()]
    param()

    $Candidates = @()
    $Available = Get-Command node.exe -CommandType Application -ErrorAction SilentlyContinue
    if ($Available) { $Candidates += $Available.Source }
    if ($env:USERPROFILE) {
        $Candidates += Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
    }
    foreach ($Candidate in @($Candidates | Select-Object -Unique)) {
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) { continue }
        $ReportedVersion = & $Candidate --version
        if ($LASTEXITCODE -eq 0 -and [string]$ReportedVersion -match '^v24\.\d+\.\d+\s*$') {
            return (Resolve-Path -LiteralPath $Candidate).Path
        }
    }
    throw 'Node 24 is required. Install it on PATH or restore the existing Codex Node runtime, then run this same launcher again.'
}
