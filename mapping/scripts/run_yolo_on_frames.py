"""가상환경 프레임에 YOLO를 돌려 detections.jsonl(공통 형식)로 저장한다.

    python mapping/scripts/run_yolo_on_frames.py <내보내기 폴더> --weights yolo11n.pt --classes car,truck,bus
    python mapping/scripts/run_yolo_on_frames.py <내보내기 폴더> --track    # ByteTrack으로 track_id도 채움

실제 CCTV용 YOLO 코드도 같은 형식(docs/data_format.md)으로 저장하면 evaluate_mapping.py로 똑같이 평가할 수 있다.
가중치 파일이 없으면 ultralytics가 처음 실행할 때 내려받는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping.dataset import read_jsonl  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export_dir", type=Path)
    parser.add_argument("--weights", default="yolo11n.pt")
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=640, help="YOLO 입력 크기. 크게 하면 먼 차량을 더 잘 찾지만 느리다")
    parser.add_argument("--classes", help="남길 클래스 이름, 쉼표로 구분 (예: car,truck,bus)")
    parser.add_argument("--device", default=None, help="cpu, 0 등. 비우면 ultralytics가 고른다")
    parser.add_argument("--track", action="store_true", help="ByteTrack으로 객체 ID를 붙인다")
    parser.add_argument("--out", type=Path, help="기본: <내보내기 폴더>/detections.jsonl")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    from ultralytics import YOLO

    frames = [f for f in read_jsonl(args.export_dir / "ground_truth.jsonl") if f.get("image")]
    if not frames:
        sys.exit("이미지가 있는 프레임이 없습니다. Unity GroundTruthExporter의 saveImages를 켜고 다시 저장하세요.")

    model = YOLO(args.weights)
    keep = set(args.classes.split(",")) if args.classes else None
    out_path = args.out or args.export_dir / "detections.jsonl"
    options = {"conf": args.conf, "imgsz": args.imgsz, "verbose": False}
    if args.device is not None:
        options["device"] = args.device

    with open(out_path, "w", encoding="utf-8") as out:
        for i, frame in enumerate(frames):
            image = str(args.export_dir / frame["image"])
            if args.track:
                result = model.track(image, persist=True, tracker="bytetrack.yaml", **options)[0]
            else:
                result = model.predict(image, **options)[0]

            boxes = result.boxes
            ids = boxes.id.int().tolist() if boxes.id is not None else [None] * len(boxes)
            detections = []
            for xyxy, conf, cls, track_id in zip(boxes.xyxy.tolist(), boxes.conf.tolist(), boxes.cls.int().tolist(), ids):
                name = result.names[cls]
                if keep is not None and name not in keep:
                    continue
                detections.append({
                    "class_name": name,
                    "class_id": cls,
                    "bbox_xyxy": [round(v, 2) for v in xyxy],
                    "confidence": round(conf, 4),
                    "track_id": track_id,
                })

            record = {key: frame[key] for key in ("camera_id", "frame", "timestamp", "width", "height")}
            record["detections"] = detections
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            if (i + 1) % 50 == 0:
                print(f"{i + 1}/{len(frames)} 프레임")

    print(f"저장: {out_path}")


if __name__ == "__main__":
    main()
