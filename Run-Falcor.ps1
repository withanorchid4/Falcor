param(
    [string]$Scene = '',
    [ValidateSet('vulkan', 'd3d12')]
    [string]$Device = 'd3d12',
    [ValidateSet('PathTracer', 'DDGIHalf', 'Probe', 'DDGI')]
    [string]$Renderer = 'PathTracer',
    [ValidateSet('manual', 'auto', 'bake', 'load')][string]$Mode = 'manual',
    [ValidateRange(1, 65536)][int]$Samples = 2048,
    [string]$Revision = '1'
)

$ErrorActionPreference = 'Stop'

# With no scene supplied, use this as the single interactive entry point.
if (-not $PSBoundParameters.ContainsKey('Scene')) {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [System.Windows.Forms.Application]::EnableVisualStyles()

    $form = New-Object System.Windows.Forms.Form
    $form.Text = 'Falcor Scene Launcher'
    $form.StartPosition = 'CenterScreen'
    $form.FormBorderStyle = 'FixedDialog'
    $form.MaximizeBox = $false
    $form.MinimizeBox = $false
    $form.ClientSize = New-Object System.Drawing.Size(380, 190)

    $sceneLabel = New-Object System.Windows.Forms.Label
    $sceneLabel.Text = 'Scene'
    $sceneLabel.Location = New-Object System.Drawing.Point(20, 24)
    $sceneLabel.Size = New-Object System.Drawing.Size(80, 24)
    $form.Controls.Add($sceneLabel)

    $sceneBox = New-Object System.Windows.Forms.ComboBox
    $sceneBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
    [void]$sceneBox.Items.Add('Room')
    [void]$sceneBox.Items.Add('Cornell')
    [void]$sceneBox.Items.Add('CornellLambert')
    [void]$sceneBox.Items.Add('Arcade')
    [void]$sceneBox.Items.Add('Bistro')
    $sceneBox.SelectedItem = 'Bistro'
    $sceneBox.Location = New-Object System.Drawing.Point(110, 20)
    $sceneBox.Size = New-Object System.Drawing.Size(240, 28)
    $form.Controls.Add($sceneBox)

    $rendererLabel = New-Object System.Windows.Forms.Label
    $rendererLabel.Text = 'Renderer'
    $rendererLabel.Location = New-Object System.Drawing.Point(20, 66)
    $rendererLabel.Size = New-Object System.Drawing.Size(80, 24)
    $form.Controls.Add($rendererLabel)

    $rendererBox = New-Object System.Windows.Forms.ComboBox
    $rendererBox.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
    [void]$rendererBox.Items.Add('DDGI')
    [void]$rendererBox.Items.Add('PathTracer')
    [void]$rendererBox.Items.Add('Probe')
    [void]$rendererBox.Items.Add('DDGIHalf')
    $defaultRenderer = 'DDGI'
    if ($PSBoundParameters.ContainsKey('Renderer')) { $defaultRenderer = $Renderer }
    $rendererBox.SelectedItem = $defaultRenderer
    $rendererBox.Location = New-Object System.Drawing.Point(110, 62)
    $rendererBox.Size = New-Object System.Drawing.Size(240, 28)
    $form.Controls.Add($rendererBox)

    $note = New-Object System.Windows.Forms.Label
    $note.Text = 'DDGI / DDGIHalf use D3D12.'
    $note.Location = New-Object System.Drawing.Point(110, 98)
    $note.Size = New-Object System.Drawing.Size(250, 22)
    $form.Controls.Add($note)

    $launchButton = New-Object System.Windows.Forms.Button
    $launchButton.Text = 'Launch'
    $launchButton.Location = New-Object System.Drawing.Point(190, 140)
    $launchButton.Size = New-Object System.Drawing.Size(75, 30)
    $launchButton.DialogResult = [System.Windows.Forms.DialogResult]::OK
    $form.Controls.Add($launchButton)
    $form.AcceptButton = $launchButton

    $cancelButton = New-Object System.Windows.Forms.Button
    $cancelButton.Text = 'Cancel'
    $cancelButton.Location = New-Object System.Drawing.Point(275, 140)
    $cancelButton.Size = New-Object System.Drawing.Size(75, 30)
    $cancelButton.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $form.Controls.Add($cancelButton)
    $form.CancelButton = $cancelButton

    if ($form.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { exit 0 }
    $Scene = [string]$sceneBox.SelectedItem
    $Renderer = [string]$rendererBox.SelectedItem
}

$availableScenes = @('Room', 'Cornell', 'CornellLambert', 'Arcade', 'Bistro')
if ($Scene -notin $availableScenes) {
    throw "Unknown scene '$Scene'. Available scenes: $($availableScenes -join ', ')."
}

if ($Renderer -in @('DDGIHalf', 'DDGI')) {
    if ($PSBoundParameters.ContainsKey('Device') -and $Device -ne 'd3d12') {
        throw "$Renderer requires D3D12 in this integration. Use -Device d3d12 or omit -Device."
    }
    $Device = 'd3d12'
}
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
    Cornell = 'F:\scripts\scenes\CornellRTXGI.pyscene'
    CornellLambert = 'F:\scripts\scenes\CornellLambert.pyscene'
    Arcade = 'F:\media\Arcade\Arcade.pyscene'
    Bistro = 'F:\media\ORCA_Bistro\Bistro_v5_2\BistroExterior.pyscene'
}
$env:FALCOR_MEDIA_FOLDERS = 'F:\media'
$env:FALCOR_SCENE_FOLDER = 'F:\media'
$env:FALCOR_START_RENDERER = $Renderer
$env:FALCOR_START_SCENE = $Scene
$env:PROBE_GI_MODE = $Mode
$env:PROBE_GI_SAMPLES = [string]$Samples
$env:PROBE_GI_REVISION = $Revision
$env:PROBE_GI_CACHE = ''
$env:PROBE_GI_ENABLED = '1'
$graphScript = if ($Device -eq 'd3d12') {
    'GIPreview.py'
} else {
    switch ($Renderer) {
        'Probe' { 'TraditionalProbeGI.py' }
        default { 'PathTracer.py' }
    }
}
$launchArguments = @(
    '--device-type', $Device,
    '--script', ('F:\scripts\' + $graphScript),
    '--scene', $scenes[$Scene],
    '--width', '1280', '--height', '720',
    '--logfile', ('F:\build\windows-vs2022\preview-' + $Scene + '.log')
)

Start-Process -FilePath $executable -ArgumentList $launchArguments `
    -WorkingDirectory 'F:\build\windows-vs2022\bin\Release' -WindowStyle Normal
