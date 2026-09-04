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
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"

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
    if ([double]$row.completion_rate_pct -lt 0 -or [double]$row.completion_rate_pct -gt 100) {
        throw "Completion rate is outside [0,100] for $($row.scenario_id)."
    }
    if ([double]$row.sla_met_pct -lt 0 -or [double]$row.sla_met_pct -gt 100) {
        throw "SLA rate is outside [0,100] for $($row.scenario_id)."
    }
}

Write-Output "academy-capacity-simulation: PASS"
Write-Output "binary: $binary"
Write-Output "results: $csvOutput"
