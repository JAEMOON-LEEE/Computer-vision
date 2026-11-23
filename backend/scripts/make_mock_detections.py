"""오버레이 동작 확인용 검출 목업을 만든다.

박스 위치는 실제 CCTV 영상 속 물체와 맞지 않는다.
timestamp는 이 파일을 만드는 시각의 Unix 초이고, 프레임마다 1/fps씩 늘어난다.
화면 위를 가로지르는 차량·보행자와 제자리 포트홀·낙하물·방호벽이 있는지만 보여 준다.
경고 6건은 그 프레임에 있는 검출의 track_id·bbox만 근거로 쓴다.

저장소 루트에서:
    .\\.venv\\Scripts\\python.exe backend\\scripts\\make_mock_detections.py
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
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
    if name in {"pothole", "debris", "barrier"}:
        class_id = taxonomy.ROAD_MODEL_CLASSES.index(name)
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
    debris_x, debris_y = width * 0.62, height * 0.66
    boxes.append(("debris", 6, clamp_box(debris_x, debris_y, debris_x + 72, debris_y + 48, width, height), 0.58))
    barrier_x, barrier_y = width * 0.18, height * 0.38
    boxes.append(("barrier", 7, clamp_box(barrier_x, barrier_y, barrier_x + 220, barrier_y + 64, width, height), 0.71))
    return [(name, track, box, conf) for name, track, box, conf in boxes if box is not None]


# 기본 300프레임에서 차량이 화면에 있는 시각으로 흩어 둔다.
ALERT_FRAMES = [20, 70, 120, 180, 230, 270]
ALERT_SPECS = [
    ("road_damage", ("pothole",)),
    ("road_debris", ("debris",)),
    ("suspected_vehicle_collision", ("car", "car")),
    ("suspected_vehicle_structure_collision", ("car", "barrier")),
    ("road_debris", ("debris",)),
    ("suspected_vehicle_collision", ("car", "car")),
]


def pick_evidence(items, need):
    chosen = []
    used = set()
    for name in need:
        found = next((item for item in items if item["class_name"] == name and item["track_id"] not in used), None)
        if found is None:
            return None
        used.add(found["track_id"])
        chosen.append(found)
    return chosen


def alert_message(kind, evidence):
    if kind in {"road_damage", "road_debris"}:
        return f"Persistent {evidence[0]['class_name']} detected on the road"
    return "Contact-like overlap followed by abrupt stopping; review video"


def evidence_row(item):
    return {
        "class_name": item["class_name"],
        "track_id": item["track_id"],
        "model_id": item["model_id"],
        "bbox_xyxy": item["bbox_xyxy"],
        "confidence": item["confidence"],
    }


def alert_plan(frame_count):
    if frame_count >= ALERT_FRAMES[-1] + 1:
        return [(frame, kind, need) for frame, (kind, need) in zip(ALERT_FRAMES, ALERT_SPECS)]
    count = min(len(ALERT_SPECS), frame_count)
    span = max(frame_count - 1, 1)
    frames = [min(frame_count - 1, round(index * span / max(count - 1, 1))) for index in range(count)]
    return [(frame, *ALERT_SPECS[index]) for index, frame in enumerate(frames)]


def build_alerts(camera_id, records):
    """프레임 안에 있는 검출의 track_id·bbox만 근거로 쓴다."""
    alerts = []
    for frame, kind, need in alert_plan(len(records)):
        evidence = pick_evidence(records[frame]["detections"], need)
        if evidence is None:
            raise SystemExit(f"프레임 {frame}에 {kind} 근거 검출이 없습니다.")
        alerts.append({
            "alert_id": f"{camera_id}:{len(alerts) + 1}",
            "camera_id": camera_id,
            "frame": frame,
            "timestamp": records[frame]["timestamp"],
            "type": kind,
            "severity": "warning",
            "status": "unconfirmed",
            "message": alert_message(kind, evidence),
            "evidence": [evidence_row(item) for item in evidence],
            "basis": "visual_detections_and_motion",
        })
    return alerts


def build(camera_id, frames, fps, width, height, taxonomy):
    records = []
    # 재생 간격은 그대로 두고, 첫 프레임만 이 파일을 만드는 시각으로 둔다.
    origin = time.time()
    for frame in range(frames):
        items = []
        for name, track_id, box, confidence in object_boxes(frame, frames, width, height):
            items.append(detection(name, track_id, box, confidence, taxonomy))
        records.append({
            "camera_id": camera_id,
            "frame": frame,
            "timestamp": round(origin + frame / fps, 3),
            "timestamp_kind": "unix_seconds",
            "width": width,
            "height": height,
            "detections": items,
            "inference_ms": round(12.0 + (frame % 5) * 0.35, 3),
        })
    alerts = build_alerts(camera_id, records)
    for alert in alerts:
        records[alert["frame"]]["alert_ids"] = [alert["alert_id"]]
    return records, alerts


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
    records, alerts = build(args.camera_id, args.frames, args.fps, args.width, args.height, taxonomy)
    out.mkdir(parents=True, exist_ok=True)
    write_jsonl(out / "detections.jsonl", records)
    write_jsonl(out / "alerts.jsonl", alerts)
    print(f"오버레이 동작 확인용 목업 {args.frames}프레임 -> {out}")
    print("박스 위치는 실제 영상 속 물체와 맞지 않습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
