"""Run from the repository root: python -m detection --help."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def parser():
    root = argparse.ArgumentParser(description="TwinSight YOLO11/v8 object detector")
    commands = root.add_subparsers(dest="command", required=True)
    predict = commands.add_parser("predict", help="Unity export, image/folder, video, webcam or RTSP")
    predict.add_argument("--source", required=True)
    predict.add_argument("--weights", default="yolo11n.pt")
    predict.add_argument("--road-weights", help="Optional trained pothole/crack/debris detector")
    predict.add_argument("--conf", type=float, default=0.25)
    predict.add_argument("--road-conf", type=float, default=0.35)
    predict.add_argument("--iou", type=float, default=0.7)
    predict.add_argument("--imgsz", type=int, default=640)
    predict.add_argument("--device", default="cpu")
    predict.add_argument("--threads", type=int, default=4)
    predict.add_argument("--camera-id")
    predict.add_argument("--stride", type=int, default=1)
    predict.add_argument("--max-frames", type=int)
    predict.add_argument("--out", type=Path, default=None)
    predict.add_argument("--save-images", action="store_true")
    predict.add_argument("--show", action="store_true")
    predict.add_argument("--track", action="store_true", help="Use existing ByteTrack backend for temporal rules")
    predict.add_argument("--alerts", action="store_true", help="Enable observation-based warnings; also enables tracking")
    predict.add_argument("--follow", action="store_true", help="Read newly appended Unity frames until 10 seconds idle")
    predict.add_argument("--context", type=Path, help="Road/stop polygons from the road-recognition module")
    warn = commands.add_parser("warn", help="Generate warnings from teammate's tracked detections.jsonl")
    warn.add_argument("--detections", required=True, type=Path)
    warn.add_argument("--out", required=True, type=Path)
    warn.add_argument("--context", type=Path)
    prepare = commands.add_parser("prepare-unity", help="Convert independent Unity capture sessions to YOLO data")
    prepare.add_argument("--train", required=True, nargs="+", type=Path)
    prepare.add_argument("--val", required=True, nargs="+", type=Path)
    prepare.add_argument("--test", nargs="+", type=Path, default=[])
    prepare.add_argument("--classes", default="pothole,debris,barrier")
    prepare.add_argument("--out", required=True, type=Path)
    check = commands.add_parser("check-data", help="Check labels and train/val/test image leakage")
    check.add_argument("--data", required=True, type=Path)
    train = commands.add_parser("train", help="Fine-tune on a locally annotated YOLO detection dataset")
    train.add_argument("--data", required=True, type=Path)
    train.add_argument("--weights", default="yolo11n.pt")
    train.add_argument("--epochs", type=int, default=100)
    train.add_argument("--imgsz", type=int, default=640)
    train.add_argument("--batch", type=int, default=8)
    train.add_argument("--device", default="cpu")
    train.add_argument("--name", default="twinsight")
    train.add_argument("--mosaic", type=float, default=1.0)
    train.add_argument("--freeze", type=int, default=0)
    validate = commands.add_parser("validate", help="Evaluate a trained detector on labeled val/test images")
    validate.add_argument("--data", required=True, type=Path)
    validate.add_argument("--weights", required=True)
    validate.add_argument("--split", choices=("val", "test"), default="test")
    validate.add_argument("--device", default="cpu")
    validate.add_argument("--imgsz", type=int, default=640)
    return root


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        if args.command == "prepare-unity":
            from .prepare_unity import prepare_unity
            report = prepare_unity({"train": args.train, "val": args.val, "test": args.test}, args.out, args.classes.split(","))
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.command == "warn":
            from .warnings import replay_warnings
            context = json.loads(args.context.read_text(encoding="utf-8")) if args.context else None
            print(f"Alerts: {replay_warnings(args.detections, args.out, context)}")
            return 0
        if args.command == "predict":
            from .engine import Detector
            from .runner import run_predictions

            detector = Detector(args.weights, args.road_weights, args.device, args.imgsz,
                                args.conf, args.road_conf, args.iou, args.threads, args.track or args.alerts)
            context = json.loads(args.context.read_text(encoding="utf-8")) if args.context else None
            print("Capabilities: " + json.dumps(detector.capabilities, ensure_ascii=False))
            output = args.out or Path("runs/detection") / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            report = run_predictions(detector, args.source, output, args.camera_id, args.stride,
                                     args.max_frames, args.save_images, args.show, args.alerts, context, args.follow)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print(f"Output: {output.resolve()}")
            return 0
        from .dataset import check_dataset
        resolved, report = check_dataset(args.data)
        if args.command == "check-data":
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        from .engine import resolve_weights
        from .runner import write_json
        from ultralytics import YOLO
        import yaml
        import torch
        torch.set_num_threads(4)

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        folder = Path("runs/detection") / f"{args.command}_{stamp}"
        folder.mkdir(parents=True)
        data = folder / "dataset.resolved.yaml"
        data.write_text(yaml.safe_dump(resolved, allow_unicode=True), encoding="utf-8")
        write_json(folder / "dataset-check.json", report)
        model = YOLO(str(resolve_weights(args.weights)))
        if model.task != "detect":
            raise ValueError("Expected detection model")
        if args.command == "train":
            if args.epochs < 1 or args.batch < 1:
                raise ValueError("epochs and batch must be positive")
            model.train(data=str(data.resolve()), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                        device=args.device, workers=0, seed=42, deterministic=True, patience=20,
                        mosaic=args.mosaic, freeze=args.freeze,
                        project=str(folder.resolve()), name=args.name, plots=True)
            print(f"Training artifacts: {folder.resolve() / args.name}")
        else:
            if args.split not in resolved:
                raise ValueError(f"Dataset has no {args.split} split")
            expected = list(resolved["names"].values())
            actual = list(model.names.values()) if isinstance(model.names, dict) else model.names
            if expected != actual:
                raise ValueError("Model and dataset class names/order differ; use the matching trained best.pt")
            metrics = model.val(data=str(data.resolve()), split=args.split, device=args.device,
                                imgsz=args.imgsz, workers=0, project=str(folder.resolve()), name="metrics")
            report = {key: float(value) for key, value in metrics.results_dict.items()}
            report["per_class"] = {expected[int(cls)]: {"precision": float(metrics.box.p[i]),
                "recall": float(metrics.box.r[i]), "mAP50": float(metrics.box.ap50[i]),
                "mAP50_95": float(metrics.box.ap[i])} for i, cls in enumerate(metrics.box.ap_class_index)}
            write_json(folder / "metrics.json", report)
            print(f"Validation artifacts: {folder.resolve()}")
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
