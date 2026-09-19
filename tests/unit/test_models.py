import pytest

from screenshot_crawler.core.models import ContentContext, ContentIdentity, RunConfig


def test_content_identity_is_value_comparable() -> None:
    assert ContentIdentity(page_number=1, source_id="a") == ContentIdentity(
        page_number=1,
        source_id="a",
    )


def test_content_context_is_value_comparable() -> None:
    assert ContentContext(episode_id="42") == ContentContext(episode_id="42")


def test_run_config_defaults_to_auto_with_unspecified_metadata(tmp_path) -> None:
    config = RunConfig(
        site="test",
        source_url="https://example.test/",
        output_dir=tmp_path / "run",
        diagnostics_dir=tmp_path / "diagnostics",
    )

    assert config.access_strategy == "auto"
    assert config.output_metadata == {}
    assert config.adapter_timeout_grace_ms == 2_000


@pytest.mark.parametrize("strategy", ["auto", "direct", "quota"])
def test_run_config_accepts_supported_access_strategies(tmp_path, strategy: str) -> None:
    config = RunConfig(
        site="test",
        source_url="https://example.test/",
        output_dir=tmp_path / "run",
        diagnostics_dir=tmp_path / "diagnostics",
        access_strategy=strategy,  # type: ignore[arg-type]
    )

    assert config.access_strategy == strategy


def test_run_config_rejects_unknown_access_strategy(tmp_path) -> None:
    with pytest.raises(ValueError, match="access_strategy"):
        RunConfig(
            site="test",
            source_url="https://example.test/",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
            access_strategy="unexpected",  # type: ignore[arg-type]
        )


def test_run_config_restricts_output_metadata_fields(tmp_path) -> None:
    with pytest.raises(ValueError, match="unsupported output metadata"):
        RunConfig(
            site="test",
            source_url="https://example.test/",
            output_dir=tmp_path / "run",
            diagnostics_dir=tmp_path / "diagnostics",
            output_metadata={"source_url": "https://other.test/"},
        )
