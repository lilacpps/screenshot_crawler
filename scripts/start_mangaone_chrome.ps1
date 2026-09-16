[CmdletBinding()]
param(
    [int]$Port = 9222
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$profileDirectory = Join-Path $repositoryRoot ".chrome-mangaone"

$chromeCandidates = @(
    (Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"),
    (Join-Path $env:LOCALAPPDATA "Google\Chrome\Application\chrome.exe")
)

$chromePath = $chromeCandidates |
    Where-Object { $_ -and (Test-Path -LiteralPath $_) } |
    Select-Object -First 1

if (-not $chromePath) {
    throw "Google Chrome was not found. Install Chrome or edit the path candidates in this script."
}

try {
    Invoke-RestMethod "http://127.0.0.1:$Port/json/version" -TimeoutSec 2 | Out-Null
    Write-Host "Chrome CDP is already available at http://127.0.0.1:$Port"
    Write-Host "Use the existing Chrome window, or close it before starting a new one."
    exit 0
} catch {
    # No existing listener: start the dedicated browser below.
}

New-Item -ItemType Directory -Force -Path $profileDirectory | Out-Null

$arguments = @(
    "--remote-debugging-port=$Port",
    "--user-data-dir=$profileDirectory",
    "--window-size=1920,1080",
    "about:blank"
)

Start-Process -FilePath $chromePath -ArgumentList $arguments
Start-Sleep -Seconds 2

try {
    Invoke-RestMethod "http://127.0.0.1:$Port/json/version" -TimeoutSec 5 | Out-Null
    Write-Host "Manga ONE Chrome started."
    Write-Host "Profile: $profileDirectory"
    Write-Host "CDP endpoint: http://127.0.0.1:$Port"
} catch {
    throw "Chrome started, but CDP endpoint http://127.0.0.1:$Port is not available."
}
