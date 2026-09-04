[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$source = Join-Path $repoRoot "tools\simulations\academy_capacity_sim.cpp"
$scenarioFile = Join-Path $repoRoot "tools\simulations\academy_capacity_scenarios.csv"
$outputDirectory = Join-Path $repoRoot ".tmp\academy-capacity-simulation"
$binary = Join-Path $outputDirectory "academy_capacity_sim.exe"
$objectFile = Join-Path $outputDirectory "academy_capacity_sim.obj"
$csvOutput = Join-Path $outputDirectory "results.csv"
$markdownOutput = Join-Path $outputDirectory "results.md"
$publishedCsv = Join-Path $repoRoot "docs\research\academy-capacity-simulation-results-2026-09-04.csv"
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
$expectedCompilerVersionPrefix = "19.44."

if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
    throw "Visual Studio locator not found: $vswhere"
}

$installationPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $installationPath) {
    throw "A Visual Studio installation with the C++ x64 toolchain is required."
}

$developerShell = Join-Path $installationPath "Common7\Tools\VsDevCmd.bat"
if (-not (Test-Path -LiteralPath $developerShell -PathType Leaf)) {
    throw "Visual Studio developer shell not found: $developerShell"
}

New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

$compilerVersionCommand = 'call "{0}" -arch=x64 -host_arch=x64 >nul && cl /Bv' -f $developerShell
$compilerBanner = (& cmd.exe /d /s /c $compilerVersionCommand 2>&1 | Out-String)
$compilerVersionMatch = [regex]::Match($compilerBanner, 'Compiler Version (?<version>[0-9.]+) for x64')
if (-not $compilerVersionMatch.Success) {
    throw "MSVC compiler version could not be parsed."
}
$compilerVersion = $compilerVersionMatch.Groups['version'].Value
if (-not $compilerVersion.StartsWith($expectedCompilerVersionPrefix, [StringComparison]::Ordinal)) {
    throw "Published results require MSVC $expectedCompilerVersionPrefix*; found $compilerVersion. Re-baseline deliberately before accepting another standard-library implementation."
}

$compileCommand = 'call "{0}" -arch=x64 -host_arch=x64 >nul && cl /nologo /std:c++17 /EHsc /W4 /WX /O2 "{1}" /Fo:"{2}" /Fe:"{3}"' -f $developerShell, $source, $objectFile, $binary
& cmd.exe /d /s /c $compileCommand
if ($LASTEXITCODE -ne 0) {
    throw "C++ compilation failed with exit code $LASTEXITCODE."
}

& $binary --self-test
if ($LASTEXITCODE -ne 0) {
    throw "Simulator self-test failed with exit code $LASTEXITCODE."
}

& $binary --scenarios $scenarioFile --csv $csvOutput --markdown $markdownOutput
if ($LASTEXITCODE -ne 0) {
    throw "Scenario simulation failed with exit code $LASTEXITCODE."
}

$rows = Import-Csv -LiteralPath $csvOutput
$publishedRows = Import-Csv -LiteralPath $publishedCsv
if ($rows.Count -ne 5) {
    throw "Expected five scenario result rows; found $($rows.Count)."
}

$expectedScenarios = @(
    "ac_dipak_pilot_25",
    "ac_cohort_100",
    "ac_launch_250",
    "future_5_tenants_supported",
    "future_5_tenants_understaffed"
)
$actualScenarioList = @($rows.scenario_id) -join ","
$expectedScenarioList = $expectedScenarios -join ","
if ($actualScenarioList -ne $expectedScenarioList) {
    throw "Scenario output order or identifiers changed unexpectedly."
}

foreach ($row in $rows) {
    $completionRate = [double]$row.completion_rate_pct
    $slaRate = [double]$row.sla_met_pct
    if (-not [double]::IsFinite($completionRate) -or $completionRate -lt 0 -or $completionRate -gt 100) {
        throw "Completion rate is outside [0,100] for $($row.scenario_id)."
    }
    if (-not [double]::IsFinite($slaRate) -or $slaRate -lt 0 -or $slaRate -gt 100) {
        throw "SLA rate is outside [0,100] for $($row.scenario_id)."
    }
}

$generatedHeader = Get-Content -LiteralPath $csvOutput -TotalCount 1
$publishedHeader = Get-Content -LiteralPath $publishedCsv -TotalCount 1
if ($generatedHeader -cne $publishedHeader -or $publishedRows.Count -ne $rows.Count) {
    throw "Generated results do not match the published CSV contract."
}
$columns = @($rows[0].PSObject.Properties.Name)
for ($rowIndex = 0; $rowIndex -lt $rows.Count; $rowIndex++) {
    foreach ($column in $columns) {
        if ([string]$rows[$rowIndex].$column -cne [string]$publishedRows[$rowIndex].$column) {
            throw "Published result drift at row $($rowIndex + 1), column $column."
        }
    }
}

function Assert-RejectedScenario {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Row
    )

    $invalidScenario = Join-Path $outputDirectory "$Name.csv"
    $invalidCsv = Join-Path $outputDirectory "$Name-results.csv"
    $invalidMarkdown = Join-Path $outputDirectory "$Name-results.md"
    @(
        $generatedHeader
        $Row
    ) | Set-Content -LiteralPath $invalidScenario -Encoding utf8NoBOM

    & $binary --scenarios $invalidScenario --csv $invalidCsv --markdown $invalidMarkdown 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        throw "Invalid scenario '$Name' was accepted."
    }
}

Assert-RejectedScenario -Name "invalid-nan" -Row "invalid_nan,1,25,14,42,12,nan,0.95,0.20,0.35,12,0.35,8,1,2,6,24,18,1,1"
Assert-RejectedScenario -Name "invalid-work-cap" -Row "invalid_work_cap,1000,100000,3650,3650,1000,0.85,0.95,0.20,0.35,12,0.35,8,10000,15,7,24,1000000,100000,1"

Write-Output "academy-capacity-simulation: PASS"
Write-Output "compiler: MSVC $compilerVersion"
Write-Output "binary: $binary"
Write-Output "results: $csvOutput"
Write-Output "published-sha256: $((Get-FileHash -LiteralPath $publishedCsv -Algorithm SHA256).Hash.ToLowerInvariant())"
