"""Replay separate fixed-CCTV clips and check warnings, without feeding simulation events to inference."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import Detector
from .runner import run_predictions, write_json

CASES = {"Normal": None, "Pothole": "road_damage", "FallingDebris": "road_debris",
         "VehicleCollision": "suspected_vehicle_collision",
         "StructureCollision": "suspected_vehicle_structure_collision"}


def verify(exports, prefix, weights, output, context, imgsz=640, focus=None, stop_model=None, save_images=True):
    exports, output = Path(exports), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory to preserve previous verification")
    model = Detector(weights, imgsz=imgsz, track=True, focus=focus)
    road = json.loads(Path(context).read_text(encoding="utf-8")) if context else None
    report = {"synthetic_only": True, "weights": weights, "imgsz": imgsz,
              "context": context, "focus": focus, "stop_model": stop_model, "cases": {}, "passed": True}
    reference = None
    for case, expected in CASES.items():
        sources = sorted(exports.glob(prefix + case + "_*"))
        if not sources:
            raise ValueError(f"No separate verification clip for {case}")
        source = sources[-1]
        camera = json.loads((source / "camera.json").read_text(encoding="utf-8-sig"))
        pose = {k: camera[k] for k in ("position", "rotation_euler_deg", "vertical_fov_deg", "image_width", "image_height")}
        if reference is not None and pose != reference:
            raise ValueError("All warning clips must use the same fixed CCTV pose and resolution")
        reference = pose
        model.reset_tracking()
        result = run_predictions(model, str(source), output / case, save_images=save_images, warnings=True, context=road, stop_model=stop_model)
        counts = result["alerts_by_type"]
        passed = not counts if expected is None else counts.get(expected, 0) > 0 and set(counts) == {expected}
        report["cases"][case] = {"source": str(source), "expected": expected,
                                  "alerts": counts, "passed": passed, "frames": result["frames"]}
        report["passed"] &= passed
        print(case, counts, "PASS" if passed else "FAIL", flush=True)
    report["camera"] = reference
    write_json(output / "verification.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exports", default="simulation/TwinSightSim/TwinSightExport")
    parser.add_argument("--prefix", default="geumchon-detail-clip-")
    parser.add_argument("--weights", default="detection/models/simulation-cctv.pt")
    parser.add_argument("--context", default="detection/config/geumchon-city-lab.context.json")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--focus", default="0.319444444,0.270833333,0.611111111,0.5625",
                        help="Normalized x1,y1,x2,y2 far-road region")
    parser.add_argument("--out", required=True)
    parser.add_argument("--stop-model")
    args = parser.parse_args()
    result = verify(args.exports, args.prefix, args.weights, args.out, args.context, args.imgsz,
                    tuple(map(float, args.focus.split(","))) if args.focus else None, args.stop_model)
    raise SystemExit(0 if result["passed"] else 1)
