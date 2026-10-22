"""Compare detectors by class name, including COCO + hazard baselines with different IDs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .dataset import check_dataset
from .engine import Detector
from .sources import IMAGE_EXTENSIONS, decode_image
from .warnings import iou


def average_precision(samples, positives):
    if not positives:
        return None
    ranked = sorted(samples, key=lambda row: -row[0])
    true = np.cumsum([row[1] for row in ranked], dtype=float)
    false = np.cumsum([not row[1] for row in ranked], dtype=float)
    recall = true / positives
    precision = true / np.maximum(true + false, 1)
    ap = np.mean([precision[recall >= r].max(initial=0) for r in np.linspace(0, 1, 101)])
    return float(ap)


def evaluate(data, weights, output, split="test", road_weights=None, imgsz=512, focus=None):
    resolved, checked = check_dataset(data)
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Evaluation output must be empty")
    output.mkdir(parents=True, exist_ok=True)
    names = list(resolved["names"].values())
    folder = Path(resolved[split])
    detector = Detector(weights, road_weights, imgsz=imgsz, conf=0.001, road_conf=0.001, focus=focus)
    positives = dict.fromkeys(names, 0)
    matches = {name: [] for name in names}
    threshold_matches = {name: [0, 0] for name in names}
    counts = 0
    with (output / "detections.jsonl").open("w", encoding="utf-8") as stream:
        for image_path in sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXTENSIONS):
            image = decode_image(image_path)
            height, width = image.shape[:2]
            label_path = folder.parent.parent / "labels" / folder.name / image_path.relative_to(folder).with_suffix(".txt")
            truth = {name: [] for name in names}
            for line in label_path.read_text().splitlines():
                if not line.strip():
                    continue
                cls, cx, cy, w, h = map(float, line.split())
                truth[names[int(cls)]].append([(cx-w/2)*width, (cy-h/2)*height, (cx+w/2)*width, (cy+h/2)*height])
            predictions = detector.predict(image)
            # The normal runner uses the timing value too; evaluation takes only the boxes.
            if isinstance(predictions, tuple):
                predictions = predictions[0]
            stream.write(json.dumps({"image": image_path.name, "detections": predictions}) + "\n")
            for name in names:
                boxes = truth[name]
                positives[name] += len(boxes)
                used = set()
                for pred in sorted((d for d in predictions if d["class_name"] == name), key=lambda d: -d["confidence"]):
                    candidates = [(iou(pred["bbox_xyxy"], box), index) for index, box in enumerate(boxes) if index not in used]
                    overlap, index = max(candidates, default=(0, -1))
                    matched = overlap >= 0.5
                    if matched:
                        used.add(index)
                    matches[name].append((pred["confidence"], matched))
                    if pred["confidence"] >= 0.25:
                        threshold_matches[name][0 if matched else 1] += 1
            counts += 1
    provenance_path = Path(data).resolve().parent / "provenance.json"
    provenance = json.loads(provenance_path.read_text(encoding="utf-8")) if provenance_path.exists() else {}
    report = {"iou_threshold": 0.5, "confidence_for_precision_recall": 0.25, "images": counts,
              "data": str(Path(data).resolve()), "split": split, "weights": weights, "road_weights": road_weights, "focus": focus,
              "synthetic_only": provenance.get("synthetic_only"), "classes": {}}
    for name in names:
        tp, fp = threshold_matches[name]
        report["classes"][name] = {"ground_truth": positives[name], "true_positives": tp, "false_positives": fp,
            "precision": tp / (tp+fp) if tp+fp else 0,
            "recall": tp / positives[name] if positives[name] else 0,
            "AP50_101point": average_precision(matches[name], positives[name])}
    aps = [item["AP50_101point"] for item in report["classes"].values() if item["AP50_101point"] is not None]
    report["mAP50_101point"] = sum(aps) / len(aps)
    (output / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--road-weights")
    parser.add_argument("--out", required=True)
    parser.add_argument("--split", choices=("val", "test"), default="test")
    parser.add_argument("--imgsz", type=int, default=512)
    parser.add_argument("--focus", help="Optional normalized x1,y1,x2,y2 far-road region")
    args = parser.parse_args()
    evaluate(args.data, args.weights, args.out, args.split, args.road_weights, args.imgsz,
             tuple(map(float, args.focus.split(","))) if args.focus else None)
