"""BookWalker Batch admission and Catalog-scoped capture-session references."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID, uuid4

from screenshot_crawler.core.packaging import PackageResult, archive_stem, resolve_output_metadata
from screenshot_crawler.core.progress import atomic_write_json
from screenshot_crawler.core.resume import CaptureSession, ResumeError, plain_path

CAPTURE_BUDGET_SECONDS = 590


class BookWalkerResumeManager:
    def __init__(self, catalog):
        self.catalog = catalog
        self.root = plain_path(catalog.path.with_name(catalog.path.name + ".resume") / "bookwalker")

    def binding(self, source, target) -> dict:
        parsed = urlparse(target.locator)
        match = re.fullmatch(r"/de([0-9a-fA-F-]{36})/?", parsed.path)
        try:
            same_book = match is not None and UUID(match[1]) == UUID(source.external_id)
        except ValueError:
            same_book = False
        if (
            parsed.scheme != "https"
            or parsed.netloc.lower() not in {"bookwalker.jp", "www.bookwalker.jp"}
            or not same_book
        ):
            raise ResumeError("BookWalker resume target is not this Source's canonical product")
        item = self.catalog.get_item(source.item_id)
        work = self.catalog.get_work(item.work_id)
        return {
            "catalog": self.catalog.path.resolve().as_posix(),
            "work_key": work.work_key,
            "work_created_at": work.created_at,
            "item_id": item.id,
            "item_created_at": item.created_at,
            "source_id": source.id,
            "source_created_at": source.created_at,
            "cid": source.external_id,
            "target_id": target.id,
            "target_created_at": target.created_at,
            "backend": target.backend,
            "target_key": target.target_key,
            "locator": target.locator,
        }

    def marker(self, source) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", source.external_id):
            raise ResumeError("Unsafe BookWalker source identity")
        return plain_path(self.root / (source.external_id + ".json"))

    def load(self, source, target) -> CaptureSession | None:
        if source.access_mode != "quota":
            return None
        marker = self.marker(source)
        if not marker.exists():
            return None
        try:
            reference = json.loads(marker.read_text(encoding="utf-8"))
            session_id = reference["id"]
            name = reference["directory"]
            if reference["version"] != 1 or not re.fullmatch(r"[0-9a-f]{32}", session_id):
                raise ResumeError("Unsupported resume reference")
            if name != session_id:
                raise ResumeError("Unsafe resume session directory")
            binding = self.binding(source, target)
            if reference["binding"] != binding:
                raise ResumeError("Resume reference does not belong to this Catalog/Source/Target")
            session = CaptureSession(
                self.root / "data" / name,
                session_id,
                binding,
                source_url=target.locator,
                site="bookwalker",
                existing=True,
                seconds=CAPTURE_BUDGET_SECONDS,
            )
            previous = 0
            total = None
            for group in session.store.manifest["capture_groups"]:
                checkpoint = group["checkpoint"]
                current = checkpoint.get("current")
                observed_total = checkpoint.get("total")
                layout = checkpoint.get("layout")
                if (
                    checkpoint.get("cid", "").casefold() != source.external_id.casefold()
                    or group["identity"].get("source_id", "").casefold()
                    != source.external_id.casefold()
                    or type(current) is not int
                    or type(observed_total) is not int
                    or not previous < current <= observed_total
                    or group["identity"].get("page_number") != current
                    or not isinstance(layout, list)
                    or len(layout) != 4
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not 0 < value < 100_000
                        for value in layout
                    )
                    or (total is not None and observed_total != total)
                ):
                    raise ResumeError("BookWalker resume checkpoint identity/order is invalid")
                previous, total = current, observed_total
            return session
        except ResumeError as exc:
            raise ResumeError(f"{exc} (resume_file={marker})") from exc
        except (AttributeError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
            raise ResumeError(f"Invalid BookWalker resume reference: {marker}") from exc

    def create(self, source, target, now: datetime) -> CaptureSession:
        marker = self.marker(source)
        if marker.exists():
            raise ResumeError("Resume reference appeared during execution; replan")
        session_id = uuid4().hex
        # Keep paths short on Windows; ownership is in the validated binding,
        # not inferred from a long directory name.
        name = session_id
        binding = self.binding(source, target)
        session = CaptureSession(
            self.root / "data" / name,
            session_id,
            binding,
            source_url=target.locator,
            site="bookwalker",
            seconds=CAPTURE_BUDGET_SECONDS,
        )
        atomic_write_json(
            marker, {"version": 1, "id": session_id, "binding": binding, "directory": name}
        )
        return session

    def clear(self, session: CaptureSession) -> None:
        marker = plain_path(self.root / (session.binding["cid"] + ".json"))
        if marker.exists():
            reference = json.loads(marker.read_text(encoding="utf-8"))
            if reference.get("id") != session.id or reference.get("binding") != session.binding:
                raise ResumeError("Resume reference changed before release")
            marker.unlink()

    def abandon_if_unsafe(self, session: CaptureSession) -> None:
        # Only a session admitted by this attempt may be invalidated automatically.
        try:
            from screenshot_crawler.core.resume import read_session_manifest

            read_session_manifest(session.directory, session.id, session.binding)
        except ResumeError:
            session.invalidate("uncommitted_artifact_or_failed_close")
            self.clear(session)

    @staticmethod
    def package_paths(session, candidate, library_dir) -> tuple[Path, Path, tuple]:
        metadata = resolve_output_metadata(candidate.metadata, session.info.get("metadata", {}))
        naming = archive_stem(
            metadata,
            artifact_prefix=candidate.artifact_prefix,
            artifact_disambiguator=candidate.artifact_disambiguator,
        )
        stem, title, genre, _, _ = naming
        library_dir = plain_path(Path(library_dir))
        archive = plain_path(library_dir / genre / title / (stem + ".zip"))
        status = plain_path(library_dir.parent / "crawl-status" / genre / title / (stem + ".json"))
        return archive, status, naming

    def owned_package(
        self, session, candidate, library_dir, *, write_status=False
    ) -> PackageResult | None:
        archive, status, naming = self.package_paths(session, candidate, library_dir)
        intent = session.info.get("package_intent")
        if intent is None:
            if archive.exists() or status.exists():
                raise ResumeError("Unowned archive/status blocks local completion")
            return None
        if intent != {"archive": archive.as_posix(), "status": status.as_posix()}:
            raise ResumeError("Archive metadata/path changed since package intent")
        if status.exists():
            try:
                record = json.loads(status.read_text(encoding="utf-8"))
                if (
                    record.get("source_output_dir") != session.directory.as_posix()
                    or record.get("archive_path") != archive.as_posix()
                    or record.get("page_count") != len(session.store.pages)
                ):
                    if archive.exists():
                        raise ResumeError("Existing package status belongs to another acquisition")
                    from screenshot_crawler.batch.archive_guard import (
                        validate_candidate_output_paths,
                    )

                    item = self.catalog.get_item(candidate.item_id)
                    validate_candidate_output_paths(
                        self.catalog,
                        work=self.catalog.get_work(item.work_id),
                        item=item,
                        source=self.catalog.get_source(candidate.source_id),
                        target=self.catalog.get_source_target(candidate.target_id),
                        archive_path=archive,
                        status_path=status,
                    )
            except (OSError, json.JSONDecodeError) as exc:
                raise ResumeError("Cannot verify package status") from exc
        if not archive.exists():
            return None
        try:
            with zipfile.ZipFile(archive) as zipped:
                pages = session.store.pages
                if zipped.namelist() != [p["file"] for p in pages]:
                    raise ResumeError("Existing ZIP does not contain this acquisition's pages")
                for p in pages:
                    if hashlib.sha256(zipped.read(p["file"])).hexdigest() != p["fingerprint"]:
                        raise ResumeError("Existing ZIP content differs from committed pages")
        except (OSError, zipfile.BadZipFile) as exc:
            raise ResumeError("Cannot verify existing acquisition ZIP") from exc
        proof = session.info.get("package")
        if proof and proof.get("sha256") != hashlib.sha256(archive.read_bytes()).hexdigest():
            raise ResumeError("Packaged ZIP changed after creation")
        if write_status and not status.exists():
            atomic_write_json(
                status,
                {
                    "status": "completed",
                    "archive_path": archive.as_posix(),
                    "page_count": len(session.store.pages),
                    "source_output_dir": session.directory.as_posix(),
                    "source_removed": False,
                },
            )
        _, title, genre, order, author = naming
        return PackageResult(archive, title, genre, order, author, status)

    def package(self, session, candidate, library_dir, package_function) -> PackageResult:
        from screenshot_crawler.core.resume import read_session_manifest

        disk = read_session_manifest(session.directory, session.id, session.binding)
        if json.dumps(disk, sort_keys=True) != json.dumps(session.store.manifest, sort_keys=True):
            raise ResumeError("Capture manifest changed before packaging")
        recovered = (
            self.owned_package(session, candidate, library_dir, write_status=True)
            if session.info.get("package_intent")
            else None
        )
        if recovered is not None:
            return recovered
        archive, status, _ = self.package_paths(session, candidate, library_dir)
        session.info["package_intent"] = {
            "archive": archive.as_posix(),
            "status": status.as_posix(),
        }
        session.save_info()
        kwargs = {"library_dir": library_dir, "explicit_metadata": candidate.metadata}
        if candidate.artifact_prefix is not None:
            kwargs["artifact_prefix"] = candidate.artifact_prefix
        if candidate.artifact_disambiguator is not None:
            kwargs["artifact_disambiguator"] = candidate.artifact_disambiguator
        result = package_function(session.directory, session.info.get("metadata", {}), **kwargs)
        if Path(result.archive_path).resolve() != archive:
            raise ResumeError("Packager returned an unexpected archive path")
        self.owned_package(session, candidate, library_dir)
        session.info["package"] = {"sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
        session.save_info()
        return result

    def completed_artifact(self, session):
        if self.catalog.get_item(session.binding["item_id"]).status != "completed":
            return None
        intent = session.info.get("package_intent") or {}
        for artifact in self.catalog.list_artifacts(
            item_id=session.binding["item_id"], state="present"
        ):
            if artifact.crawl_run_id in session.info["attempts"] and artifact.locator == intent.get(
                "archive"
            ):
                run = self.catalog.get_crawl_run(artifact.crawl_run_id)
                if (
                    run.status != "succeeded"
                    or run.source_id != session.binding["source_id"]
                    or run.target_id != session.binding["target_id"]
                    or run.item_id != session.binding["item_id"]
                ):
                    raise ResumeError("Completed archive has different acquisition history")
                path = plain_path(Path(artifact.locator))
                if (
                    path.is_file()
                    and hashlib.sha256(path.read_bytes()).hexdigest() == artifact.sha256
                ):
                    return artifact
        raise ResumeError("Completed Item is not bound to this capture acquisition")

    def cleanup(self, session) -> None:
        # Leave diagnostics/user files alone. Never recursively delete a directory.
        names = {p["file"] for p in session.store.pages} | {
            "manifest.json",
            "progress.json",
            "capture-session.keep",
        }
        if any(p.name not in names for p in session.directory.iterdir()):
            return
        for name in names:
            plain_path(session.directory / name).unlink(missing_ok=True)
        session.directory.rmdir()
        intent = session.info.get("package_intent")
        if intent:
            status_path = plain_path(Path(intent["status"]))
            if status_path.is_file():
                record = json.loads(status_path.read_text(encoding="utf-8"))
                if record.get("source_output_dir") == session.directory.as_posix():
                    record["source_removed"] = True
                    atomic_write_json(status_path, record)
