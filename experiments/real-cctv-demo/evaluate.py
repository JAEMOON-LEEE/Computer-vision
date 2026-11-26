"""시연 영상별 남겨 둔 구간(뒤 30 %)에서 시연과 같은 조건(조각 검출·경고 규칙)으로 검출·경고를 확인한다."""
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app.demo_service import REAL_MODELS, DemoDetectionService  # noqa: E402

V = ROOT / "frontend/public/demo-videos"
CASES = [  # 이름, 영상, 평가 구간(초), 찾아야 할 클래스
    ("pothole", V / "pothole.mp4", (21.4, 30.5), {"pothole"}),
    ("debris (서해안선)", V / "debris.mp4", (14.2, 20.3), {"debris"}),
    ("debris (남해선 유튜브)", V / "debris_youtube.mp4", (91.0, 130.0), {"debris"}),
    ("guardrail", V / "guardrail.mp4", (15.2, 21.7), {"guardrail_abnormal"}),
    ("delineator", V / "delineator.mp4", (21.2, 30.2), {"delineator_broken", "delineator_fallen"}),
    ("manhole", V / "manhole.mp4", (0.0, 0.7), {"manhole_abnormal"}),
]
out = {}
for name, video, (t0, t1), wanted in CASES:
    svc = DemoDetectionService(models=REAL_MODELS, tiled=True, camera_id=name)
    cap = cv2.VideoCapture(str(video)); fps = cap.get(cv2.CAP_PROP_FPS)
    step = max(1, round(fps / (10 if name == "manhole" else 4)))
    hits = frames = 0; alerts = []; best = 0.0
    i = int(t0 * fps)
    while i / fps <= t1:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i); ok, img = cap.read()
        if not ok: break
        r = svc.infer(img, i / fps); frames += 1
        found = [d for d in r["detections"] if d["class_name"] in wanted]
        hits += bool(found); best = max([best] + [d["confidence"] for d in found])
        alerts += [(round(a["timestamp"], 1), a["type"]) for a in r["alerts"]]
        i += step
    out[name] = {"window_s": [t0, t1], "frames": frames, "frames_with_target": hits, "max_conf": round(best, 2), "alerts": alerts}
    print(name, out[name], flush=True)
(ROOT / "docs/validation/real-cctv-demo-heldout-20261127.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf8")
