param(
    [ValidateSet('Room', 'Cornell', 'Arcade')][string]$Scene = 'Cornell',
    [ValidateSet('manual', 'auto', 'bake', 'load')][string]$Mode = 'manual',
    [ValidateRange(1, 65536)][int]$Samples = 2048,
    [string]$Revision = '1'
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot.TrimEnd('\')
$aliasRoot = 'F:\'

# Packman and parts of the build require a path without non-ASCII characters.
# SUBST provides an alias; all project files remain in their original folder.
if (Test-Path -LiteralPath $aliasRoot) {
    # Query the Unicode path directly; SUBST's console output can lose Chinese characters.
    if (-not ('FalcorPreview.NativeMethods' -as [type])) {
        Add-Type -Namespace FalcorPreview -Name NativeMethods -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern uint QueryDosDevice(string name, System.Text.StringBuilder target, int capacity);
'@
    }
    $mapping = New-Object System.Text.StringBuilder 4096
    $queryResult = [FalcorPreview.NativeMethods]::QueryDosDevice('F:', $mapping, $mapping.Capacity)
    $expected = '\??\' + $projectRoot
    if ($projectRoot -ine 'F:' -and ($queryResult -eq 0 -or $mapping.ToString().TrimEnd('\') -ine $expected)) {
        throw 'F: is already in use by another location. Free F: before launching this build.'
    }
} else {
    & subst F: $projectRoot
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the F: project alias.' }
}

$executable = 'F:\build\windows-vs2022\bin\Release\Mogwai.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw 'Mogwai.exe was not found. Build the Release configuration first.'
}

$scenes = @{
    Room = 'F:\media\test_scenes\grey_and_white_room\grey_and_white_room.pyscene'
    Cornell = 'F:\media\test_scenes\cornell_box.pyscene'
    Arcade = 'F:\media\Arcade\Arcade.pyscene'
}
$env:FALCOR_MEDIA_FOLDERS = 'F:\media'
$env:PROBE_GI_MODE = $Mode
$env:PROBE_GI_SAMPLES = [string]$Samples
$env:PROBE_GI_REVISION = $Revision
$env:PROBE_GI_CACHE = ''
$env:PROBE_GI_ENABLED = '1'
$launchArguments = @(
    '--device-type', 'vulkan',
    '--script', 'F:\scripts\TraditionalProbeGI.py',
    '--scene', $scenes[$Scene],
    '--width', '1280', '--height', '720',
    '--logfile', ('F:\build\probe-' + $Scene + '-' + $Mode + '.log')
)
Start-Process -FilePath $executable -ArgumentList $launchArguments `
    -WorkingDirectory 'F:\build\windows-vs2022\bin\Release' -WindowStyle Normal
