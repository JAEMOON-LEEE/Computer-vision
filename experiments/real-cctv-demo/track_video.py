"""실제 CCTV 영상의 차량을 추적해 cctv_scene_replay.py 입력(JSONL)을 만든다.

    python experiments/real-cctv-demo/track_video.py --video <mp4> --out captures/<name>_tracks.jsonl [--start 0 --end 130] [--mask x0,y0,x1,y1]
"""
import argparse
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from detection.engine import Detector  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--video", required=True); ap.add_argument("--out", required=True)
ap.add_argument("--start", type=float, default=0.0); ap.add_argument("--end", type=float, default=None)
ap.add_argument("--stride", type=int, default=2, help="몇 프레임마다 추적할지(30 fps 영상에서 2 = 15 fps)")
ap.add_argument("--imgsz", type=int, default=960)
ap.add_argument("--mask", action="append", default=[], help="화면 자막 영역 x0,y0,x1,y1(박스 중심이 안에 있으면 뺀다)")
args = ap.parse_args()
masks = [tuple(int(v) for v in m.split(",")) for m in args.mask]
det = Detector(str(ROOT / "detection/models/real-traffic.pt"), imgsz=args.imgsz, conf=0.3, track=True)
cap = cv2.VideoCapture(args.video); fps = cap.get(cv2.CAP_PROP_FPS)
cap.set(cv2.CAP_PROP_POS_FRAMES, int(args.start * fps)); i = int(args.start * fps)
with open(args.out, "w", encoding="utf8") as out:
    while True:
        ok, img = cap.read()
        if not ok or (args.end and i / fps > args.end):
            break
        if i % args.stride == 0:
            boxes, _ = det.predict(img)
            rows = []
            for b in boxes:
                if b.get("track_id") is None:
                    continue
                x1, y1, x2, y2 = b["bbox_xyxy"]; cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                if any(a <= cx <= c and bb <= cy <= d for a, bb, c, d in masks):
                    continue
                rows.append({"track_id": b["track_id"], "class_name": b["class_name"], "confidence": round(b["confidence"], 3),
                             "bbox_xyxy": [round(v, 1) for v in b["bbox_xyxy"]]})
            out.write(json.dumps({"frame": i, "t": round(i / fps, 3), "detections": rows}) + "\n")
        i += 1
print("done", args.out)
