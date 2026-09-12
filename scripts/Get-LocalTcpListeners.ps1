# Read the operating system TCP table without the Windows CIM provider.
# Errors propagate: a failed inspection is never treated as a free port.
function Get-LocalTcpListeners {
    [CmdletBinding()]
    param([ValidateRange(1, 65535)][int[]]$Port = @())

    $Endpoints = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
    foreach ($Endpoint in $Endpoints) {
        if ($Port.Count -eq 0 -or $Endpoint.Port -in $Port) {
            [pscustomobject]@{
                LocalAddress = $Endpoint.Address.ToString()
                LocalPort = $Endpoint.Port
            }
        }
    }
}
