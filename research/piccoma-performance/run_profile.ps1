param(
    [Parameter(Mandatory = $true)][string]$RunRoot,
    [int]$Pages = 12,
    [int]$Runs = 2,
    [int]$PageTurnDelayMs = 1000
)

$ErrorActionPreference = "Stop"
if ($PageTurnDelayMs -lt 0) {
    throw "PageTurnDelayMs must be a non-negative integer"
}
$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$python = Join-Path $repo ".venv\Scripts\python.exe"
$endpoint = "http://127.0.0.1:9222"
$runRootPath = [System.IO.Path]::GetFullPath($RunRoot)
$allowedRoot = [System.IO.Path]::GetFullPath((Join-Path $repo "output\piccoma_performance"))
if (-not $runRootPath.StartsWith(
    $allowedRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar,
    [System.StringComparison]::OrdinalIgnoreCase
)) {
    throw "RunRoot must be below $allowedRoot"
}
if (Test-Path -LiteralPath $runRootPath) {
    throw "RunRoot already exists; refusing to overwrite isolated evidence"
}
New-Item -ItemType Directory -Force -Path $runRootPath | Out-Null

$env:PYTHONPATH = "$PSScriptRoot;$repo\src"
for ($index = 1; $index -le $Runs; $index++) {
    $runDir = Join-Path $runRootPath "run-$index"
    $workDir = Join-Path $runDir "cwd"
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null
    @"
sites:
  piccoma:
    page_turn_delay_ms: $PageTurnDelayMs
    stop_on_http_403: true
    stop_on_http_429: true
    stop_on_challenge: true
    stop_on_captcha: true
"@ | Set-Content -Encoding utf8 (Join-Path $workDir "crawler.yaml")

    $env:PERF_TRACE_FILE = Join-Path $runDir "timings.json"
    $env:PERF_PROGRESS_FILE = Join-Path $runDir "page-progress.json"
    Push-Location $workDir
    try {
        & $python (Join-Path $PSScriptRoot "profile_run_driver.py") `
            $endpoint $runDir $Pages $PageTurnDelayMs
        $exitCode = $LASTEXITCODE
        Set-Content -Encoding ascii (Join-Path $runDir "exit-code.txt") "$exitCode"
        if (-not (Test-Path (Join-Path $runDir "timings.json"))) {
            throw "Profiling hook did not write timing output for run $index"
        }
        if (-not (Test-Path (Join-Path $runDir "page-progress.json"))) {
            throw "Profiling hook did not write page progress output for run $index"
        }
    }
    finally {
        Pop-Location
    }
}
