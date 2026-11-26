"""발표 시연용 실제 CCTV 위험물 학습 자료(YOLO 형식)를 만든다.

    python experiments/real-cctv-demo/build_dataset.py --out datasets/real-cctv-demo

- 원본: frontend/public/demo-videos/*.mp4(팀 공유 드라이브 "CCTV영상") + 유튜브 낙하물 영상(captures/downloads/...).
- 고정 카메라라서 정지한 위험물은 기준 프레임 한 장에서 정한 상자를 모든 프레임에 쓴다. 차량이 상자를 가리는 프레임은 뺀다.
  유튜브 낙하물(파란 화물)은 색으로 매 프레임 상자를 찾는다. 가드레일은 정상 기준 프레임과의 차이로 정상/파손을 나눈다.
- 영상마다 앞 70 %는 학습, 뒤 30 %는 검증(시간 분리). 같은 장소·카메라라 처음 보는 CCTV 성능의 증거는 아니다.
- 학습은 원본 해상도에서 위험물을 포함한 640×640 조각으로 한다(작은 위험물이 줄어들지 않게). 위험물이 없는 조각도 섞는다.
- 클래스 순서는 시설물 실험 모델(centerline-no-vehicle-yolo11n)과 같다.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
NAMES = ["pothole", "debris", "delineator_normal", "delineator_broken", "delineator_fallen",
         "manhole_normal", "manhole_abnormal", "guardrail_normal", "guardrail_abnormal"]
CID = {n: i for i, n in enumerate(NAMES)}
VIDEOS = ROOT / "frontend/public/demo-videos"
CROP = 640


def fixed(boxes):
    return lambda frame, t, ctx: boxes


def guardrail_state(frame, t, ctx):
    x0, y0, x1, y1 = 205, 150, 300, 245
    gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(float)
    if "ref" not in ctx:
        ctx["ref"] = gray
    d = float(np.abs(gray - ctx["ref"]).mean())
    if d < 17:
        return [("guardrail_normal", (x0, y0, x1, y1))]
    if 33 <= d <= 38.5:
        return [("guardrail_abnormal", (x0, y0, x1, y1))]
    return None                                                     # 충돌 중(차가 지나감) → 뺀다


def blue_cargo(frame, t, ctx):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (100, 120, 60), (128, 255, 255))
    h, w = mask.shape
    mask[: int(h * 0.12)] = 0                                         # 위쪽 자막 줄
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n <= 1:
        return []
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, bw, bh, area = stats[i]
    if area < 2500 or bw < 60 or bh < 30:
        return []                                                     # 이 시점에는 화물이 안 보인다(라벨 없는 음성 프레임)
    return [("debris", (x, y, x + bw, y + bh))]


SPECS = [
    {"name": "pothole", "video": VIDEOS / "pothole.mp4", "stride": 6, "occlusion": True,
     "label": fixed([("pothole", (805, 648, 895, 672))])},           # 물보라가 이는 물웅덩이(추정)
    {"name": "debris", "video": VIDEOS / "debris.mp4", "stride": 4, "occlusion": True,
     "label": fixed([("debris", (575, 436, 619, 455))])},
    {"name": "debris_youtube", "video": ROOT / "captures/downloads/debris_youtube/debris_youtube.mp4", "stride": 40,
     "occlusion": False, "label": blue_cargo},
    {"name": "delineator", "video": VIDEOS / "delineator.mp4", "stride": 6, "occlusion": True,
     "label": fixed([("delineator_broken", (1050, 858, 1062, 874)), ("delineator_broken", (1080, 889, 1092, 908)),
                     ("delineator_fallen", (1318, 640, 1362, 668))])},
    {"name": "guardrail", "video": VIDEOS / "guardrail.mp4", "stride": 3, "occlusion": False, "label": guardrail_state},
    # 맨홀: 0.6초부터 트럭이 가려 쓸 수 있는 프레임이 적다 → 프레임을 번갈아 학습/검증(시간 분리가 아님, 결과 해석 주의)
    {"name": "manhole", "video": VIDEOS / "manhole.mp4", "stride": 1, "occlusion": True, "max_t": 1.6, "split": "interleave",
     "label": fixed([("manhole_abnormal", (355, 435, 425, 497)), ("manhole_abnormal", (502, 515, 585, 600))])},
]


def overlap_fraction(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy / max(1, (a[2] - a[0]) * (a[3] - a[1]))


def crop_around(frame, boxes, rng):
    h, w = frame.shape[:2]
    if w <= CROP and h <= CROP:
        return frame, (0, 0)
    xs = [b[1][0] for b in boxes] + [b[1][2] for b in boxes]; ys = [b[1][1] for b in boxes] + [b[1][3] for b in boxes]
    lo_x, hi_x = max(0, max(xs) - CROP), min(w - CROP, min(xs)); lo_y, hi_y = max(0, max(ys) - CROP), min(h - CROP, min(ys))
    x0 = rng.randint(int(lo_x), int(max(lo_x, hi_x))) if w > CROP else 0
    y0 = rng.randint(int(lo_y), int(max(lo_y, hi_y))) if h > CROP else 0
    return frame[y0:y0 + CROP, x0:x0 + CROP], (x0, y0)


def negative_crop(frame, boxes, rng):
    h, w = frame.shape[:2]
    if w <= CROP and h <= CROP:
        return None
    for _ in range(20):
        x0 = rng.randint(0, max(0, w - CROP)); y0 = rng.randint(0, max(0, h - CROP))
        win = (x0, y0, x0 + CROP, y0 + CROP)
        if all(overlap_fraction(b[1], win) == 0 for b in boxes):
            return frame[y0:y0 + CROP, x0:x0 + CROP]
    return None


def write(out, split, stem, img, labels):
    (out / "images" / split).mkdir(parents=True, exist_ok=True); (out / "labels" / split).mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "images" / split / f"{stem}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    h, w = img.shape[:2]
    lines = []
    for name, (x1, y1, x2, y2) in labels:
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
        if x2 - x1 < 3 or y2 - y1 < 3:
            continue
        lines.append(f"{CID[name]} {(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}")
    (out / "labels" / split / f"{stem}.txt").write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "datasets/real-cctv-demo")
    ap.add_argument("--train-fraction", type=float, default=0.7)
    args = ap.parse_args()
    from detection.engine import Detector
    vehicles = Detector(str(ROOT / "detection/models/real-traffic.pt"), imgsz=960, conf=0.3, track=False)
    rng = random.Random(0)
    report = {}
    for spec in SPECS:
        cap = cv2.VideoCapture(str(spec["video"])); fps = cap.get(cv2.CAP_PROP_FPS); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = min(n / fps, spec.get("max_t", n / fps)); ctx = {}; stats = {"train": 0, "val": 0, "skipped": 0, "negatives": 0}
        for i in range(0, n, spec["stride"]):
            t = i / fps
            if t > duration:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, i); ok, frame = cap.read()
            if not ok:
                break
            labels = spec["label"](frame, t, ctx)
            if labels is None:
                stats["skipped"] += 1; continue
            if spec["occlusion"] and labels:
                cars, _ = vehicles.predict(frame)
                if any(overlap_fraction(b[1], c["bbox_xyxy"]) > 0.25 for b in labels for c in cars):
                    stats["skipped"] += 1; continue
            if spec.get("split") == "interleave":
                split = "train" if (i // spec["stride"]) % 2 == 0 else "val"
            else:
                split = "train" if t < duration * args.train_fraction else "val"
            stem = f"{spec['name']}_{i:05d}"
            if labels:
                img, (x0, y0) = crop_around(frame, labels, rng)
                write(args.out, split, stem, img, [(nm, (b[0] - x0, b[1] - y0, b[2] - x0, b[3] - y0)) for nm, b in labels])
            else:
                img = frame if frame.shape[1] <= CROP else frame[:CROP, :CROP]
                write(args.out, split, stem, cv2.resize(frame, (CROP, int(CROP * frame.shape[0] / frame.shape[1]))), [])
            stats[split] += 1
            if split == "train" and rng.random() < 0.35:
                neg = negative_crop(frame, labels, rng)
                if neg is not None:
                    write(args.out, split, stem + "_neg", neg, []); stats["negatives"] += 1
        report[spec["name"]] = stats
        print(spec["name"], stats, flush=True)
    yaml = args.out / "dataset.yaml"
    yaml.write_text(f"path: {args.out.as_posix()}\ntrain: images/train\nval: images/val\nnames:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(NAMES)))
    (args.out / "provenance.json").write_text(json.dumps({"purpose": "presentation demo on the same real CCTV videos (time split, not a generalization test)",
                                                          "videos": {s["name"]: str(s["video"].relative_to(ROOT)) for s in SPECS}, "counts": report},
                                                         ensure_ascii=False, indent=1), encoding="utf8")


if __name__ == "__main__":
    main()
