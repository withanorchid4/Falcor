param(
    [ValidateSet('All', 'Sponza', 'EmeraldSquare')][string]$Scene = 'All',
    [string]$EmeraldArchive = '',
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'scripts/download_scene_assets.py'
$arguments = @($script, '--scene', $Scene)
if ($EmeraldArchive) { $arguments += @('--emerald-archive', $EmeraldArchive) }
if ($VerifyOnly) { $arguments += '--verify-only' }
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 @arguments
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    & python @arguments
} else {
    throw 'Install Python 3.9 or newer, then run this script again.'
}
if ($LASTEXITCODE -ne 0) { throw 'Scene asset setup failed. See the error above; rerun to retry.' }
