"""Fresh inference with frozen models; never train or select thresholds on test data."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from .engine import Detector
from .evaluate_detection import evaluate
from .runner import annotate, run_predictions, write_json
from .sources import decode_image
from .train_stop_collision import POSITIVE, minimum_control_clearance, verify
from .verify_simulation import CASES, verify as verify_warnings
from .warnings import WarningEngine

FOCUS = (230/720, 130/480, 440/720, 270/480)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def main(output):
    root = Path.cwd().resolve()
    output = Path(output).resolve()
    if not output.is_relative_to(root.parent) or output.exists():
        raise ValueError("Choose a new output directory in the D-drive workspace")
    output.mkdir(parents=True)
    weights = root/"detection/models/simulation-cctv-day-night.pt"
    classifier = root/"detection/models/stop-zone-collision-day-night.xml"
    context = root/"detection/config/geumchon-city-lab.context.json"
    real_context = root/"runs/real-cctv-20261022/real-road-context.json"
    model_files = [weights, classifier, classifier.with_suffix(".json")]
    frozen = {str(p.relative_to(root)): sha(p) for p in model_files}
    if read(classifier.with_suffix(".json"))["detector_weights_sha256"] != sha(weights):
        raise ValueError("Mismatched detector and temporal classifier")
    write_json(output/"protocol.json", {
        "started_at": datetime.now(timezone.utc).isoformat(), "models_sha256": frozen,
        "fresh_inference": True, "cached_predictions_used": False, "training_performed": False,
        "threshold_selection_performed": False, "temporal_splits": ["val", "test"],
        "real_source": "Previously recorded 120-second ITS night clip; not a new live capture",
        "real_ground_truth_available": False, "focus": FOCUS, "imgsz": 640,
        "strict_collision_pass": "Exactly one matching warning at or after actual physics contact",
    })
    inputs = set(model_files+[context, real_context, Path(__file__).resolve()])
    def pin_folder(folder):
        inputs.update(p for p in folder.rglob("*") if p.is_file())

    detection = {}
    for domain, dataset in [("night", "night-v1-full"), ("day", "geumchon-detail-full")]:
        folder = root/"datasets"/dataset
        inputs.add(folder/"dataset.yaml")
        pin_folder(folder/"images/test"); pin_folder(folder/"labels/test")
        detection[domain] = evaluate(folder/"dataset.yaml", str(weights), output/("detection-"+domain),
                                     imgsz=640, focus=FOCUS)
        print("DETECTION_DONE", domain, flush=True)

    temporal_out = output/"temporal"
    entries = [e for e in read(root/"runs/night-v1/temporal-combined/manifest.json")
               if e["split"] in {"val", "test"}]
    counts = Counter(("night" if e["clip"].startswith("night") else "day", e["split"]) for e in entries)
    if counts != Counter({("day", "val"): 10, ("day", "test"): 10,
                          ("night", "val"): 10, ("night", "test"): 10}):
        raise ValueError("Need independent day/night validation and test clips")
    detector = Detector(str(weights), track=True, focus=FOCUS)
    manifest = []
    for original in entries:
        source = Path(original["source"])
        pin_folder(source)
        truth = [json.loads(s) for s in (source/"ground_truth.jsonl").read_text(encoding="utf-8-sig").splitlines()]
        if len(truth) != 40:
            raise ValueError("Incomplete capture")
        impacts = [e for e in truth[-1]["scenario"]["events"] if e["evidence"] == "physics_contact"
                   and e["event_type"] in {"vehicle_collision", "vehicle_structure_collision"}]
        if bool(impacts) != (original["case"] in POSITIVE):
            raise ValueError("Physics contact does not match intended case")
        entry = {k: original[k] for k in ["clip", "split", "case", "source"]}
        entry.update(frames=len(truth), physics_events=impacts,
                     first_impact=min((e["timestamp"] for e in impacts), default=None))
        if not impacts:
            clearance = minimum_control_clearance(truth[-1]["objects"])
            if clearance < .03:
                raise ValueError("Interpenetrating normal control")
            entry["final_clearance_units"] = clearance
        detector.reset_tracking()
        run_predictions(detector, str(source), temporal_out/entry["clip"])
        manifest.append(entry)
        print("FRESH_TEMPORAL", len(manifest), "/", len(entries), entry["clip"], flush=True)
    write_json(temporal_out/"manifest.json", manifest)
    temporal = verify(temporal_out, classifier, context)

    exports = root/"simulation/TwinSightSim/TwinSightExport"
    warnings = {}
    for domain, prefix in [("day", "geumchon-detail-clip-"), ("night", "night-v1-clip-")]:
        for case in CASES:
            pin_folder(sorted(exports.glob(prefix+case+"_*"))[-1])
        warnings[domain] = verify_warnings(exports, prefix, str(weights), output/("warnings-"+domain),
                                          str(context), 640, FOCUS, str(classifier), save_images=False)

    capture = root/"runs/real-cctv-20261022/hls-geumchon-v2"
    inputs.add(capture/"frames.jsonl")
    frames = [json.loads(s) for s in (capture/"frames.jsonl").read_text().splitlines()]
    if len(frames) != 600 or any(b["timestamp"] <= a["timestamp"] for a, b in zip(frames, frames[1:])):
        raise ValueError("Real frame count or source PTS changed")
    real_out = output/"real-night"
    real_out.mkdir(); (real_out/"annotated").mkdir()
    detector.reset_tracking()
    engine = WarningEngine(read(real_context), stop_model=classifier)
    counts = Counter(); alerts = []; times = []
    write_json(real_out/"session.json", {"source": str(capture), "detector": detector.metadata(),
                                        "ground_truth_available": False, "training_use": False})
    with (real_out/"detections.jsonl").open("w", encoding="utf-8") as stream:
        for i, row in enumerate(frames):
            image_path = capture/row["image"]; inputs.add(image_path)
            image = decode_image(image_path); boxes, ms = detector.predict(image)
            record = {**row, "detections": boxes, "inference_ms": ms}
            warning = engine.update(record); alerts.extend(warning); times.append(ms)
            counts.update(d["class_name"] for d in boxes)
            stream.write(json.dumps(record)+"\n")
            if row["frame"] in {0, 150, 300, 450, 599} or warning:
                cv2.imencode(".jpg", annotate(image, boxes, warning))[1].tofile(str(real_out/"annotated"/f"{row['frame']:06d}.jpg"))
            if (i+1) % 100 == 0:
                print("FRESH_REAL", i+1, "/", len(frames), flush=True)
    (real_out/"alerts.jsonl").write_text("".join(json.dumps(a)+"\n" for a in alerts), encoding="utf-8")
    real = {"frames": len(frames), "media_seconds": read(capture/"capture.json")["media_seconds"],
            "detections_by_class": dict(counts), "alerts_by_type": dict(Counter(a["type"] for a in alerts)),
            "warm_mean_inference_ms": float(np.mean(times[1:])), "accuracy_evaluated": False,
            "ground_truth_available": False, "source_pts_preserved": True, "new_live_capture": False}
    write_json(real_out/"summary.json", real)
    frozen_after = {str(p.relative_to(root)): sha(p) for p in model_files}
    if frozen != frozen_after:
        raise ValueError("Models changed during revalidation")
    write_json(output/"input-files.json", [{"path": p.relative_to(root.parent).as_posix(),
               "size_bytes": p.stat().st_size, "sha256": sha(p)} for p in sorted(inputs)])
    summary = {"completed_at": datetime.now(timezone.utc).isoformat(), "models_sha256": frozen,
               "models_unchanged": True, "fresh_inference": True, "training_performed": False,
               "detection": detection, "warning_cases": warnings, "temporal": {}, "real": real}
    for domain in ["day", "night"]:
        for split in ["val", "test"]:
            rows = [e for e in temporal["clips"] if e["split"] == split
                    and e["clip"].startswith("night" if domain == "night" else "queue")]
            positives = [e for e in rows if e["case"] in POSITIVE]
            negatives = [e for e in rows if e["case"] not in POSITIVE]
            summary["temporal"][domain+"-"+split] = {
                "accident_clips": len(positives), "strict_passes": sum(e["passed"] for e in positives),
                "any_warning_clips": sum(bool(e["alerts"]) for e in positives),
                "normal_clips": len(negatives), "normal_alert_count": sum(sum(e["alerts"].values()) for e in negatives),
                "failures": [e for e in rows if not e["passed"]]}
    summary["all_warning_checks_passed"] = temporal["passed"] and all(r["passed"] for r in warnings.values())
    write_json(output/"summary.json", summary)
    print("REVALIDATION_COMPLETE", output, "all_warning_checks_passed", summary["all_warning_checks_passed"], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    main(parser.parse_args().out)
