"""Local manual validation sessions; reuse the team's detector and warning contract."""
from __future__ import annotations

import base64
from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import threading
import time
import uuid

from fastapi import HTTPException

from detection.warnings import WarningEngine

ROOT = Path(__file__).resolve().parents[2]
MODELS = {"day-night": "simulation-cctv-day-night.pt", "day": "simulation-cctv-queue.pt",
          "collision-v2":"simulation-cctv-collision-v2.pt", "real-traffic":"real-traffic.pt", "real-coco":"yolo11s.pt"}


def now():
    return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def append(path, value):
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False)+"\n")


def decode_frame(value):
    from PIL import Image
    import cv2
    import numpy as np
    if value.startswith("data:image/"):
        value = value.split(",", 1)[-1]
    try:
        raw = base64.b64decode(value, validate=True)
        if len(raw) > 3*1024*1024:
            raise ValueError("too large")
        with Image.open(BytesIO(raw)) as header:
            width, height = header.size
            if header.format not in {"JPEG", "PNG"} or not (1 <= width <= 2560 and 1 <= height <= 1440):
                raise ValueError("unsupported dimensions or format")
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape[:2] != (height, width):
            raise ValueError("invalid image")
        return image
    except Exception as exc:
        raise HTTPException(422, "JPEG/PNG 프레임을 최대 2560×1440, 3MB로 보내 주세요.") from exc


def detector_factory(model, confidence, tracking):
    from detection.engine import Detector
    if model=="real-coco":
        import hashlib
        if hashlib.sha256((ROOT/"detection/models/yolo11s.pt").read_bytes()).hexdigest()!="85a76fe86dd8afe384648546b56a7a78580c7cb7b404fc595f97969322d502d5":
            raise ValueError("Official real traffic baseline weights differ")
    if model=="real-traffic":
        import hashlib
        metadata=json.loads((ROOT/"detection/models/real-traffic.json").read_text(encoding="utf8"))
        if hashlib.sha256((ROOT/"detection/models/real-traffic.pt").read_bytes()).hexdigest()!=metadata["selected_sha256"]:
            raise ValueError("Real traffic detector weights differ from verified selection")
    return Detector(str(ROOT/"detection/models"/MODELS[model]), track=tracking, conf=confidence, focus=None)


class LabService:
    def __init__(self, storage=None, factory=detector_factory):
        self.storage = Path(storage) if storage else ROOT/"runs/validation-lab"
        self.factory = factory
        self.sessions = {}
        self.lock = threading.RLock()

    def collision_v2_ready(self):
        return ((ROOT/"detection/models"/MODELS["collision-v2"]).is_file()
                and (ROOT/"detection/models/collision-policy-v2.xml").is_file()
                and (ROOT/"runs/collision-v2/policy-verification.json").is_file())

    def real_traffic_ready(self):
        try:
            metadata=json.loads((ROOT/"detection/models/real-traffic.json").read_text(encoding="utf8"))
            return metadata.get("status")=="complete" and (ROOT/"detection/models/real-traffic.pt").is_file()
        except (OSError,ValueError):return False

    def real_coco_ready(self):
        return (ROOT/"detection/models/yolo11s.pt").is_file()

    def real_incident_ready(self):
        try:
            metadata=json.loads((ROOT/"detection/models/real-incident-scene-v1.json").read_text(encoding="utf8"))
            return (metadata.get("alerts_enabled") is True
                    and (ROOT/"detection/models/real-incident-scene-v1.xml").is_file()
                    and (ROOT/"runs/real-traffic-v1/incidents/completion.json").is_file())
        except (OSError,ValueError):return False

    def load_collision_policy(self, detector):
        if not self.collision_v2_ready():
            raise HTTPException(503,"충돌 보강 모델의 학습·검사가 아직 완료되지 않았습니다.")
        from detection.collision_policy import CollisionPolicy
        policy=CollisionPolicy(ROOT/"detection/models/collision-policy-v2.xml")
        if policy.metadata["detector_weights_sha256"]!=detector.metadata()["models"][0]["sha256"]:
            raise HTTPException(409,"충돌 판정 모델과 차량 검출 가중치가 일치하지 않습니다.")
        return policy

    def create(self, options):
        with self.lock:
            if options.model=="real-traffic" and not self.real_traffic_ready():
                raise HTTPException(503,"실제 영상용 차량 모델의 학습·비교 검사가 아직 완료되지 않았습니다.")
            if options.model=="real-coco" and not self.real_coco_ready():
                raise HTTPException(503,"범용 차량 모델 파일을 먼저 준비해 주세요.")
            if options.real_incident_scene and not self.real_incident_ready():
                raise HTTPException(503,"실제 사고 장면 분류기는 검증 기준을 아직 통과하지 못했습니다. 차량 검출은 사용할 수 있습니다.")
            for session in list(self.sessions.values()):
                if session["enabled"] and (time.monotonic()-session["touched"] > 1800 or
                        (options.client_id and session["options"].get("client_id") == options.client_id)):
                    self._stop(session)
            if sum(s["enabled"] for s in self.sessions.values()) >= 2:
                raise HTTPException(409, "모델 실행은 최대 두 세션입니다. 기존 세션을 먼저 꺼 주세요.")
            try:
                detector = self.factory(options.model, options.confidence, options.source_kind != "image")
            except Exception as exc:
                raise HTTPException(503, "모델을 읽지 못했습니다. Git LFS 가중치와 Python 설치를 확인해 주세요.") from exc
            policy=self.load_collision_policy(detector) if options.simulation_collision_policy else None
            real_scene=None
            if options.real_incident_scene:
                from detection.real_incident import RealIncidentScorer
                try:real_scene=RealIncidentScorer()
                except Exception as exc:raise HTTPException(503,"실제 사고 장면 분류기를 읽지 못했습니다.") from exc
            session_id = uuid.uuid4().hex
            folder = self.storage/session_id
            folder.mkdir(parents=True, exist_ok=False)
            session = {"id": session_id, "folder": folder, "enabled": True, "detector": detector,
                       "engine": WarningEngine(collision_model=policy), "collision_policy":policy,
                       "real_scene":real_scene,
                       "options": options.model_dump(), "started_at": now(),
                       "touched": time.monotonic(), "frames": 0, "last_time": None, "shape": None,
                       "segment": 0, "counts": Counter(), "alerts": Counter(), "last_result": None,
                       "model_metadata": detector.metadata()}
            self.sessions[session_id] = session
            write(folder/"session.json", self.describe(session))
            append(folder/"events.jsonl", {"event": "model_on", "at": now()})
            # Closed sessions contain no model or frame buffers.
            for old in list(self.sessions):
                if len(self.sessions) > 100 and not self.sessions[old]["enabled"]:
                    del self.sessions[old]
            return self.describe(session)

    def get(self, session_id):
        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(404, "세션을 찾을 수 없습니다.")
        return session

    def describe(self, session):
        options = session["options"]
        return {"session_id": session["id"], "enabled": session["enabled"], "started_at": session["started_at"],
                "frames": session["frames"], "segment": session["segment"], "options": options,
                "detections_by_class": dict(session["counts"]), "alerts_by_type": dict(session["alerts"]),
                "model": session["model_metadata"], "output_directory": str(session["folder"].resolve()),
                "input_frames_saved": False, "training_performed": False, "accuracy_evaluated": False,
                "temporal_warnings": options["source_kind"] != "image",
                "collision_warnings": options["source_kind"] != "image" and options["fixed_camera"] and options["sampling_fps"] >= 4,
                "unity_focus_or_stop_zones_applied": False,
                "simulation_collision_policy_applied":options.get("simulation_collision_policy",False),
                "real_incident_scene_applied":options.get("real_incident_scene",False),
                "real_incident_scope":"weakly_supervised_scene_presence; not contact identification" if options.get("real_incident_scene") else None,
                "evaluation_scope": "manual_screen_case" if options["source_kind"] == "screen" else "manual_media_case"}

    def _reset(self, session, reason):
        if session["detector"]:
            session["detector"].reset_tracking()
        session["engine"] = WarningEngine(collision_model=session["collision_policy"])
        if session["real_scene"]:session["real_scene"].reset()
        session["last_time"] = None
        session["shape"] = None
        session["segment"] += 1
        append(session["folder"]/"events.jsonl", {"event": "history_reset", "reason": reason, "at": now()})

    def reset(self, session_id):
        with self.lock:
            session = self.get(session_id)
            if not session["enabled"]:
                raise HTTPException(409, "모델이 꺼져 있습니다.")
            self._reset(session, "manual_or_media_seek")
            return self.describe(session)

    def infer(self, session_id, frame):
        with self.lock:
            session = self.get(session_id)
            if not session["enabled"]:
                raise HTTPException(409, "모델이 꺼져 있습니다. 새 세션을 시작해 주세요.")
            if session["frames"] >= 5000:
                self._stop(session)
                raise HTTPException(409, "세션 최대 5,000프레임입니다. 새 세션으로 계속해 주세요.")
            still = session["options"]["source_kind"] == "image"
            if not still and frame.timestamp == session["last_time"]:
                raise HTTPException(409, "같은 영상 시각은 중복 분석하지 않습니다.")
            image = decode_frame(frame.image_b64)
            height, width = image.shape[:2]
            reset_reason = None
            if session["last_time"] is not None and (frame.timestamp < session["last_time"] or
                    frame.timestamp-session["last_time"] > 2 or session["shape"] != (width, height)):
                reset_reason = "seek_gap_or_size_change"
                self._reset(session, reset_reason)
            if still:
                session["detector"].reset_tracking()
            boxes, elapsed = session["detector"].predict(image)
            record = {"camera_id": "lab-"+session_id, "frame": session["frames"], "timestamp": frame.timestamp,
                      "timestamp_kind": "still_image" if still else "capture_seconds" if session["options"]["source_kind"] == "screen" else "video_seconds",
                      "width": width, "height": height, "detections": boxes, "inference_ms": elapsed,
                      "segment": session["segment"], "request_id": frame.request_id}
            alerts = [] if still else session["engine"].update(record)
            if session["real_scene"] and not still:
                scene_started=time.perf_counter()
                scene_alerts,scene_score=session["real_scene"].update(image,record)
                alerts.extend(scene_alerts)
                record["real_scene_vote_ratio"]=scene_score
                record["scene_inference_ms"]=(time.perf_counter()-scene_started)*1000
                record["detector_inference_ms"]=elapsed
                record["inference_ms"]=elapsed+record["scene_inference_ms"]
            if not session["options"]["fixed_camera"] or session["options"]["sampling_fps"] < 4:
                alerts = [a for a in alerts if not a["type"].startswith("suspected_")]
            session["frames"] += 1
            session["last_time"] = frame.timestamp
            session["shape"] = (width, height)
            session["touched"] = time.monotonic()
            session["counts"].update(b["class_name"] for b in boxes)
            session["alerts"].update(a["type"] for a in alerts)
            append(session["folder"]/"detections.jsonl", record)
            for alert in alerts:
                append(session["folder"]/"alerts.jsonl", alert)
            return {**record, "alerts": alerts, "history_reset": reset_reason, "enabled": True}

    def _stop(self, session):
        session["enabled"] = False
        session["detector"] = None
        session["engine"] = None
        session["collision_policy"] = None
        session["real_scene"] = None
        append(session["folder"]/"events.jsonl", {"event": "model_off", "at": now()})
        write(session["folder"]/"session.json", self.describe(session))

    def stop(self, session_id):
        with self.lock:
            session = self.get(session_id)
            if session["enabled"]:
                self._stop(session)
            return self.describe(session)

    def save_report(self, session_id, review):
        with self.lock:
            session = self.get(session_id)
            report = {**self.describe(session), "saved_at": now(), "human_review": review.model_dump(),
                      "interpretation": "수동 사례 확인 결과입니다. 정답 라벨 기반 정확도나 CCTV 사고 재현율이 아닙니다."}
            name = "report-"+uuid.uuid4().hex[:10]+".json"
            write(session["folder"]/name, report)
            return {"path": str((session["folder"]/name).resolve()), "report": report}

    def shutdown(self):
        with self.lock:
            for session in self.sessions.values():
                if session["enabled"]:
                    self._stop(session)


service = LabService()
