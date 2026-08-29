$ErrorActionPreference = "Stop"
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$failures = 0

Get-ChildItem -LiteralPath $repositoryRoot -Filter "*.ps1" -File -Recurse | ForEach-Object {
    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($_.FullName, [ref]$tokens, [ref]$errors)
    foreach ($parseError in @($errors)) {
        Write-Error "$($_.FullName):$($parseError.Extent.StartLineNumber): $($parseError.Message)" -ErrorAction Continue
        $failures++
    }
}

if ($failures -ne 0) {
    throw "$failures PowerShell parse error(s) found."
}

Write-Output "PASS  PowerShell syntax validation completed."
