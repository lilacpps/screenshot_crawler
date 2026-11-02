from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from screenshot_crawler.cli import _discovery_registry
from screenshot_crawler.registration.models import ObservedUrlConversion
from screenshot_crawler.registration.resolver import UrlResolver
from screenshot_crawler.registration.service import RegistrationService
from tests.unit.test_registration_detail import setup_batch

LIST = "https://piccoma.com/web/product/63/episodes"
SEED = "https://piccoma.com/web/viewer/63/900"


def converted(resolver, now=None):
    initial = resolver.resolve(LIST)
    proof = ObservedUrlConversion(LIST, "piccoma", LIST, SEED, "piccoma-product:63",
        "63:900", 1, 3, ("PCM-list_asc", "declared-count:3", "status-count:1",
            "PCM-epList_status_free", "¥0"), now or datetime.now(UTC))
    return replace(initial, status="converted", discovery_url=SEED,
        site_work_identity="piccoma-product:63", conversion_proof=proof, blockers=())


@pytest.mark.parametrize("suffix", ["", "/"])
def test_listing_is_only_pending_observation_not_manually_registrable(suffix):
    resolver = UrlResolver(_discovery_registry())
    result = resolver.resolve(LIST + suffix)
    assert result.status == "blocked" and result.observation_url == LIST
    assert result.discovery_url is None and result.site_work_identity is None
    assert result.conversion_proof is None and resolver.resolution_error(result)


@pytest.mark.parametrize("alter", [
    lambda u: u + "?a=1", lambda u: u + "#", lambda u: u + ";x", lambda u: u + "\\",
    lambda u: u.replace("https:", "http:"), lambda u: u.replace(".com/", ".com.evil.invalid/"),
    lambda u: u.replace("://", "://user@"), lambda u: u.replace("/63/", "/%36%33/"),
    lambda u: u.replace(".com/", ".com:444/"),
])
def test_unsafe_listing_never_becomes_an_observation_candidate(alter):
    result = UrlResolver(_discovery_registry()).resolve(alter(LIST))
    assert result.status == "blocked" and result.observation_url is None


def test_proof_is_immutable_normal_metadata_cannot_rescue_pending():
    resolver = UrlResolver(_discovery_registry())
    value = converted(resolver)
    assert resolver.resolution_error(value) is None
    assert value.blocked("retry").conversion_proof is None
    with pytest.raises(FrozenInstanceError):
        value.conversion_proof.dom_index = 0


@pytest.mark.parametrize("field,value", [
    ("input_url", LIST + "/"), ("site", "zeblack"), ("observation_url", LIST + "/"),
    ("discovery_url", "https://piccoma.com/web/viewer/64/900"),
    ("site_work_identity", "piccoma-product:64"), ("selected_external_id", "63:901"),
    ("dom_index", -1), ("dom_index", 3), ("dom_index", True),
    ("row_count", 10001), ("row_count", 2),
    ("selection_evidence", ("PCM-list_desc",)),
    ("observed_at", datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None)), ("observed_at", "not a date"),
])
def test_altered_proof_is_rejected(field, value):
    resolver = UrlResolver(_discovery_registry())
    result = converted(resolver)
    result = replace(result, conversion_proof=replace(result.conversion_proof, **{field: value}))
    assert resolver.resolution_error(result)


@pytest.mark.parametrize("field,value", [
    ("input_url", LIST + "/"), ("site", "zeblack"), ("observation_url", LIST + "/"),
    ("discovery_url", "https://piccoma.com/web/viewer/64/900"),
    ("site_work_identity", "piccoma-product:64"), ("status", "valid"), ("conversion_proof", None),
])
def test_resolution_cannot_be_substituted_under_proof(field, value):
    resolver = UrlResolver(_discovery_registry())
    assert resolver.resolution_error(replace(converted(resolver), **{field: value}))


@pytest.mark.parametrize("age,accepted", [(0, True), (300, True), (300.001, False), (-0.001, False)])
def test_proof_time_is_bounded_and_clock_is_testable(monkeypatch, age, accepted):
    now = datetime(2026, 11, 3, tzinfo=UTC)
    monkeypatch.setattr("screenshot_crawler.registration.models.conversion_now", lambda: now)
    resolver = UrlResolver(_discovery_registry())
    error = resolver.resolution_error(converted(resolver, now - timedelta(seconds=age)))
    assert (error is None) == accepted


@pytest.mark.asyncio
async def test_normal_observe_and_changed_pending_never_navigate():
    resolver = UrlResolver(_discovery_registry())
    pending = resolver.resolve(LIST)
    assert (await resolver.observe(object(), pending)).status == "blocked"
    assert (await resolver.observe_conversion(object(), replace(pending, discovery_url=SEED))).status == "blocked"


def test_unknown_title_conversion_requires_human_confirmation_and_saves_exact_seed(tmp_path, monkeypatch):
    batch, path, catalog = setup_batch(tmp_path)
    now = datetime.now(UTC)
    monkeypatch.setattr("screenshot_crawler.registration.models.conversion_now", lambda: now)
    value = converted(batch.resolver, now)
    row = batch.add_resolution(1, LIST, value)
    assert batch.readiness(row).status != "ready"
    batch.edit_candidate(row, label="人工作品")
    batch.name_work(row, "synthetic_piccoma")
    batch.confirm(row)
    assert batch.readiness(row).status == "ready"
    service = RegistrationService(path, catalog.path)
    before = path.read_bytes(), catalog.path.read_bytes()
    preview = service.preview(batch)
    assert f"入力URL: {LIST}" in preview.summary and f"保存URL: {SEED}" in preview.summary
    assert before == (path.read_bytes(), catalog.path.read_bytes())
    assert service.save(batch, preview).verified
    target, = yaml.safe_load(path.read_text(encoding="utf-8"))["targets"]
    assert target["url"] == SEED and target["label"] == "人工作品"
    assert "conversion_proof" not in target and "observation_url" not in target
    assert catalog.path.read_bytes() == before[1]


def test_expiry_after_preview_blocks_atomic_save_and_retry_discards_proof(tmp_path, monkeypatch):
    batch, path, catalog = setup_batch(tmp_path)
    now = datetime.now(UTC)
    monkeypatch.setattr("screenshot_crawler.registration.models.conversion_now", lambda: now)
    row = batch.add_resolution(1, LIST, converted(batch.resolver, now))
    batch.edit_candidate(row, label="人工作品")
    batch.name_work(row, "synthetic_piccoma")
    batch.confirm(row)
    service = RegistrationService(path, catalog.path)
    preview = service.preview(batch)
    before = path.read_bytes(), catalog.path.read_bytes()
    monkeypatch.setattr("screenshot_crawler.registration.models.conversion_now", lambda: now + timedelta(seconds=301))
    assert batch.readiness(row).status == "blocked"
    with pytest.raises(ValueError):
        service.save(batch, preview)
    assert before == (path.read_bytes(), catalog.path.read_bytes())
    batch.retry(row, batch.resolver.resolve(SEED))
    assert batch.candidates[row].resolution.conversion_proof is None
    assert batch.candidates[row].label == "人工作品" and not batch.candidates[row].confirmed
