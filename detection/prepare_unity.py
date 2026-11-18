"""Convert explicit Unity capture sessions to YOLO labels without random frame splitting."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path

import yaml

from .sources import confined_image, decode_image
from .taxonomy import CATEGORIES


def audit_hazard_splits(splits):
    """Fail closed on missing provenance, collision episodes, or cross-split reuse."""
    seeds, episodes, hashes = {}, {}, {}
    counts = {}
    for split, sessions in splits.items():
        counts[split] = 0
        for session in sessions:
            root = Path(session).resolve()
            with (root / "ground_truth.jsonl").open(encoding="utf-8-sig") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    scenario = record.get("scenario") or {}
                    seed, episode, kind = scenario.get("seed"), scenario.get("episode"), scenario.get("scenario")
                    if type(seed) is not int or type(episode) is not int or not isinstance(kind, str) or not kind:
                        raise ValueError(f"Missing seed, episode or scenario in {root}")
                    if kind not in {"Normal", "Pothole", "FallingDebris"}:
                        raise ValueError(f"Unsupported or collision scenario {kind!r} in {root}")
                    for mapping, key, label in ((seeds, seed, "seed"), (episodes, (seed, episode), "episode")):
                        if key in mapping and mapping[key] != split:
                            raise ValueError(f"{label} leakage between {mapping[key]} and {split}: {key}")
                        mapping[key] = split
                    image = confined_image(root, record["image"])
                    digest = hashlib.sha256(image.read_bytes()).hexdigest()
                    if digest in hashes and hashes[digest] != split:
                        raise ValueError(f"Image leakage between {hashes[digest]} and {split}: {image}")
                    hashes[digest] = split
                    counts[split] += 1
        if sessions and not counts[split]:
            raise ValueError(f"No frames in {split}")
    return {"frames": counts, "unique_seeds": len(seeds), "unique_seed_episodes": len(episodes),
            "limitations": "Exact hashes and recorded seed/episode only; shared assets/camera and near duplicates are not ruled out."}


def prepare_unity(splits, output, classes, hazard_audit=False):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Dataset output must be empty")
    if not classes or len(set(classes)) != len(classes) or not set(classes).issubset(CATEGORIES):
        raise ValueError("Use unique project class names")
    roots = [Path(root).resolve() for sessions in splits.values() for root in sessions]
    if len(set(roots)) != len(roots):
        raise ValueError("A capture session cannot appear in multiple splits")
    audit = audit_hazard_splits(splits) if hazard_audit else None
    output.mkdir(parents=True, exist_ok=True)
    names = {name: index for index, name in enumerate(classes)}
    report = {"synthetic_only": True, "human_review_complete": False,
              "class_names": classes, "sessions": {}, "warning": "Unity boxes include occluded geometry; inspect labels before final experiments"}
    if audit is not None:
        report["hazard_split_audit"] = audit
    config = {"path": str(output.resolve()), "names": dict(enumerate(classes))}
    for split, sessions in splits.items():
        if not sessions:
            continue
        config[split] = f"images/{split}"
        images, labels = output / "images" / split, output / "labels" / split
        images.mkdir(parents=True); labels.mkdir(parents=True)
        count = 0
        frame_names = set()
        for session in sessions:
            root = Path(session).resolve()
            prefix = hashlib.sha256(str(root).encode()).hexdigest()[:10]
            report["sessions"].setdefault(split, []).append(str(root))
            with (root / "ground_truth.jsonl").open(encoding="utf-8-sig") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    image = confined_image(root, record["image"])
                    height, width = decode_image(image).shape[:2]
                    if (height, width) != (record["height"], record["width"]):
                        raise ValueError("Image dimensions differ from Unity metadata")
                    stem = f'{prefix}_{record["frame"]:06d}'
                    if stem in frame_names:
                        raise ValueError("Duplicate frame in Unity capture")
                    frame_names.add(stem)
                    rows = []
                    for obj in record.get("objects", []):
                        name = obj["class_name"]
                        if name not in names:
                            continue
                        x1, y1, x2, y2 = obj["bbox_xyxy"]
                        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
                            raise ValueError("Non-finite Unity bounding box")
                        x1, x2 = max(0, min(width, x1)), max(0, min(width, x2))
                        y1, y2 = max(0, min(height, y1)), max(0, min(height, y2))
                        if x2 - x1 < 4 or y2 - y1 < 4:
                            continue
                        rows.append(f'{names[name]} {(x1+x2)/2/width:.8f} {(y1+y2)/2/height:.8f} {(x2-x1)/width:.8f} {(y2-y1)/height:.8f}')
                    shutil.copy2(image, images / (stem + image.suffix.lower()))
                    (labels / (stem + ".txt")).write_text("\n".join(rows), encoding="utf-8")
                    count += 1
        report.setdefault("frame_counts", {})[split] = count
    (output / "dataset.yaml").write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    (output / "provenance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
