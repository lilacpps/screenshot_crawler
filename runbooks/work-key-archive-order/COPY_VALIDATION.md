# Isolated-copy preparation before renumber apply

Use this only for an isolated validation copy. Never run it against the operational Catalog, Watchlist, Books, or status directory. Make a SQLite online backup and copy the Watchlist, Books, and crawl-status from one point in time into a new COPY_ROOT. If a step fails, discard the working copy and recreate it from the immutable seed; do not continue with a partly remapped copy.

Renumber --apply trusts Catalog Artifact locators as old-path authority. An isolated status directory is insufficient if the copied Catalog still points at operational ZIP paths. Before any copy renumber command, remap every non-NULL Artifact locator and each copied status JSON archive_path so they resolve under the copy root.

## Copy layout

    COPY_ROOT/
      catalog.sqlite
      watchlist.yaml
      Books/                 # copied payloads, preserving relative layout
      crawl-status/          # copied JSON sidecars
      _missing-artifacts/    # deliberately absent references
      work/                  # migration backups and logs

Run the following recipe exactly once on a fresh working copy, before migration, scope sync, planning, or renumbering. Supply both ORIGINAL_CATALOG and ORIGINAL_BOOKS from outside COPY_ROOT. The script rejects the original Catalog itself, any ORIGINAL Catalog path inside COPY_ROOT, and a COPY_ROOT that overlaps the original Books tree. The copied Catalog must be inside COPY_ROOT. For each locator beneath ORIGINAL_BOOKS, preserve its relative path under COPY_ROOT/Books only when that copied file exists. Unmapped, external, missing, and un-copied paths become missing stubs under COPY_ROOT/_missing-artifacts/. Status JSON references use the same mapping. Save this as remap_copy_locators.py and run it against only the copy.

    from __future__ import annotations
    import argparse
    import hashlib
    import json
    import sqlite3
    from pathlib import Path

    def inside(path: Path, root: Path) -> bool:
        try:
            path.resolve(strict=False).relative_to(root.resolve(strict=False))
            return True
        except (OSError, ValueError):
            return False

    def remap(raw: str, original: Path, books: Path, root: Path, key: str) -> str:
        try:
            rel = Path(raw).expanduser().resolve(strict=False).relative_to(original)
        except (OSError, ValueError):
            rel = None
        if rel is not None:
            target = books / rel
            if inside(target, root) and target.is_file():
                return target.resolve(strict=False).as_posix()
        stub = root / "_missing-artifacts" / key / (Path(raw).name or "missing.zip")
        if not inside(stub, root):
            raise RuntimeError(f"stub escaped copy root: {stub}")
        return stub.resolve(strict=False).as_posix()

    def main() -> None:
        ap = argparse.ArgumentParser()
        ap.add_argument("--copy-root", type=Path, required=True)
        ap.add_argument("--catalog", type=Path, required=True)
        ap.add_argument("--original-catalog", type=Path, required=True)
        ap.add_argument("--original-books", type=Path, required=True)
        ap.add_argument("--copy-books", type=Path, required=True)
        ap.add_argument("--status-dir", type=Path, required=True)
        a = ap.parse_args()
        root = a.copy_root.resolve(strict=True)
        catalog = a.catalog.resolve(strict=True)
        original_catalog = a.original_catalog.resolve(strict=True)
        original = a.original_books.resolve(strict=True)
        if not original.is_dir():
            raise RuntimeError(f"ORIGINAL_BOOKS is not a directory: {original}")
        books = a.copy_books.resolve(strict=True)
        status = a.status_dir.resolve(strict=True)
        for name, path in (("Catalog", catalog), ("Books", books), ("status", status)):
            if not inside(path, root):
                raise RuntimeError(f"{name} outside COPY_ROOT: {path}")
        if catalog == original_catalog or catalog.samefile(original_catalog):
            raise RuntimeError("--catalog identifies the original Catalog")
        if inside(original_catalog, root) or inside(root, original_catalog):
            raise RuntimeError("COPY_ROOT overlaps the original Catalog path")
        if inside(original, root) or inside(root, original):
            raise RuntimeError("COPY_ROOT overlaps the original Books tree")

        uri = catalog.as_uri() + "?mode=rw"
        with sqlite3.connect(uri, uri=True) as db:
            rows = db.execute(
                "SELECT id, locator FROM artifacts WHERE locator IS NOT NULL ORDER BY id"
            ).fetchall()
        if any(inside(Path(locator), root) for _, locator in rows):
            raise RuntimeError("already-remapped Catalog; recreate a fresh copy")

        statuses = sorted(status.rglob("*.json"))
        status_updates = []
        for path in statuses:
            if path.is_symlink() or not inside(path, root):
                raise RuntimeError(f"unsafe status path: {path}")
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError(f"status JSON is not an object: {path}")
            old = payload.get("archive_path")
            if isinstance(old, str) and old:
                digest = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]
                payload["archive_path"] = remap(
                    old, original, books, root, f"status-{digest}"
                )
                data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
                status_updates.append((path, data))

        mapped = [
            (aid, remap(loc, original, books, root, f"artifact-{aid}"))
            for aid, loc in rows
        ]
        # This copy is disposable if interrupted between DB and JSON writes.
        # Never continue unless final verification completes.
        db = sqlite3.connect(uri, uri=True)
        try:
            db.execute("BEGIN IMMEDIATE")
            db.executemany(
                "UPDATE artifacts SET locator=? WHERE id=?",
                [(loc, aid) for aid, loc in mapped],
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()
        for path, data in status_updates:
            temp = path.with_name(path.name + ".copy-remap.tmp")
            if temp.exists() or temp.is_symlink() or not inside(temp.parent, root):
                raise RuntimeError(f"unsafe or pre-existing status temp path: {temp}")
            with temp.open("xb") as stream:
                stream.write(data)
            temp.replace(path)

        ro = catalog.as_uri() + "?mode=ro"
        with sqlite3.connect(ro, uri=True) as db:
            final = db.execute(
                "SELECT id, locator FROM artifacts WHERE locator IS NOT NULL ORDER BY id"
            ).fetchall()
        for aid, loc in final:
            if not inside(Path(loc), root):
                raise RuntimeError(f"Artifact {aid} escapes COPY_ROOT: {loc}")
        for path in statuses:
            payload = json.loads(path.read_text(encoding="utf-8"))
            loc = payload.get("archive_path")
            if isinstance(loc, str) and not inside(Path(loc), root):
                raise RuntimeError(f"status JSON escapes COPY_ROOT: {path}")
        print(f"verified {len(final)} Artifact locators and {len(statuses)} status files")

    if __name__ == "__main__":
        main()

Example PowerShell invocation (all paths must be absolute):

    .venv\Scripts\python.exe .\remap_copy_locators.py --copy-root "C:\validation\work-key" --catalog "C:\validation\work-key\catalog.sqlite" --original-catalog "D:\crawler\catalog.sqlite" --original-books "D:\crawler\output\Books" --copy-books "C:\validation\work-key\Books" --status-dir "C:\validation\work-key\crawl-status"

The recipe changes only copied Catalog locators and copied JSON archive_path fields. It does not copy, rename, delete, or repair ZIPs. If it is interrupted or reports an error, discard the working copy and start from the seed.

## Mandatory pre-apply containment check

Immediately before every renumber_archives.py --apply on the copy:

1. Resolve the Catalog, all non-NULL artifacts.locator values, status directory, every sidecar path, and all string archive_path values. Require every resolved path inside resolved COPY_ROOT; reject symlinked parents or sidecars resolving outside it.
2. Confirm no reference enters the operational Books or status tree. Confirm copied ZIP/status contents and Catalog metadata match the intended seed; report missing stubs and do not repair them silently.
3. Pass explicit --catalog, --watchlist, and --status-dir paths rooted under COPY_ROOT to dry-run and apply. Never rely on default paths.
4. Keep the original backup immutable. Discard and recreate an uncertain working copy.

This is a copy-validation guard, not a production migration helper. The locator remap is required because renumber correctly trusts Catalog Artifact.locator values as the old-path authority.
