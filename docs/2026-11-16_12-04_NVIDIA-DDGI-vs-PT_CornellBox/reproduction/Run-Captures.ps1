$ErrorActionPreference = 'Stop'
$evalRoot = 'F:/build/official-ddgi/evaluation/2026-11-16_12-04_NVIDIA-DDGI-vs-PT_CornellBox'
$evalExe = 'F:/build/official-ddgi/build/samples/bin/d3d12/Release/TestHarness-Evaluation.exe'
$cases = @(
    @{ Variant='ddgi'; Directory='ddgi-final'; Start=65537; Count=32; End=65568 },
    @{ Variant='pt-a'; Directory='pt-a'; Start=32769; Count=1; End=32769 },
    @{ Variant='pt-b'; Directory='pt-b'; Start=32769; Count=1; End=32769 }
)
try {
    foreach ($case in $cases) {
        $runDir = Join-Path $evalRoot $case.Directory
        New-Item -ItemType Directory -Path $runDir -Force | Out-Null
        $env:GI_EVAL_DIR = Join-Path $runDir 'capture'
        $env:GI_EVAL_START = [string]$case.Start
        $env:GI_EVAL_COUNT = [string]$case.Count
        $env:GI_EVAL_END = [string]$case.End
        $configPath = Join-Path $evalRoot ($case.Variant + '.ini')
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot ($case.Variant + '.ini')) -Destination $configPath
        $runStarted = Get-Date
        $process = Start-Process -FilePath $evalExe -ArgumentList ('"' + $configPath + '"') -WorkingDirectory $runDir -WindowStyle Hidden -PassThru -Wait
        if ($process.ExitCode -ne 0) { throw "Capture failed: $($case.Variant), exit $($process.ExitCode)" }
        $completion = Join-Path $env:GI_EVAL_DIR 'complete.txt'
        if (-not (Test-Path -LiteralPath $completion)) { throw "Missing completion: $($case.Variant)" }
        if ((Get-Item -LiteralPath $completion).LastWriteTime -lt $runStarted) { throw "Stale completion: $($case.Variant)" }
        Write-Output "Completed $($case.Variant): $(Get-Content -LiteralPath $completion)"
    }
} finally {
    foreach ($name in @('GI_EVAL_DIR','GI_EVAL_START','GI_EVAL_COUNT','GI_EVAL_END')) {
        Remove-Item -LiteralPath "Env:$name" -ErrorAction SilentlyContinue
    }
}
