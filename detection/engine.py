"""YOLO11/v8 adapter with optional separately trained road-hazard detector."""

from __future__ import annotations

import math
import hashlib
import importlib.metadata
import re
import time
from pathlib import Path

from .taxonomy import CATEGORIES, CATEGORY_IDS, ROAD_MODEL_CLASSES, TRAFFIC, model_classes


def resolve_weights(value: str) -> Path:
    path = Path(value)
    if path.is_file():
        return path.resolve()
    if re.fullmatch(r"(?:yolo11|yolov8)[nslmx]\.pt", value):
        # Ultralytics downloads official weights here on the first invocation.
        path = Path(__file__).parent / "models" / value
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.resolve()
    raise FileNotFoundError(f"Model weights not found: {value}")


def convert_result(result, names: dict[int, str], model_id: str, width: int, height: int):
    """Preserve original-pixel boxes and never invent track IDs or unknown labels."""
    detections = []
    boxes = result.boxes
    if boxes is None:
        return detections
    ids = boxes.id.int().tolist() if getattr(boxes, "id", None) is not None else [None] * len(boxes.cls.tolist())
    for xyxy, confidence, cls, track_id in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.tolist(), ids):
        index = int(cls)
        if index not in names or not all(math.isfinite(float(v)) for v in [*xyxy, confidence]):
            continue
        x1, y1, x2, y2 = map(float, xyxy)
        x1, x2 = max(0, min(width, x1)), max(0, min(width, x2))
        y1, y2 = max(0, min(height, y1)), max(0, min(height, y2))
        if x2 <= x1 or y2 <= y1 or not 0 <= confidence <= 1:
            continue
        name = names[index]
        detections.append({
            "class_name": name, "class_id": index,
            "category_id": CATEGORY_IDS[name], "model_id": model_id,
            "bbox_xyxy": [round(v, 3) for v in (x1, y1, x2, y2)],
            "confidence": round(float(confidence), 6), "track_id": track_id,
            "ground_point_px": [round((x1 + x2) / 2, 3), round(y2, 3)],
        })
    return detections


class Detector:
    def __init__(self, weights="yolo11n.pt", road_weights=None, device="cpu", imgsz=640,
                 conf=0.25, road_conf=0.35, iou=0.7, threads=4, track=False, focus=None):
        if imgsz < 32 or imgsz % 32:
            raise ValueError("imgsz must be a positive multiple of 32")
        if not all(0 < value <= 1 for value in (conf, road_conf, iou)):
            raise ValueError("conf, road-conf and iou must be in (0, 1]")
        if threads < 1:
            raise ValueError("threads must be positive")
        if focus is not None:
            if (len(focus) != 4 or not all(math.isfinite(v) and 0 <= v <= 1 for v in focus)
                    or focus[0] >= focus[2] or focus[1] >= focus[3]):
                raise ValueError("focus needs normalized x1,y1,x2,y2 bounds")
            if road_weights:
                raise ValueError("focus currently requires a unified traffic/hazard model")
        import torch
        from ultralytics import YOLO

        torch.set_num_threads(threads)
        self.options = {"device": device, "imgsz": imgsz, "iou": iou, "verbose": False}
        self.models = []
        self.track = track
        self.focus = focus
        requests = [("primary", weights, TRAFFIC if road_weights else CATEGORIES, conf)]
        if focus is not None:
            # Separate existing ByteTrack instances: never feed two views into one tracker.
            requests.append(("focus", weights, CATEGORIES, conf))
        if road_weights:
            requests.append(("road", road_weights, ROAD_MODEL_CLASSES, road_conf))
        for model_id, weight, allowed, threshold in requests:
            path = resolve_weights(weight)
            model = YOLO(str(path))
            if model.task != "detect":
                raise ValueError(f"{weight}: expected an object-detection model, got {model.task}")
            names = model_classes(model.names, allowed)
            if not names:
                raise ValueError(f"{weight}: no recognized classes. Expected names: {', '.join(allowed)}")
            self.models.append((model_id, model, names, threshold, path))

    @property
    def capabilities(self):
        available = {name for _, _, names, _, _ in self.models for name in names.values()}
        return {"available": [name for name in CATEGORIES if name in available],
                "unavailable": [name for name in CATEGORIES if name not in available]}

    def metadata(self):
        return {"options": self.options, "focus": self.focus, "capabilities": self.capabilities, "tracking": "bytetrack" if self.track else None,
                "versions": {name: importlib.metadata.version(name) for name in ("ultralytics", "torch", "opencv-python")},
                "models": [{"id": key, "weights": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "classes": names, "conf": threshold}
                           for key, _, names, threshold, path in self.models]}

    def predict(self, image):
        if image is None or image.ndim != 3 or image.shape[2] != 3:
            raise ValueError("Expected a decoded BGR image with 3 channels")
        height, width = image.shape[:2]
        started = time.perf_counter()
        detections = []
        for model_id, model, names, threshold, _ in self.models:
            x0 = y0 = 0
            sample = image
            if model_id == "focus":
                x0, y0, x1, y1 = [round(v * scale) for v, scale in zip(self.focus, (width, height, width, height))]
                if x1 - x0 < 2 or y1 - y0 < 2:
                    raise ValueError("Focus region is too small for this image")
                sample = image[y0:y1, x0:x1]
            if self.track:
                result = model.track(sample, persist=True, tracker="bytetrack.yaml", classes=list(names), conf=threshold, **self.options)[0]
            else:
                result = model.predict(sample, classes=list(names), conf=threshold, **self.options)[0]
            for detection in convert_result(result, names, model_id, sample.shape[1], sample.shape[0]):
                box = detection["bbox_xyxy"]
                if model_id == "primary" and self.focus is not None:
                    cx, cy = (box[0] + box[2]) / (2 * width), (box[1] + box[3]) / (2 * height)
                    if self.focus[0] <= cx < self.focus[2] and self.focus[1] <= cy < self.focus[3]:
                        continue  # One owner per region prevents duplicate collision pairs.
                if model_id == "focus":
                    detection["bbox_xyxy"] = [box[0] + x0, box[1] + y0, box[2] + x0, box[3] + y0]
                    detection["ground_point_px"] = [detection["ground_point_px"][0] + x0,
                                                     detection["ground_point_px"][1] + y0]
                detections.append(detection)
        return detections, (time.perf_counter() - started) * 1000

    def reset_tracking(self):
        for _, model, _, _, _ in self.models:
            for tracker in getattr(getattr(model, "predictor", None), "trackers", []):
                tracker.reset()
