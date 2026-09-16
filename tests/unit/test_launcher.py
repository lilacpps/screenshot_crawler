from pathlib import Path

ROOT = Path(__file__).parents[2]
LAUNCHER = ROOT / "scripts" / "start_crawler_chrome.ps1"


def test_shared_launcher_uses_repository_profile_and_standard_port() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")

    assert "[int]$Port = 9222" in script
    assert '".chrome-crawler"' in script
    assert '"--remote-debugging-port=$Port"' in script
    assert "$quotedProfileDirectory = '\"' + $profileDirectory + '\"'" in script
    assert '"--user-data-dir=$quotedProfileDirectory"' in script
    assert '"--window-size=1920,1080"' in script
    assert '"about:blank"' in script


def test_shared_launcher_checks_existing_cdp_listener_before_starting_chrome() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")

    listener_check = script.index("/json/version")
    process_start = script.index("Start-Process")
    assert listener_check < process_start
    assert "Test-SharedCrawlerChromeProcess" in script
    assert "Get-CimInstance -ClassName Win32_Process" in script
    assert "no second browser will be started" in script
    assert "could not be verified as using the shared crawler profile" in script


def test_shared_launcher_verifies_profile_after_start_before_success() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")

    process_start = script.index("Start-Process")
    post_start_listener_check = script.index(
        'Invoke-RestMethod "http://127.0.0.1:$Port/json/version"',
        process_start,
    )
    post_start_profile_check = script.index(
        "if (-not (Test-SharedCrawlerChromeProcess",
        process_start,
    )
    success_message = script.index('Write-Host "Shared Crawler Chrome started."')

    assert post_start_listener_check > process_start
    assert post_start_profile_check > post_start_listener_check
    assert success_message > post_start_profile_check


def test_shared_chrome_profile_is_covered_by_existing_gitignore_rule() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".chrome-*/" in gitignore
