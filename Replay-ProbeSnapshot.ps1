param(
    [Parameter(Mandatory=$true)][string]$Snapshot,
    [string]$Overrides,
    [switch]$Rebake
)
$ErrorActionPreference='Stop'
$python=Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Use Python with numpy to run scripts/replay_probe_snapshot.py.' }
$arguments=@((Join-Path $PSScriptRoot 'scripts/replay_probe_snapshot.py'),$Snapshot)
if ($Overrides) { $arguments+=@('--overrides',$Overrides) }
if ($Rebake) { $arguments+='--rebake' }
& $python @arguments
if ($LASTEXITCODE -ne 0) { throw 'Probe snapshot replay failed; see the run output.' }
