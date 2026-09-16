from pathlib import Path

ROOT = Path(__file__).parents[2]
LAUNCHER = ROOT / "scripts" / "start_crawler_chrome.ps1"


def test_shared_launcher_uses_repository_profile_and_standard_port() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")

    assert "[int]$Port = 9222" in script
    assert '".chrome-crawler"' in script
    assert '"--remote-debugging-port=$Port"' in script
    assert '"--user-data-dir=$profileDirectory"' in script
    assert '"--window-size=1920,1080"' in script
    assert '"about:blank"' in script


def test_shared_launcher_checks_existing_cdp_listener_before_starting_chrome() -> None:
    script = LAUNCHER.read_text(encoding="utf-8")

    listener_check = script.index("/json/version")
    process_start = script.index("Start-Process")
    assert listener_check < process_start
    assert "no second browser will be started" in script


def test_shared_chrome_profile_is_covered_by_existing_gitignore_rule() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".chrome-*/" in gitignore
