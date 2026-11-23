"""Lossless, content-deduplicated experiment bundles with verified safe restoration."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import lzma
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile

BLOCK = 1024 * 1024


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(BLOCK), b""):
            h.update(block)
    return h.hexdigest()


def safe_relative(value):
    p = PurePosixPath(value)
    if (not value or p.is_absolute() or str(p) != value or "\\" in value or ":" in value
            or any(s in {"..", ".git", ".venv", "node_modules", "__pycache__"}
                   or s.startswith(".env") or "private" in s.lower() for s in p.parts)):
        raise ValueError("Unsafe artifact path")
    return p


def package(root, files, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    if destination.exists() or not destination.is_relative_to(root):
        raise ValueError("Choose a new archive inside the repository")
    destination.parent.mkdir(parents=True, exist_ok=True)
    index = []
    for path in sorted(set(Path(p).resolve() for p in files)):
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError("Artifact is outside the repository or missing")
        relative = path.relative_to(root).as_posix()
        safe_relative(relative)
        digest = sha(path)
        index.append({"path": relative, "size_bytes": path.stat().st_size,
                      "sha256": digest, "member": "blobs/"+digest})
    staging = destination.with_suffix(".building.zip")
    try:
        with zipfile.ZipFile(staging, "x", compression=zipfile.ZIP_STORED) as z:
            stored = set()
            for item in index:
                if item["member"] not in stored:
                    z.write(root/item["path"], item["member"])
                    stored.add(item["member"])
                if sha(root/item["path"]) != item["sha256"]:
                    raise ValueError("Source changed during packaging")
            z.writestr("artifact-index.json", json.dumps(index, ensure_ascii=False, indent=2))
        with staging.open("rb") as source, lzma.open(destination, "xb", preset=3) as target:
            shutil.copyfileobj(source, target, BLOCK)
    finally:
        if staging.exists():
            staging.unlink()
    return {"file": destination.relative_to(root).as_posix(), "sha256": sha(destination),
            "archive_bytes": destination.stat().st_size, "files": len(index),
            "original_bytes": sum(i["size_bytes"] for i in index)}


@contextmanager
def open_archive(bundle, temporary):
    with tempfile.TemporaryDirectory(dir=temporary, prefix="artifact-") as stage:
        path = Path(stage)/"reading.zip"
        with lzma.open(bundle, "rb") as source, path.open("xb") as target:
            shutil.copyfileobj(source, target, BLOCK)
        with zipfile.ZipFile(path) as z:
            yield z


def unpack(bundle, root, expected_sha=None, verify_only=False, portable_configs=True):
    bundle, root = Path(bundle).resolve(), Path(root).resolve()
    if root.drive and root.drive.lower() != "d:":
        raise ValueError("Project data must be restored on D drive")
    if expected_sha and sha(bundle) != expected_sha:
        raise ValueError("Archive SHA256 mismatch; run git lfs pull first")
    root.mkdir(parents=True, exist_ok=True)
    created = []
    with open_archive(bundle, root) as z:
        index = json.loads(z.read("artifact-index.json"))
        seen = set()
        for item in index:
            relative = safe_relative(item["path"])
            target = (root/str(relative)).resolve()
            if not target.is_relative_to(root) or str(relative) in seen:
                raise ValueError("Duplicate or escaping artifact path")
            seen.add(str(relative))
            if item["member"] != "blobs/"+item["sha256"]:
                raise ValueError("Invalid content-addressed member")
            if z.getinfo(item["member"]).file_size != item["size_bytes"]:
                raise ValueError("Archive member size differs")
            h = hashlib.sha256()
            with z.open(item["member"]) as source:
                for block in iter(lambda: source.read(BLOCK), b""):
                    h.update(block)
            if h.hexdigest() != item["sha256"]:
                raise ValueError("Archive member hash differs")
            if target.exists() and (not target.is_file() or sha(target) != item["sha256"]):
                raise ValueError("Preserve existing files: restore into a new folder")
        if not verify_only:
            for item in index:
                target = root/item["path"]
                if target.exists():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(item["member"]) as source, target.open("xb") as writer:
                    shutil.copyfileobj(source, writer, BLOCK)
                if sha(target) != item["sha256"]:
                    raise ValueError("Restored file hash differs")
                created.append(target)
    rebased = []
    if portable_configs and not verify_only:
        import yaml
        for target in created:
            if target.name == "dataset.yaml" and target.relative_to(root).parts[0] == "datasets":
                raw = yaml.safe_load(target.read_text(encoding="utf-8-sig"))
                if not (target.parent/"images").is_dir():
                    continue
                # Keep original settings byte-for-byte beside the portable execution config.
                target.with_name("dataset.original.yaml").write_bytes(target.read_bytes())
                raw["path"] = "."
                target.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
                rebased.append(target.relative_to(root).as_posix())
    return {"archive_sha256": sha(bundle), "verified_files": len(index),
            "restored_files": len(created), "portable_configs": rebased, "root": str(root)}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", required=True, type=Path)
    p.add_argument("--root", required=True, type=Path)
    p.add_argument("--sha256")
    p.add_argument("--verify-only", action="store_true")
    p.add_argument("--keep-original-configs", action="store_true")
    a = p.parse_args()
    print(json.dumps(unpack(a.bundle, a.root, a.sha256, a.verify_only, not a.keep_original_configs), ensure_ascii=False, indent=2))
