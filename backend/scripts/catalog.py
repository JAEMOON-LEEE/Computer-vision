"""팀 산출물 등록·검증·내보내기. 원본 파일을 이동하거나 서버로 업로드하지 않는다."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.routers.catalog import FileIn, LogIn, RecordIn

BLOCKED = {".git", ".venv", "__pycache__", ".pytest_cache"}
JSON_DETAILS = {"camera.json", "control_points.json", "provenance.json", "session.json", "summary.json", "metrics.json", "dataset-check.json"}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Non-finite JSON: {value}")))


def write_json(path, body):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(body, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def safe_file(root, relative):
    # Use the same path grammar as the API and reject symlink escapes.
    FileIn(path=relative, size_bytes=0, sha256="0" * 64, role="validate")
    parts = Path(relative).parts
    if any(part in BLOCKED or part == ".env" or part.startswith(".env.") for part in parts):
        raise ValueError("Secret/environment files and tool internals cannot be registered")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Missing file or path outside artifact root: {relative}")
    return path


def file_info(root, entry):
    path = safe_file(root, entry["path"])
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError(f"File is changing; register after capture/training stops: {entry['path']}")
    return FileIn(path=entry["path"], role=entry.get("role", "artifact"),
                  size_bytes=after.st_size, sha256=digest.hexdigest()).model_dump()


def prepare(folder, record, output):
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError("Artifact folder does not exist")
    output = Path(output).resolve()
    files, logs, details = [], [], dict(record.get("details", {}))
    details["storage"] = {"kind": "local_files", "root": str(folder),
                          "availability": "requires_access_to_producer_filesystem"}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.resolve() == output:
            continue
        relative = path.relative_to(folder).as_posix()
        if any(p in BLOCKED or p == ".env" or p.startswith(".env.") for p in path.relative_to(folder).parts):
            continue
        safe_file(folder, relative)
        role = "model" if path.suffix.lower() in {".pt", ".onnx"} else "artifact"
        if path.suffix.lower() == ".log":
            role = "log"
            logs.append(relative)
        files.append({"path": relative, "role": role})
        if path.name in JSON_DETAILS and path.stat().st_size <= 131072:
            details.setdefault("reports", {})[relative] = read_json(path)
        if path.name == "results.csv":
            with path.open(encoding="utf-8-sig", newline="") as stream:
                rows = csv.DictReader(stream)
                last, count = None, 0
                for last in rows:
                    count += 1
            if last:
                final = {}
                for key, value in last.items():
                    if key is None:
                        raise ValueError("Malformed results.csv")
                    try:
                        number = float(value)
                        final[key.strip()] = number if math.isfinite(number) else None
                    except (ValueError, TypeError):
                        final[key.strip()] = value
                details.setdefault("metric_summaries", {})[relative] = {"rows": count, "last_row": final}
    if not files:
        raise ValueError("No artifact files found")
    record = RecordIn(**{**record, "details": details}).model_dump()
    # Pin hashes at prepare time: retries must not silently register changed bytes.
    pinned = [file_info(folder, item) for item in files]
    write_json(output, {"record": record, "root": str(folder), "files": pinned, "log_files": logs})
    return {"files": len(files), "log_files": len(logs)}


def load_manifest(path):
    path = Path(path).resolve()
    manifest = read_json(path)
    record = RecordIn(**manifest["record"]).model_dump()
    root = (path.parent / manifest.get("root", ".")).resolve()
    files = [FileIn(**item).model_dump() for item in manifest.get("files", [])]
    names = [item["path"] for item in files]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate file path in manifest")
    for item in files:
        if file_info(root, item) != item:
            raise ValueError(f"File changed since manifest creation: {item['path']}")
    logs = manifest.get("log_files", [])
    if len(set(logs)) != len(logs) or not set(logs).issubset(names):
        raise ValueError("Log files must be unique and included in pinned files")
    return record, root, files, logs


def log_rows(root, paths):
    for relative in paths:
        with safe_file(root, relative).open(encoding="utf-8-sig", errors="strict") as stream:
            for number, line in enumerate(stream, 1):
                yield LogIn(stream=relative, line_no=number, message=line.rstrip("\r\n")).model_dump()


def checked(response):
    response.raise_for_status()
    return response.json()


def batches(rows, size=200):
    batch = []
    for row in rows:
        batch.append(row)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def register(client, manifest_path):
    record, root, files, logs = load_manifest(manifest_path)
    # Copy logs into a verified snapshot: an appending producer must not change the
    # content between preflight validation and the later paged HTTP requests.
    with tempfile.TemporaryDirectory(prefix="twinsight-catalog-") as tmp:
        snapshot = Path(tmp)
        by_path = {item["path"]: item for item in files}
        for relative in logs:
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(safe_file(root, relative), target)
            if file_info(snapshot, by_path[relative]) != by_path[relative]:
                raise ValueError(f"Log changed while preparing registration: {relative}")
        for _ in log_rows(snapshot, logs):
            pass
        checked(client.post("/catalog/records", json=record))
        prefix = "/catalog/records/" + record["record_id"]
        for batch in batches(files):
            checked(client.post(prefix + "/files", json=batch))
        count = 0
        for batch in batches(log_rows(snapshot, logs)):
            checked(client.post(prefix + "/logs", json=batch))
            count += len(batch)
    return {"record_id": record["record_id"], "files": len(files), "log_lines": count}


def export_record(client, record_id, output):
    prefix = "/catalog/records/" + record_id
    record = checked(client.get(prefix))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "record.json", record)
    for collection in ("files", "logs"):
        cursor = 0
        with (output / f"{collection}.jsonl").open("x", encoding="utf-8") as stream:
            while True:
                page = checked(client.get(prefix + "/" + collection, params={"after_id": cursor, "limit": 500}))
                for row in page["items"]:
                    stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")
                cursor = page["next_after_id"]
                if cursor is None:
                    break
    write_json(output / "export-complete.json", {"record_id": record_id, "includes_file_bytes": False})


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    make = commands.add_parser("prepare")
    make.add_argument("--folder", required=True, type=Path)
    make.add_argument("--record-id", required=True)
    make.add_argument("--kind", required=True)
    make.add_argument("--title", required=True)
    make.add_argument("--owner", required=True)
    make.add_argument("--origin", required=True, choices=["real", "synthetic", "mixed", "unspecified"])
    make.add_argument("--status", default="draft", choices=["draft", "running", "completed", "failed"])
    make.add_argument("--camera-id")
    make.add_argument("--detection-run-id")
    make.add_argument("--parent", action="append", default=[])
    make.add_argument("--out", required=True, type=Path)
    for name in ("register", "verify"):
        sub = commands.add_parser(name)
        sub.add_argument("--manifest", required=True, type=Path)
        if name == "register":
            sub.add_argument("--api", default="http://localhost:8000")
    export = commands.add_parser("export")
    export.add_argument("--record-id", required=True)
    export.add_argument("--out", required=True, type=Path)
    export.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            record = {"record_id": args.record_id, "kind": args.kind, "title": args.title, "owner": args.owner,
                      "data_origin": args.origin, "status": args.status, "camera_id": args.camera_id,
                      "detection_run_id": args.detection_run_id, "parents": args.parent}
            result = prepare(args.folder, record, args.out)
        elif args.command == "verify":
            record, _, files, _ = load_manifest(args.manifest)
            result = {"record_id": record["record_id"], "verified_files": len(files)}
        else:
            with httpx.Client(base_url=args.api, timeout=60) as client:
                if args.command == "register":
                    result = register(client, args.manifest)
                else:
                    export_record(client, args.record_id, args.out)
                    result = {"exported_to": str(args.out)}
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except httpx.HTTPStatusError as exc:
        print(f"API HTTP {exc.response.status_code}: 등록 내용과 상위 자료 ID를 확인하세요.", file=sys.stderr)
        return 1
    except (ValueError, OSError, KeyError, httpx.HTTPError) as exc:
        print(f"등록 실패 ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
