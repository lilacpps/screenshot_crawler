[CmdletBinding()]
param(
    [int]$Port = 9222
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$profileDirectory = Join-Path $repositoryRoot ".chrome-crawler"

$normalizedProfileDirectory = [System.IO.Path]::GetFullPath($profileDirectory).Replace('/', '\').TrimEnd('\').ToLowerInvariant()

function Test-SharedCrawlerChromeProcess {
    param(
        [int]$ExpectedPort,
        [string]$ExpectedProfileDirectory
    )

    try {
        $chromeProcesses = @(Get-CimInstance -ClassName Win32_Process -Filter "Name = 'chrome.exe'")
    } catch {
        throw "CDP listener is available, but the Chrome process could not be inspected. Confirm that the existing Chrome uses the shared crawler profile before retrying."
    }

    foreach ($chromeProcess in $chromeProcesses) {
        if ([string]::IsNullOrWhiteSpace($chromeProcess.CommandLine)) {
            continue
        }

        $commandLine = $chromeProcess.CommandLine.Replace('"', '').Replace('/', '\').ToLowerInvariant()
        $hasExpectedPort = $commandLine -match "(^|\s)--remote-debugging-port=$ExpectedPort(\s|$)"
        $hasExpectedProfile = $commandLine.Contains("--user-data-dir=$ExpectedProfileDirectory")
        if ($hasExpectedPort -and $hasExpectedProfile) {
            return $true
        }
    }

    return $false
}

$listenerAvailable = $false
try {
    Invoke-RestMethod "http://127.0.0.1:$Port/json/version" -TimeoutSec 2 | Out-Null
    $listenerAvailable = $true
} catch {
    # No existing listener: start the shared browser below.
}

if ($listenerAvailable) {
    if (Test-SharedCrawlerChromeProcess -ExpectedPort $Port -ExpectedProfileDirectory $normalizedProfileDirectory) {
        Write-Host "Shared Crawler Chrome CDP is already available at http://127.0.0.1:$Port"
        Write-Host "Using the existing shared Chrome process; no second browser will be started."
        exit 0
    }

    throw "Port $Port is already in use, but the existing Chrome could not be verified as using the shared crawler profile '$profileDirectory'. Confirm the existing Chrome before retrying."
}

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
    Write-Host "Shared Crawler Chrome started."
    Write-Host "Profile: $profileDirectory"
    Write-Host "CDP endpoint: http://127.0.0.1:$Port"
    Write-Host "BookWalker and Manga ONE can share this Chrome profile."
} catch {
    throw "Chrome started, but CDP endpoint http://127.0.0.1:$Port is not available."
}
