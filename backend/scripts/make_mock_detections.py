"""오버레이 동작 확인용 검출 목업을 만든다.

박스 위치는 실제 CCTV 영상 속 물체와 맞지 않는다.
화면 위를 가로지르는 차량·보행자와 제자리 포트홀이 있는지만 보여 준다.

저장소 루트에서:
    .\\.venv\\Scripts\\python.exe backend\\scripts\\make_mock_detections.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# primary(YOLO COCO) 모델의 원래 class_id. category_id는 taxonomy.py가 정한다.
PRIMARY_CLASS_IDS = {"person": 0, "car": 2}


def load_taxonomy():
    path = ROOT / "detection" / "taxonomy.py"
    spec = importlib.util.spec_from_file_location("twinsight_taxonomy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def clamp_box(x1, y1, x2, y2, width, height):
    left, right = max(0.0, min(width, x1)), max(0.0, min(width, x2))
    top, bottom = max(0.0, min(height, y1)), max(0.0, min(height, y2))
    if right - left < 2 or bottom - top < 2:
        return None
    return [round(left, 3), round(top, 3), round(right, 3), round(bottom, 3)]


def detection(name, track_id, box, confidence, taxonomy):
    if name == "pothole":
        class_id = taxonomy.ROAD_MODEL_CLASSES.index("pothole")
        model_id = "road"
    else:
        class_id = PRIMARY_CLASS_IDS[name]
        model_id = "primary"
    return {
        "class_name": name,
        "class_id": class_id,
        "category_id": taxonomy.CATEGORY_IDS[name],
        "model_id": model_id,
        "bbox_xyxy": box,
        "confidence": round(confidence, 6),
        "track_id": track_id,
        "ground_point_px": [round((box[0] + box[2]) / 2, 3), round(box[3], 3)],
    }


def object_boxes(frame, frames, width, height):
    """프레임마다 조금 움직이는 상자. 화면 밖이면 None."""
    span = max(frames - 1, 1)
    cars = (
        (1, -180.0, 5.4, height * 0.58, 168.0, 92.0),
        (2, -420.0, 4.1, height * 0.70, 210.0, 108.0),
        (3, width + 80.0, -6.2, height * 0.46, 150.0, 78.0),
    )
    boxes = []
    for track_id, start, speed, top, box_w, box_h in cars:
        x = start + speed * frame
        boxes.append(("car", track_id, clamp_box(x, top, x + box_w, top + box_h, width, height), 0.86 - track_id * 0.03))
    person_x = 90.0 + (width * 0.45) * (frame / span)
    person_y = height * 0.62
    boxes.append(("person", 4, clamp_box(person_x, person_y, person_x + 46, person_y + 128, width, height), 0.74))
    hole_x, hole_y = width * 0.48, height * 0.72
    boxes.append(("pothole", 5, clamp_box(hole_x, hole_y, hole_x + 96, hole_y + 52, width, height), 0.62))
    return [(name, track, box, conf) for name, track, box, conf in boxes if box is not None]


def build(camera_id, frames, fps, width, height, taxonomy):
    alert_frame = min(20, frames - 1)
    records = []
    pothole_at_alert = None
    for frame in range(frames):
        items = []
        for name, track_id, box, confidence in object_boxes(frame, frames, width, height):
            item = detection(name, track_id, box, confidence, taxonomy)
            items.append(item)
            if frame == alert_frame and name == "pothole":
                pothole_at_alert = item
        record = {
            "camera_id": camera_id,
            "frame": frame,
            "timestamp": round(frame / fps, 3),
            "timestamp_kind": "video_seconds",
            "width": width,
            "height": height,
            "detections": items,
            "inference_ms": round(12.0 + (frame % 5) * 0.35, 3),
        }
        if frame == alert_frame:
            record["alert_ids"] = [f"{camera_id}:1"]
        records.append(record)
    if pothole_at_alert is None:
        raise SystemExit("포트홀 상자가 경고 프레임에 없습니다.")
    alert = {
        "alert_id": f"{camera_id}:1",
        "camera_id": camera_id,
        "frame": alert_frame,
        "timestamp": records[alert_frame]["timestamp"],
        "type": "road_damage",
        "severity": "warning",
        "status": "unconfirmed",
        "message": "Persistent pothole detected on the road",
        "evidence": [{
            "class_name": "pothole",
            "track_id": pothole_at_alert["track_id"],
            "model_id": pothole_at_alert["model_id"],
            "bbox_xyxy": pothole_at_alert["bbox_xyxy"],
            "confidence": pothole_at_alert["confidence"],
        }],
        "basis": "visual_detections_and_motion",
    }
    return records, alert


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="오버레이 동작 확인용 검출 목업을 만듭니다. 실제 물체 위치와는 맞지 않습니다.")
    parser.add_argument("--camera-id", default="its-cc4277cc18")
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--fps", type=float, default=10)
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--out", default=None, help="출력 폴더. 기본값은 backend/data/mock/<camera-id>")
    args = parser.parse_args()
    if args.frames < 1 or args.fps <= 0 or args.width < 2 or args.height < 2:
        parser.error("--frames, --width, --height는 양수이고 --fps는 0보다 커야 합니다")
    out = Path(args.out) if args.out else ROOT / "backend" / "data" / "mock" / args.camera_id
    if not out.is_absolute():
        out = Path.cwd() / out
    taxonomy = load_taxonomy()
    records, alert = build(args.camera_id, args.frames, args.fps, args.width, args.height, taxonomy)
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "detections.jsonl", records)
    write_jsonl(out / "alerts.jsonl", [alert])
    print(f"오버레이 동작 확인용 목업 {args.frames}프레임 -> {out}")
    print("박스 위치는 실제 영상 속 물체와 맞지 않습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
