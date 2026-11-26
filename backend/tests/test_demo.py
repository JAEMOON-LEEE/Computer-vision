"""시연 실시간 검출: 모델 없이 가짜 검출기로 경고 조건만 검사한다."""
import numpy as np

from backend.app.demo_service import DemoDetectionService


class FakeDetector:
    def __init__(self, frames):
        self.frames = list(frames)

    def predict(self, image):
        return self.frames.pop(0), 5.0


def box(name, conf=0.8, xyxy=(100, 200, 160, 260)):
    return {"class_name": name, "confidence": conf, "bbox_xyxy": list(xyxy), "model_id": "primary"}


def run(frames, times):
    fake = FakeDetector(frames)
    service = DemoDetectionService(factory=lambda: fake)
    image = np.zeros((480, 720, 3), np.uint8)
    return [service.infer(image, t) for t in times]


def test_persistent_guardrail_damage_alerts_once():
    results = run([[box("guardrail_abnormal")]] * 5, [0.0, 0.3, 0.6, 0.9, 1.2])
    alerts = [a for r in results for a in r["alerts"]]
    assert [a["type"] for a in alerts] == ["facility_damage"]
    assert alerts[0]["status"] == "unconfirmed"
    assert results[0]["detections"][0]["class_name"] == "guardrail_abnormal"


def test_single_frame_or_low_confidence_does_not_alert():
    results = run([[box("manhole_abnormal")], [], [box("manhole_abnormal", 0.3)], [box("manhole_abnormal", 0.3)],
                   [box("manhole_abnormal", 0.3)]], [0.0, 0.3, 0.6, 0.9, 1.2])
    assert not any(r["alerts"] for r in results)


def test_normal_facility_classes_never_alert():
    results = run([[box("guardrail_normal"), box("manhole_normal")]] * 6, [i * 0.3 for i in range(6)])
    assert not any(r["alerts"] for r in results)


def test_pothole_alert_keeps_team_alert_type():
    results = run([[box("pothole")]] * 4, [0.0, 0.3, 0.6, 0.9])
    assert [a["type"] for r in results for a in r["alerts"]] == ["road_damage"]


def test_gap_restarts_persistence():
    results = run([[box("delineator_fallen")]] * 4, [0.0, 0.3, 2.6, 2.9])
    assert not any(r["alerts"] for r in results)
