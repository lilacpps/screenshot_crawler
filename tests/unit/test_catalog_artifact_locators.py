import pytest

from screenshot_crawler.catalog import ArtifactInput, CatalogService, ItemInput, WorkInput
from screenshot_crawler.catalog.service import CatalogNotFoundError, CatalogValidationError

SHA = "B" * 64


def _artifact_graph(tmp_path):
    catalog = CatalogService(tmp_path / "catalog.sqlite")
    work = catalog.create_work(WorkInput(work_key="work", title="Work"))
    item = catalog.create_item(ItemInput(), work_id=work.id)
    first = catalog.create_artifact(
        ArtifactInput(
            kind="archive", format="zip", sha256=SHA, byte_size=10,
            storage_backend="filesystem", locator="one.zip", state="present",
        ), item_id=item.id,
    )
    second = catalog.create_artifact(
        ArtifactInput(
            kind="archive", format="zip", sha256=SHA, byte_size=20,
            storage_backend="filesystem", locator="two.zip", state="present",
        ), item_id=item.id,
    )
    return catalog, first, second


def test_bulk_locator_update_changes_only_locator_and_updated_at(tmp_path):
    catalog, first, second = _artifact_graph(tmp_path)
    updated = catalog.update_artifact_locators({
        first.id: ("one.zip", "new-one.zip"),
        second.id: ("two.zip", "new-two.zip"),
    })

    assert [artifact.locator for artifact in updated] == ["new-one.zip", "new-two.zip"]
    assert catalog.get_artifact(first.id).sha256 == SHA.lower()
    assert catalog.get_artifact(first.id).byte_size == 10
    assert catalog.get_artifact(first.id).state == "present"
    assert catalog.get_artifact(second.id).byte_size == 20


def test_bulk_locator_update_compare_and_set_rolls_back_all_rows(tmp_path):
    catalog, first, second = _artifact_graph(tmp_path)
    with pytest.raises(CatalogValidationError, match="changed"):
        catalog.update_artifact_locators({
            first.id: ("one.zip", "new-one.zip"),
            second.id: ("wrong.zip", "new-two.zip"),
        })
    assert catalog.get_artifact(first.id).locator == "one.zip"
    assert catalog.get_artifact(second.id).locator == "two.zip"


def test_bulk_locator_update_missing_artifact_rolls_back_all_rows(tmp_path):
    catalog, first, second = _artifact_graph(tmp_path)
    with pytest.raises(CatalogNotFoundError):
        catalog.update_artifact_locators({
            first.id: ("one.zip", "new-one.zip"),
            9999: ("missing.zip", "new-two.zip"),
        })
    assert catalog.get_artifact(first.id).locator == "one.zip"
    assert catalog.get_artifact(second.id).locator == "two.zip"


def test_bulk_locator_update_rejects_invalid_new_locator_without_changes(tmp_path):
    catalog, first, _ = _artifact_graph(tmp_path)
    with pytest.raises(CatalogValidationError, match="locator"):
        catalog.update_artifact_locators({first.id: ("one.zip", "")})
    assert catalog.get_artifact(first.id).locator == "one.zip"
