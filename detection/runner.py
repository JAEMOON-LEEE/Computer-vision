"""Record detector outputs in the team's JSONL contract and optional OpenCV overlays."""

from __future__ import annotations

import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .sources import read_frames
from .warnings import WarningEngine


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def annotate(image, detections, alerts=None):
    canvas = image.copy()
    for detection in detections:
        x1, y1, x2, y2 = map(round, detection["bbox_xyxy"])
        color = (0, 180, 255) if detection["class_name"] in ("pothole", "crack", "debris") else (60, 220, 60)
        cv2.rectangle(canvas, (x1, y1), (x2, y2), color, 2)
        text = f'{detection["class_name"]} {detection["confidence"]:.2f}'
        cv2.putText(canvas, text, (x1, max(y1 - 6, 16)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    for index, alert in enumerate((alerts or [])[:3]):
        cv2.putText(canvas, alert["type"], (12, 26 + 25 * index), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 50, 255), 2)
    return canvas


def run_predictions(detector, source, output, camera_id=None, stride=1, max_frames=None,
                    save_images=False, show=False, warnings=False, context=None, follow=False):
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Output must be empty to preserve previous runs: {output}")
    output.mkdir(parents=True, exist_ok=True)
    if save_images:
        (output / "annotated").mkdir()
    # Do not persist RTSP/HTTP source strings: URLs may contain credentials.
    source_path = Path(source)
    source_description = str(source_path.resolve()) if source_path.exists() else "live-camera-or-stream"
    session = {"started_at": datetime.now(timezone.utc).isoformat(), "source": source_description,
               "detector": detector.metadata(), "category_id_schema": "twinsight-v1",
               "tracking": bool(getattr(detector, "track", False)), "warnings": warnings,
               "warning_basis": "visual_detections_and_motion", "stride": stride, "status": "running"}
    warning_engine = WarningEngine(context) if warnings else None
    alert_writer = (output / "alerts.jsonl").open("w", encoding="utf-8") if warnings else None
    alert_counts = Counter()
    latest_alerts = []
    last_alert_time = -float("inf")
    write_json(output / "session.json", session)
    started = time.perf_counter()
    counts, times, frames = Counter(), [], 0
    status = "completed"
    iterator = read_frames(source, camera_id, stride, max_frames, follow)
    previous_camera, previous_time = None, None
    try:
        with (output / "detections.jsonl").open("w", encoding="utf-8") as writer:
            for frame in iterator:
                if getattr(detector, "track", False) and frame.timestamp_kind == "unspecified":
                    raise ValueError("Tracking/temporal alerts require a video, live camera or Unity export, not unrelated still images")
                if previous_camera is not None and (frame.camera_id != previous_camera or frame.timestamp < previous_time):
                    if hasattr(detector, "reset_tracking"):
                        detector.reset_tracking()
                previous_camera, previous_time = frame.camera_id, frame.timestamp
                detections, milliseconds = detector.predict(frame.image)
                height, width = frame.image.shape[:2]
                record = {"camera_id": frame.camera_id, "frame": frame.number, "timestamp": frame.timestamp,
                          "timestamp_kind": frame.timestamp_kind, "width": width, "height": height,
                          "detections": detections, "inference_ms": round(milliseconds, 3)}
                if frame.image_path:
                    record["image"] = frame.image_path
                if warning_engine is not None:
                    alerts = warning_engine.update(record)
                    record["alert_ids"] = [alert["alert_id"] for alert in alerts]
                    for alert in alerts:
                        alert_writer.write(json.dumps(alert, ensure_ascii=False, allow_nan=False) + "\n")
                        alert_counts[alert["type"]] += 1
                        print(f'WARNING {alert["type"]}: {alert["message"]}')
                    alert_writer.flush()
                    if alerts:
                        latest_alerts, last_alert_time = alerts, frame.timestamp
                writer.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                writer.flush()
                frames += 1
                counts.update(item["class_name"] for item in detections)
                times.append(milliseconds)
                if save_images or show:
                    canvas = annotate(frame.image, detections, latest_alerts if frame.timestamp - last_alert_time <= 3 else [])
                    if save_images:
                        ok, data = cv2.imencode(".jpg", canvas)
                        if not ok:
                            raise RuntimeError("Failed to encode annotated image")
                        data.tofile(output / "annotated" / f"{frame.number:06d}.jpg")
                    if show:
                        cv2.imshow("TwinSight detection — Q to quit", canvas)
                        if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                            status = "stopped"
                            break
        if not frames:
            raise ValueError("No input frames")
    except KeyboardInterrupt:
        status = "interrupted"
    except Exception:
        status = "failed"
        raise
    finally:
        iterator.close()
        if alert_writer is not None:
            alert_writer.close()
        if show:
            cv2.destroyAllWindows()
        elapsed = time.perf_counter() - started
        session["status"] = status
        write_json(output / "session.json", session)
        # Warmup/loading impacts the first inference. These are runtime measurements, not mAP.
        warm = times[1:]
        report = {"status": status, "frames": frames, "detections_by_class": dict(counts),
                  "elapsed_seconds": round(elapsed, 3), "pipeline_fps": round(frames / elapsed, 3) if elapsed else 0,
                  "mean_inference_ms": round(float(np.mean(times)), 3) if times else None,
                  "warm_mean_inference_ms": round(float(np.mean(warm)), 3) if warm else None,
                  "warm_p95_inference_ms": round(float(np.percentile(warm, 95)), 3) if warm else None,
                  "capabilities": detector.capabilities, "alerts_by_type": dict(alert_counts)}
        write_json(output / "summary.json", report)
    return report
