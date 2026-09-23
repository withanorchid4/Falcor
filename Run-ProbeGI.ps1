param(
    [ValidateSet('Room', 'Cornell', 'Arcade')][string]$Scene = 'Cornell',
    [ValidateSet('manual', 'auto', 'bake', 'load')][string]$Mode = 'manual',
    [ValidateRange(1, 65536)][int]$Samples = 2048,
    [string]$Revision = '1'
)
$ErrorActionPreference = 'Stop'
# Compatibility shortcut: same application and graphs, starting on Probe GI.
& (Join-Path $PSScriptRoot 'Run-Falcor.ps1') -Renderer Probe -Scene $Scene -Mode $Mode -Samples $Samples -Revision $Revision
