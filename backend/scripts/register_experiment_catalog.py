"""Register experiment metadata, exact YOLO labels and JSONL evidence in the team's catalog.

File bytes stay on the producer filesystem. This tool never creates tables or
copies environment files, private stream URLs, or external datasets not used here.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

import yaml
from dotenv import dotenv_values, load_dotenv


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as reader:
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class Builder:
    def __init__(self, repo, team_root, env_file, code_ref="unspecified team schema source"):
        self.repo = repo.resolve()
        self.workspace = self.repo.parent
        self.records = []
        self.file_cache = {}
        self.excluded = []
        self.code_ref = code_ref
        load_dotenv(env_file, override=True)
        sys.path.insert(0, str(team_root.resolve()))
        # Reuse the team's actual validation and fingerprint contract.
        from backend.app.routers.catalog import RecordIn, FileIn, LogIn
        self.RecordIn, self.FileIn, self.LogIn = RecordIn, FileIn, LogIn
        self.secrets = [v for k, v in dotenv_values(self.repo / ".env").items()
                        if v and "KEY" in k and len(v) > 12]
        from sqlalchemy.engine import make_url
        password = make_url(os.environ["DATABASE_URL"]).password
        if password:
            self.secrets.append(password)

    def safe_text(self, text):
        if any(secret in text for secret in self.secrets):
            raise ValueError("Secret value found in proposed catalog content")
        if re.search(r"wmsAuthSign|nimblesessionid|postgresql\+psycopg://|apiKey=", text, re.I):
            raise ValueError("Credential or signed-stream content found")
        return text

    def read_json(self, path):
        return json.loads(self.safe_text(Path(path).read_text(encoding="utf-8-sig")))

    def paths(self, folder):
        return [p for p in sorted(Path(folder).rglob("*")) if p.is_file()
                and not any(x in {".git", ".venv", "__pycache__", "node_modules"}
                            or x.startswith(".env") or "private" in x.lower()
                            for x in p.parts)]

    def info(self, path):
        path = Path(path).resolve()
        if not path.is_relative_to(self.workspace):
            raise ValueError("Artifact is outside the D-drive workspace")
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        if key not in self.file_cache:
            role = "image" if path.suffix.lower() in {".jpg", ".jpeg", ".png"} else (
                "model" if path.suffix.lower() in {".pt", ".onnx", ".xml"} else (
                    "label" if "labels" in path.parts else "artifact"))
            value = self.FileIn(path=path.relative_to(self.workspace).as_posix(),
                                size_bytes=stat.st_size, sha256=file_hash(path), role=role).model_dump()
            if (path.stat().st_size, path.stat().st_mtime_ns) != (stat.st_size, stat.st_mtime_ns):
                raise ValueError("Artifact changed while hashing")
            self.file_cache[key] = value
        return self.file_cache[key]

    def add(self, slug, kind, origin, files=(), details=None, parents=(), status="completed", logs=False):
        pinned = sorted([self.info(p) for p in set(map(Path, files))], key=lambda f: f["path"])
        details = dict(details or {})
        details["storage"] = {"kind": "local_files", "root": str(self.workspace),
                              "availability": "requires_access_to_producer_filesystem",
                              "file_bytes_uploaded": False}
        details["file_manifest_sha256"] = digest(pinned)
        body = {"kind": kind, "title": slug, "owner": "TwinSight 팀 / 이진규 실험",
                "data_origin": origin, "status": status, "camera_id": None,
                "detection_run_id": None, "parents": sorted(set(parents)), "details": details}
        body["record_id"] = (slug[:98] + "-" + digest({**body, "files": pinned})[:16])
        body = self.RecordIn(**body).model_dump()
        self.safe_text(canonical(body))
        lines = []
        skipped = []
        if logs:
            for item in pinned:
                p = self.workspace / item["path"]
                if p.suffix.lower() not in {".jsonl", ".log", ".csv"}:
                    continue
                stream = p.name[:90] + "-" + hashlib.sha256(item["path"].encode()).hexdigest()[:12]
                for number, message in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), 1):
                    message = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", message)
                    self.safe_text(message)
                    if len(message) > 16384:
                        skipped.append({"path": item["path"], "line": number, "reason": "catalog line limit"})
                        continue
                    lines.append(self.LogIn(stream=stream, line_no=number, message=message).model_dump())
        if skipped:
            self.excluded.extend(skipped)
        self.records.append({"record": body, "fingerprint": digest(body), "files": pinned, "logs": lines})
        print("prepared", slug, "files", len(pinned), "log_lines", len(lines), flush=True)
        return body["record_id"]

    def prepare(self):
        repo = self.repo
        profile = self.add("simulation-geumchon-city-lab", "simulation", "synthetic",
                           list((repo / "simulation/TwinSightSim/RealCctv").glob("*.json")) +
                           [repo / "simulation/TwinSightSim/Assets/TwinSight/Scripts/RoadScenarioDirector.cs"],
                           {"synthetic_only": True, "camera_profile": "restored Geumchon"})
        captures = {}
        exports = repo / "simulation/TwinSightSim/TwinSightExport"
        for folder in sorted(exports.iterdir()):
            truth = folder / "ground_truth.jsonl"
            if not truth.is_file():
                continue
            n = sum(1 for line in truth.open(encoding="utf-8-sig") if line.strip())
            if not n:
                self.excluded.append({"path": str(folder), "reason": "empty capture"})
                continue
            key = self.add("capture-" + folder.name, "capture", "synthetic", self.paths(folder),
                           {"frames": n, "source_folder": str(folder), "human_review_complete": False,
                            "camera": self.read_json(folder / "camera.json"),
                            "capture_readiness": "archive; experimental captures included"},
                           [profile], status="draft", logs=True)
            captures[str(folder.resolve())] = key
        # Queue detector training used a subset of frames, not entire clips.
        selected = repo / "runs/queue-detector/selected-sessions"
        if selected.exists():
            for folder in sorted(selected.iterdir()):
                if not (folder / "ground_truth.jsonl").exists():
                    continue
                source = next((v for k, v in reversed(list(captures.items()))
                               if Path(k).name.startswith(folder.name + "_")), None)
                captures[str(folder.resolve())] = self.add(
                    "capture-selected-" + folder.name, "capture", "synthetic", self.paths(folder),
                    {"source_folder": str(folder), "frame_selection": [0,2,4,6,8,12,20,30]},
                    [source] if source else [profile], logs=True)
        datasets = {}
        pending = [p for p in sorted((repo / "datasets").iterdir()) if (p / "dataset.yaml").is_file()]
        while pending:
            progress = False
            for folder in pending[:]:
                provenance = self.read_json(folder / "provenance.json") if (folder / "provenance.json").exists() else {}
                dependencies = [Path(provenance[k]).parent.name for k in ("full_data", "detail_data") if k in provenance]
                if folder.name == "queue-retention":
                    dependencies.append("geumchon-focus")
                if any(name not in datasets for name in dependencies):
                    continue
                cfg = yaml.safe_load((folder / "dataset.yaml").read_text(encoding="utf-8"))
                names = cfg["names"]
                classes = list(names.values()) if isinstance(names, dict) else names
                subsets = {}
                for split in ("train", "val", "test"):
                    samples = []
                    for image in sorted((folder / "images" / split).glob("*")):
                        if not image.is_file():
                            continue
                        label = folder / "labels" / split / (image.stem + ".txt")
                        # Preserve Windows CRLF so the DB label text reproduces
                        # the exact bytes named by label_sha256.
                        text = label.read_bytes().decode("utf-8")
                        boxes = [[float(v) for v in line.split()] for line in text.splitlines() if line.strip()]
                        if any(len(b) != 5 or not all(math.isfinite(v) for v in b)
                               or b[0] != int(b[0]) or not 0 <= b[0] < len(classes)
                               or any(not 0 <= v <= 1 for v in b[1:]) for b in boxes):
                            raise ValueError("Invalid YOLO label")
                        samples.append({"image": self.info(image)["path"], "image_sha256": self.info(image)["sha256"],
                                        "label": self.info(label)["path"], "label_sha256": self.info(label)["sha256"],
                                        "label_text": text, "boxes_yolo": boxes})
                    subsets[split] = samples
                parents = [datasets[name] for name in dependencies]
                for sources in provenance.get("sessions", {}).values():
                    parents += [captures[str(Path(s).resolve())] for s in sources if str(Path(s).resolve()) in captures]
                key = self.add("dataset-" + folder.name, "dataset", "synthetic", self.paths(folder),
                               {"classes": classes, "split_counts": {s: len(v) for s, v in subsets.items()},
                                "provenance": provenance, "human_review_complete": False,
                                "source_folder": str(folder)}, parents,
                               status="draft" if folder.name == "scenario-prototype" else "completed")
                datasets[folder.name] = key
                for split, samples in subsets.items():
                    for part, start in enumerate(range(0, len(samples), 100)):
                        self.add(f"labels-{folder.name}-{split}-{part:03}", "dataset", "synthetic",
                                 details={"type": "yolo_split_annotations", "dataset": folder.name,
                                          "split": split, "classes": classes, "samples": samples[start:start+100],
                                          "exact_label_text_in_database": True}, parents=[key])
                pending.remove(folder)
                progress = True
            if not progress:
                raise ValueError("Dataset provenance dependency cannot be resolved")
        models = {}
        official = repo / "detection/models/yolo11n.pt"
        models[file_hash(official)] = self.add("model-yolo11n-coco", "model", "real", [official],
                                             {"external_pretrained": True, "source": "Ultralytics COCO baseline"})
        model_files = list((repo / "detection/models").glob("*.pt"))
        for folder in sorted((repo / "runs/detection").glob("train*/*")):
            if not (folder / "args.yaml").exists():
                continue
            args = yaml.safe_load((folder / "args.yaml").read_text(encoding="utf-8"))
            data_path = Path(args["data"])
            cfg = yaml.safe_load(data_path.read_text(encoding="utf-8"))
            dataset_name = Path(cfg["path"]).name
            parents = [datasets[dataset_name]] if dataset_name in datasets else []
            source_weight = Path(str(args["model"]))
            if source_weight.is_file() and file_hash(source_weight) in models:
                parents.append(models[file_hash(source_weight)])
            csv_path = folder / "results.csv"
            with csv_path.open(encoding="utf-8-sig", newline="") as f:
                metric_rows = list(csv.DictReader(f))
            metrics = {k.strip(): float(v) if math.isfinite(float(v)) else None for k, v in metric_rows[-1].items()}
            training = self.add("training-" + folder.parent.name + "-" + folder.name, "training", "synthetic",
                                self.paths(folder) + [data_path],
                                {"args": args, "epochs_recorded": len(metric_rows), "last_epoch_metrics": metrics,
                                 "dataset_name": dataset_name, "actual_cctv_performance": False}, parents, logs=True)
            best = folder / "weights/best.pt"
            if best.exists():
                sha = file_hash(best)
                aliases = [p for p in model_files if file_hash(p) == sha]
                models[sha] = self.add("model-" + folder.name + "-" + sha[:12], "model", "synthetic",
                                       [best, *aliases], {"sha256": sha, "last_epoch_metrics": metrics}, [training])
        queue = repo / "runs/queue-v3"
        manifest = self.read_json(queue / "manifest.json")
        temporal_parents = [captures[str(Path(e["source"]).resolve())] for e in manifest]
        temporal = self.add("dataset-stop-zone-temporal", "dataset", "synthetic",
                            [queue / "candidates.jsonl", queue / "manifest.json"],
                            {"type": "temporal_collision_features", "split_clips": {"train":20,"val":10,"test":10},
                             "physics_contact_labels": True}, temporal_parents, logs=True)
        queue_model = models[file_hash(repo / "detection/models/simulation-cctv-queue.pt")]
        report = self.read_json(queue / "training-report.json")
        training = self.add("training-stop-zone-final", "training", "synthetic", [queue / "training-report.json"],
                            report | {"test_used_for_training": False}, [temporal, queue_model])
        for p in sorted((repo / "detection/models").glob("stop-zone-collision*.xml")):
            metadata = self.read_json(p.with_suffix(".json"))
            sha = file_hash(p)
            models[sha] = self.add("model-" + p.stem, "model", "synthetic", [p,p.with_suffix(".json")], metadata,
                                   [training] if p.stem.endswith("final") else [queue_model],
                                   status="completed" if p.stem.endswith("final") else "draft")
        real_capture = repo / "runs/real-cctv-20261022/hls-geumchon-v2"
        real = self.add("capture-real-geumchon-20261022", "capture", "real", self.paths(real_capture),
                        self.read_json(real_capture / "capture.json") | {"annotations_available": False}, logs=True)
        day_folder = self.workspace / "reviews/geumchon-real-2b75753/simulation/TwinSightSim/RealCctv/geumchon_frames"
        real_day = self.add("capture-real-geumchon-day-20261019", "capture", "real", self.paths(day_folder),
                            {"frames": 16, "annotations_available": False, "continuous_video": False,
                             "source_git_commit": "2b75753"})
        for name in ("synthetic-live", "coco-live", "synthetic-model", "coco-baseline"):
            folder = real_capture.parent / name
            model_path = "simulation-cctv-queue.pt" if name.startswith("synthetic") else "yolo11n.pt"
            self.add("detection-real-geumchon-" + name, "detection", "real", self.paths(folder),
                     self.read_json(folder / "summary.json") | {"ground_truth_available": False,
                      "input_kind": "night_continuous_capture" if name.endswith("live") else "day_separate_stills"},
                     [real, models[file_hash(repo / "detection/models" / model_path)]] if name.endswith("live")
                     else [real_day, models[file_hash(repo / "detection/models" / model_path)]], logs=True)
        mappings = {"synthetic-v2": ("synthetic", "simulation-detection.pt"),
                    "geumchon-v1": ("synthetic", "simulation-cctv.pt"),
                    "stop-zone-v2": ("synthetic", "stop-zone-collision-final.xml"),
                    "real-cctv-20261022": ("real", "simulation-cctv-queue.pt")}
        for name, (origin, model_name) in mappings.items():
            folder = repo / "docs/validation" / name
            files = self.paths(folder)
            if name == "stop-zone-v2":
                files += self.paths(queue)
            self.add("evaluation-" + name, "evaluation", origin, files,
                     {"ground_truth_accident_clips_available": origin != "real",
                      "reports": {p.name: self.read_json(p) for p in folder.glob("*.json")
                                  if p.stat().st_size < 131072}},
                     [models[file_hash(repo / "detection/models" / model_name)]], logs=True)
        self.excluded.append({"path": "datasets/public-sources", "reason": "downloaded but not used for training"})
        return {"format": "twinsight-catalog-import-v1", "workspace": str(self.workspace),
                "source_catalog_code": self.code_ref,
                "records": self.records, "excluded": self.excluded,
                "file_bytes_uploaded": False}


def upload(manifest, env_file, out):
    import psycopg
    from psycopg.types.json import Json
    cfg = dotenv_values(env_file)
    if cfg.get("DATABASE_SCHEMA") != "twinsight" or cfg.get("DATABASE_AUTO_CREATE") != "false":
        raise ValueError("Expected existing twinsight schema with automatic creation disabled")
    entries = manifest["records"]
    ids = [x["record"]["record_id"] for x in entries]
    all_ids = set(ids)
    seen = set()
    external_parents = set()
    for entry in entries:
        record = entry["record"]
        if record["record_id"] in seen or any(p in all_ids and p not in seen for p in record["parents"]):
            raise ValueError("Expected unique records with previously declared immutable parents")
        external_parents.update(p for p in record["parents"] if p not in all_ids)
        seen.add(record["record_id"])
    expected_files = [(x["record"]["record_id"],f["path"],f["size_bytes"],f["sha256"],f["role"])
                      for x in entries for f in x["files"]]
    expected_logs = [(x["record"]["record_id"],l["stream"],l["line_no"],l["message"])
                     for x in entries for l in x["logs"]]
    expected_parents = [(x["record"]["record_id"],p) for x in entries for p in x["record"]["parents"]]
    with psycopg.connect(cfg["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://",1),
                        connect_timeout=12, prepare_threshold=None) as conn:
        conn.execute("SET LOCAL statement_timeout='120s'")
        conn.execute("SET LOCAL lock_timeout='5s'")
        if external_parents:
            found = {row[0] for row in conn.execute(
                "SELECT record_id FROM twinsight.catalog_records WHERE record_id=ANY(%s)",
                (sorted(external_parents),)).fetchall()}
            if found != external_parents:
                raise ValueError("An external parent is missing or inaccessible")
        existing = dict(conn.execute("SELECT record_id,fingerprint FROM twinsight.catalog_records WHERE record_id=ANY(%s)",(ids,)).fetchall())
        for entry in entries:
            if entry["fingerprint"] != digest(entry["record"]):
                raise ValueError("Manifest fingerprint mismatch")
            key = entry["record"]["record_id"]
            if key in existing and existing[key] != entry["fingerprint"]:
                raise ValueError("Existing immutable catalog record differs")
        with conn.cursor() as cur:
            cur.executemany("""INSERT INTO twinsight.catalog_records
                (record_id,kind,title,owner,data_origin,status,camera_id,detection_run_id,details,fingerprint,created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,now()) ON CONFLICT(record_id) DO NOTHING""",
                [(r["record_id"],r["kind"],r["title"],r["owner"],r["data_origin"],r["status"],r["camera_id"],
                  r["detection_run_id"],Json(r["details"]),e["fingerprint"]) for e in entries for r in [e["record"]]])
            cur.executemany("INSERT INTO twinsight.catalog_parents(record_id,parent_id) VALUES(%s,%s) ON CONFLICT DO NOTHING", expected_parents)
            cur.executemany("INSERT INTO twinsight.catalog_files(record_id,path,size_bytes,sha256,role) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(record_id,path) DO NOTHING",expected_files)
            cur.executemany("INSERT INTO twinsight.catalog_logs(record_id,stream,line_no,message) VALUES(%s,%s,%s,%s) ON CONFLICT(record_id,stream,line_no) DO NOTHING",expected_logs)
        # Read back complete contents before committing; any mismatch rolls back.
        actual_files = conn.execute("SELECT record_id,path,size_bytes,sha256,role FROM twinsight.catalog_files WHERE record_id=ANY(%s)",(ids,)).fetchall()
        actual_logs = conn.execute("SELECT record_id,stream,line_no,message FROM twinsight.catalog_logs WHERE record_id=ANY(%s)",(ids,)).fetchall()
        actual_parents = conn.execute("SELECT record_id,parent_id FROM twinsight.catalog_parents WHERE record_id=ANY(%s)",(ids,)).fetchall()
        for expected, actual in [(expected_files,actual_files),(expected_logs,actual_logs),(expected_parents,actual_parents)]:
            if sorted(expected) != sorted(actual):
                raise ValueError("Database readback differs; transaction rolled back")
        actual_records = conn.execute("SELECT record_id,details FROM twinsight.catalog_records WHERE record_id=ANY(%s)",(ids,)).fetchall()
        expected_details = {x["record"]["record_id"]:x["record"]["details"] for x in entries}
        if len(actual_records) != len(entries) or any(expected_details[key] != details for key,details in actual_records):
            raise ValueError("Record details readback differs")
        labels = [s for _,d in actual_records if d.get("type")=="yolo_split_annotations" for s in d["samples"]]
        if any(hashlib.sha256(s["label_text"].encode()).hexdigest()!=s["label_sha256"] for s in labels):
            raise ValueError("Exact YOLO label bytes did not round-trip")
        result = {"committed": True,"records":len(entries),"new_records":len(entries)-len(existing),
                  "file_references":len(actual_files),"log_lines":len(actual_logs),"parent_links":len(actual_parents),
                  "exact_yolo_labels":len(labels),"label_objects":sum(len(s["boxes_yolo"]) for s in labels),
                  "records_by_kind":dict(Counter(x["record"]["kind"] for x in entries)),
                  "readback_verified":True,"image_video_model_bytes_uploaded":False,
                  "source_root":manifest["workspace"],"schema_changed":False,
                  "manifest_sha256":digest(manifest)}
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=["prepare","upload"])
    parser.add_argument("--repo",type=Path,default=Path(__file__).resolve().parents[2])
    parser.add_argument("--team-code-root",type=Path)
    parser.add_argument("--team-code-ref",default="unspecified team schema source")
    parser.add_argument("--env-file",type=Path,default=Path(".env.database"))
    parser.add_argument("--manifest",type=Path,required=True)
    parser.add_argument("--report",type=Path)
    args=parser.parse_args()
    if args.mode=="prepare":
        if args.manifest.exists():
            raise ValueError("Preserve prepared snapshots: choose a new manifest")
        builder=Builder(args.repo,args.team_code_root or args.repo,args.env_file,args.team_code_ref)
        result=builder.prepare()
        args.manifest.parent.mkdir(parents=True,exist_ok=True)
        args.manifest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
        print(json.dumps({"records":len(result["records"]),"files":sum(len(e["files"]) for e in result["records"]),
                          "logs":sum(len(e["logs"]) for e in result["records"]),"bytes_uploaded":False}))
    else:
        result=upload(json.loads(args.manifest.read_text(encoding="utf-8")),args.env_file,args.report or args.manifest.with_name("registration-report.json"))
        print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
