"""발표 시연(/demo): 브라우저 안 Unity City Lab 화면을 받아 도로 위험·시설물 모델로 검출하고 경고한다.

두 팀 모델을 함께 쓴다. 포트홀·낙하물은 주간·야간 시나리오 경고를 통과한 simulation-cctv-day-night,
시선유도봉·가드레일·맨홀은 같은 가상 CCTV 시점의 차량 없는 주간 합성 장면으로 학습한 실험 가중치
centerline-no-vehicle-yolo11n(PR #4)이다. 시연은 "버튼 → 장면 생성 → 모델 검출 → 경고"가 끝까지 이어지는지 보여 주며,
실제 CCTV 정확도를 뜻하지 않는다. Unity의 시나리오 정답은 받지도 쓰지도 않는다.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

from detection.warnings import WarningEngine, iou

ROOT = Path(__file__).resolve().parents[2]
MODELS = {
    # 이름: (가중치, SHA-256, 학습 입력 크기, 이 모델에서 쓰는 클래스)
    "road": ("simulation-cctv-day-night.pt", "7dd2720a7bd8c8757c3a0f38b901b7e6dea46d68e97257916a6810b6947bf1a2", 640,
             {"pothole", "crack", "debris"}),
    "facility": ("centerline-no-vehicle-yolo11n.pt", "d5fb75fc142eb5f8e5da3b675d010b70784255630be743dcbd1533f91a9664d4", 512,
                 {"delineator_normal", "delineator_broken", "delineator_fallen", "manhole_normal", "manhole_abnormal",
                  "guardrail_normal", "guardrail_abnormal"}),
}
# 실제 CCTV 영상용: 시연 영상 4종(+유튜브 낙하물)의 일부 구간으로 추가 학습한 모델(experiments/real-cctv-demo).
# 같은 영상·카메라로 학습했으므로 처음 보는 CCTV 성능을 뜻하지 않는다. 고해상도 영상은 640 조각으로 나눠 원본 크기로 검출한다.
REAL_MODELS = {
    "real": ("real-cctv-demo-yolo11n.pt", None, 640,
             {"pothole", "debris", "delineator_broken", "delineator_fallen", "manhole_abnormal", "guardrail_normal", "guardrail_abnormal"}),
}
TILE = 640
DETECT_CONF = 0.25     # 화면에 그리는 박스
ALERT_CONF = 0.4       # 경고 근거로 쓰는 최소 신뢰도
PERSISTENCE = 0.6      # 같은 자리에 이만큼(초) 이어져야 경고
MIN_FRAMES = 3
MAX_GAP = 1.5          # 프레임 간격이 이보다 벌어지면 다시 센다(탭이 뒤로 가면 브라우저가 초당 1장으로 늦춘다)
COOLDOWN = 30.0       # 같은 자리 위험물을 다시 경고하기까지(초). 시연 장면은 치우기 전까지 남아 있다

# 위험 클래스 → 경고 종류. 실제 영상 조각 검출은 초당 1장 남짓이라 팀 WarningEngine(프레임 간격 0.5초 이내 요구) 대신
# 같은 지속 규칙을 모든 위험에 쓴다. 경고 종류 이름(road_damage, road_debris)은 팀 엔진과 같다.
FACILITY_ALERTS = {
    "pothole": ("road_damage", "포트홀 의심"),
    "debris": ("road_debris", "낙하물 의심"),
    "delineator_broken": ("facility_damage", "시선유도봉 파손 의심"),
    "delineator_fallen": ("facility_damage", "시선유도봉 쓰러짐 의심"),
    "guardrail_abnormal": ("facility_damage", "가드레일 이상 의심"),
    "manhole_abnormal": ("manhole_abnormal", "맨홀 이상 의심"),
}


class FacilityGate:
    """시설물 이상 검출이 같은 자리에 MIN_FRAMES번·PERSISTENCE초 이상 이어질 때만 경고한다."""

    def __init__(self, max_gap=MAX_GAP):
        self.max_gap = max_gap
        self.tracks: dict[tuple, tuple[float, float, int]] = {}
        self.recent: list[tuple[str, list[float], float]] = []
        self.index = 0

    def reset(self):
        self.tracks.clear(); self.recent.clear()

    def update(self, record):
        now, width, height = float(record["timestamp"]), record["width"], record["height"]
        alerts = []
        for d in record["detections"]:
            name = d["class_name"]
            if name not in FACILITY_ALERTS or d["confidence"] < ALERT_CONF:
                continue
            box = d["bbox_xyxy"]
            key = (name, round((box[0] + box[2]) / width * 8), round(box[3] / height * 8))
            first, last, count = self.tracks.get(key, (now, now, 0))
            if now - last > self.max_gap:
                first, count = now, 0
            self.tracks[key] = (first, now, count + 1)
            if count + 1 < MIN_FRAMES or now - first < PERSISTENCE:
                continue
            kind, message = FACILITY_ALERTS[name]
            if any(k == kind and now - t < COOLDOWN and iou(box, b) >= 0.2 for k, b, t in self.recent):
                continue
            self.recent.append((kind, list(box), now))
            self.index += 1
            alerts.append({"alert_id": f'{record["camera_id"]}:facility:{self.index}', "camera_id": record["camera_id"],
                           "frame": record["frame"], "timestamp": now, "type": kind, "severity": "warning",
                           "status": "unconfirmed", "message": message,
                           "evidence": [{"class_name": name, "bbox_xyxy": box, "confidence": d["confidence"]}],
                           "basis": "persistent_visual_detection"})
        self.tracks = {k: v for k, v in self.tracks.items() if now - v[1] <= self.max_gap}
        self.recent = [item for item in self.recent if now - item[2] < COOLDOWN]
        return alerts


def tiled_predict(detector, image, tile=TILE, overlap=0.25):
    """원본 해상도를 유지하려고 tile×tile 조각으로 나눠 검출하고, 겹친 상자는 클래스별 NMS로 합친다."""
    import cv2
    h, w = image.shape[:2]
    if max(h, w) <= tile * 1.25:
        return detector.predict(image)
    step = int(tile * (1 - overlap))
    xs = list(range(0, max(1, w - tile) + 1, step)); ys = list(range(0, max(1, h - tile) + 1, step))
    if xs[-1] + tile < w: xs.append(w - tile)
    if ys[-1] + tile < h: ys.append(h - tile)
    found, elapsed = [], 0.0
    for y0 in ys:
        for x0 in xs:
            boxes, ms = detector.predict(image[y0:y0 + tile, x0:x0 + tile]); elapsed += ms
            for b in boxes:
                x1, y1, x2, y2 = b["bbox_xyxy"]; found.append({**b, "bbox_xyxy": [x1 + x0, y1 + y0, x2 + x0, y2 + y0]})
    merged = []
    for name in {b["class_name"] for b in found}:
        group = [b for b in found if b["class_name"] == name]
        rects = [[b["bbox_xyxy"][0], b["bbox_xyxy"][1], b["bbox_xyxy"][2] - b["bbox_xyxy"][0], b["bbox_xyxy"][3] - b["bbox_xyxy"][1]] for b in group]
        keep = cv2.dnn.NMSBoxes(rects, [b["confidence"] for b in group], 0.0, 0.5)
        merged += [group[int(i)] for i in (keep.flatten() if len(keep) else [])]
    return merged, elapsed


class DemoDetectionService:
    def __init__(self, models_dir: Path = ROOT / "detection/models", factory=None, models=None, tiled=False, camera_id="demo-city-lab"):
        self.models_dir = models_dir
        self.factory = factory
        self.models = models or MODELS
        self.tiled = tiled
        self.camera_id = camera_id
        self.max_gap = 2.5 if tiled else MAX_GAP     # 조각 검출은 느려서 프레임 간격을 더 허용한다
        self.lock = threading.Lock()
        self.detectors = None
        self.frame = 0
        self.last_time: float | None = None
        self.engine = WarningEngine(confidence=ALERT_CONF, persistence=PERSISTENCE, cooldown=COOLDOWN)
        self.gate = FacilityGate(self.max_gap)

    def status(self):
        files = {key: (self.models_dir / name).exists() and (self.models_dir / name).stat().st_size > 1_000_000
                 for key, (name, *_rest) in self.models.items()}
        return {"models": {key: self.models[key][0] for key in self.models}, "weights_present": files, "tiled": self.tiled, "loaded": self.detectors is not None,
                "detect_confidence": DETECT_CONF, "alert_confidence": ALERT_CONF,
                "persistence_seconds": PERSISTENCE, "min_frames": MIN_FRAMES}

    def _load(self):
        if self.detectors is not None:
            return self.detectors
        if self.factory is not None:
            self.detectors = [(self.factory(), None)]
            return self.detectors
        from detection.engine import Detector
        detectors = []
        for key, (name, sha, imgsz, classes) in self.models.items():
            path = self.models_dir / name
            if not path.exists() or path.stat().st_size < 1_000_000:
                raise FileNotFoundError(f'모델이 없습니다. git lfs pull --include="detection/models/{name}"')
            if sha is not None and hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                raise ValueError(f"{name} 가중치가 팀 공유본(SHA-256)과 다릅니다")
            detectors.append((Detector(str(path), imgsz=imgsz, conf=DETECT_CONF, track=False), classes))
        self.detectors = detectors
        return detectors

    def reset(self):
        with self.lock:
            self._reset()

    def _reset(self):
        self.engine = WarningEngine(confidence=ALERT_CONF, persistence=PERSISTENCE, cooldown=COOLDOWN)
        self.gate.reset()
        self.last_time = None

    def infer(self, image, timestamp: float):
        with self.lock:
            detectors = self._load()
            if self.last_time is not None and (timestamp <= self.last_time or timestamp - self.last_time > self.max_gap + 1):
                self._reset()   # 장면 전환·탭 비활성으로 끊기면 지속 조건을 처음부터 센다
            height, width = image.shape[:2]
            boxes, elapsed = [], 0.0
            for detector, classes in detectors:
                found, ms = tiled_predict(detector, image) if self.tiled else detector.predict(image)
                boxes += [b for b in found if classes is None or b["class_name"] in classes]
                elapsed += ms
            self.frame += 1
            record = {"camera_id": self.camera_id, "frame": self.frame, "timestamp": timestamp,
                      "timestamp_kind": "capture_seconds", "width": width, "height": height, "detections": boxes}
            alerts = self.gate.update(record)
            self.last_time = timestamp
            return {"frame": self.frame, "timestamp": timestamp, "width": width, "height": height,
                    "inference_ms": round(elapsed, 1),
                    "detections": [{"class_name": b["class_name"], "confidence": round(b["confidence"], 3),
                                    "bbox_xyxy": [round(v, 1) for v in b["bbox_xyxy"]]} for b in boxes],
                    "alerts": alerts}


service = DemoDetectionService()
real_service = DemoDetectionService(models=REAL_MODELS, tiled=True, camera_id="demo-real-cctv")
# 영상 재현(Unity) 화면: 같은 모델·같은 조건으로 따로 경고 상태를 둔다
twin_service = DemoDetectionService(models=REAL_MODELS, tiled=True, camera_id="demo-twin-replay")
