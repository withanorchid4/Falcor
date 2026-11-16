$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot.TrimEnd('\')
$aliasRoot = 'F:\'

# The official sample uses narrow-string paths. Use the same ASCII alias as Falcor.
if (Test-Path -LiteralPath $aliasRoot) {
    if (-not ('OfficialDDGILauncher.NativeMethods' -as [type])) {
        Add-Type -Namespace OfficialDDGILauncher -Name NativeMethods -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern uint QueryDosDevice(string name, System.Text.StringBuilder target, int capacity);
'@
    }
    $mapping = New-Object System.Text.StringBuilder 4096
    $queryResult = [OfficialDDGILauncher.NativeMethods]::QueryDosDevice('F:', $mapping, $mapping.Capacity)
    $expected = '\??\' + $projectRoot
    if ($projectRoot -ine 'F:' -and ($queryResult -eq 0 -or $mapping.ToString().TrimEnd('\') -ine $expected)) {
        throw 'F: is already in use by another location. Free F: before launching this build.'
    }
} else {
    & subst F: $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the F: project alias.' }
}

$officialRoot = 'F:\build\official-ddgi\RTXGI-DDGI-1.3.7'
$officialExe = 'F:\build\official-ddgi\build\samples\bin\d3d12\Release\TestHarness-D3D12.exe'
$officialConfig = Join-Path $officialRoot 'samples\test-harness\config\cornell.ini'
$workingDirectory = Join-Path $officialRoot 'bin\d3d12\Release'
foreach ($requiredPath in @($officialExe, $officialConfig, $workingDirectory)) {
    if (-not (Test-Path -LiteralPath $requiredPath)) {
        throw "Official RTXGI sample file or directory not found: $requiredPath"
    }
}

Start-Process -FilePath $officialExe -ArgumentList $officialConfig -WorkingDirectory $workingDirectory -WindowStyle Hidden
