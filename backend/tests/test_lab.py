import base64
import json

import cv2
import numpy as np
import pytest

from backend.app.lab_service import LabService
from backend.app.routers import lab


class DetectorStub:
    def __init__(self):
        self.resets = 0

    def metadata(self):
        return {"models": [{"sha256": "fake-for-contract-test"}], "focus": None}

    def predict(self, image):
        return [{"class_name": "debris", "class_id": 3, "category_id": 8,
                 "model_id": "primary", "confidence": .9, "track_id": 1,
                 "bbox_xyxy": [10, 10, 20, 20], "ground_point_px": [15, 20]}], 2.0

    def reset_tracking(self):
        self.resets += 1


@pytest.fixture
def service(tmp_path, monkeypatch):
    service = LabService(tmp_path/"lab", factory=lambda *_: DetectorStub())
    monkeypatch.setattr(lab, "service", service)
    return service


def frame(t):
    image = np.zeros((80, 120, 3), np.uint8)
    payload = base64.b64encode(cv2.imencode(".jpg", image)[1]).decode()
    return {"image_b64": payload, "timestamp": t, "request_id": str(t)}


def test_image_is_detection_only_and_off_rejects_frames(client, service):
    session = client.post("/lab/sessions", json={"source_kind": "image"}).json()
    key = session["session_id"]
    for _ in range(4):
        result = client.post(f"/lab/sessions/{key}/frames", json=frame(0))
        assert result.status_code == 200
        assert result.json()["alerts"] == []
    client.post(f"/lab/sessions/{key}/stop")
    assert service.sessions[key]["detector"] is None
    assert client.post(f"/lab/sessions/{key}/frames", json=frame(1)).status_code == 409


def test_seek_resets_tracking_and_original_video_time_is_logged(client, service):
    key = client.post("/lab/sessions", json={"source_kind": "video", "fixed_camera": True}).json()["session_id"]
    observed = []
    for t in [10, 10.2, 10.4, 10.6]:
        response = client.post(f"/lab/sessions/{key}/frames", json=frame(t))
        assert response.status_code == 200
        observed.extend(response.json()["alerts"])
    assert [a["type"] for a in observed] == ["road_debris"]
    assert client.post(f"/lab/sessions/{key}/frames", json=frame(10.6)).status_code == 409
    seek = client.post(f"/lab/sessions/{key}/frames", json=frame(1)).json()
    assert seek["history_reset"] == "seek_gap_or_size_change"
    assert seek["timestamp"] == 1
    assert seek["timestamp_kind"] == "video_seconds"
    assert service.sessions[key]["detector"].resets == 1
    path = service.sessions[key]["folder"]/"detections.jsonl"
    assert json.loads(path.read_text().splitlines()[-1])["segment"] == 1


def test_invalid_inputs_and_session_limits(client, service):
    assert client.post("/lab/sessions", json={"source_kind": "video", "model": "../../other"}).status_code == 422
    assert client.post("/lab/sessions", json={"source_kind": "image", "crop_percent": [80, 0, 50, 100]}).status_code == 422
    a = client.post("/lab/sessions", json={"source_kind": "video"}).json()["session_id"]
    client.post("/lab/sessions", json={"source_kind": "video"})
    assert client.post("/lab/sessions", json={"source_kind": "video"}).status_code == 409
    assert client.post(f"/lab/sessions/{a}/frames", json={"timestamp": 0, "image_b64": "x"*20}).status_code == 422
    assert client.post("/lab/sessions/not-a-session/stop").status_code == 404


def test_simulation_policy_requires_matching_model_and_fixed_temporal_source(client,service,monkeypatch):
    monkeypatch.setattr(service,"collision_v2_ready",lambda:False)
    base={"source_kind":"video","model":"collision-v2","simulation_collision_policy":True,"fixed_camera":True}
    for change in ({"model":"day-night"},{"source_kind":"image"},{"fixed_camera":False},{"sampling_fps":2}):
        assert client.post("/lab/sessions",json={**base,**change}).status_code==422
    assert client.post("/lab/sessions",json=base).status_code==503


def test_simulation_policy_rejects_mismatched_detector_weights(client,service,monkeypatch):
    from types import SimpleNamespace
    import detection.collision_policy as policy_module
    monkeypatch.setattr(service,"collision_v2_ready",lambda:True)
    monkeypatch.setattr(policy_module,"CollisionPolicy",lambda path:SimpleNamespace(metadata={"detector_weights_sha256":"another-detector"}))
    response=client.post("/lab/sessions",json={"source_kind":"video","model":"collision-v2",
        "simulation_collision_policy":True,"fixed_camera":True})
    assert response.status_code==409


def test_simulation_policy_survives_seek_reset(client,service,monkeypatch):
    from detection.collision_policy import ObservationPolicy
    monkeypatch.setattr(service,"load_collision_policy",lambda detector:ObservationPolicy())
    key=client.post("/lab/sessions",json={"source_kind":"video","model":"collision-v2",
        "simulation_collision_policy":True,"fixed_camera":True}).json()["session_id"]
    client.post(f"/lab/sessions/{key}/frames",json=frame(10))
    client.post(f"/lab/sessions/{key}/frames",json=frame(1))
    assert isinstance(service.sessions[key]["engine"].collision_model,ObservationPolicy)
    result=client.post(f"/lab/sessions/{key}/report",json={}).json()
    assert result['report']['simulation_collision_policy_applied'] is True


def test_screen_report_does_not_claim_accuracy_or_save_input_images(client, service):
    key = client.post("/lab/sessions", json={"source_kind": "screen"}).json()["session_id"]
    client.post(f"/lab/sessions/{key}/frames", json=frame(1))
    result = client.post(f"/lab/sessions/{key}/report", json={"expected_case": "debris", "judgment": "missed"}).json()
    assert result["report"]["accuracy_evaluated"] is False
    assert result["report"]["collision_warnings"] is False
    assert result["report"]["human_review"]["judgment"] == "missed"
    assert not list(service.storage.rglob("*.jpg"))


def test_same_browser_replaces_orphan_session_after_reload(client, service):
    a = client.post("/lab/sessions", json={"source_kind": "video", "client_id": "same-browser"}).json()["session_id"]
    b = client.post("/lab/sessions", json={"source_kind": "video", "client_id": "same-browser"}).json()["session_id"]
    assert not service.sessions[a]["enabled"]
    assert service.sessions[b]["enabled"]


@pytest.mark.parametrize("fixed,fps,collision", [(False, 5, False), (True, 2, False), (True, 5, True)])
def test_collision_gate_keeps_hazard_warnings(client, service, fixed, fps, collision):
    key = client.post("/lab/sessions", json={"source_kind": "video", "fixed_camera": fixed, "sampling_fps": fps}).json()["session_id"]
    class EngineStub:
        def update(self, _record):
            return [{"type": "suspected_vehicle_collision"}, {"type": "road_debris"}]
    service.sessions[key]["engine"] = EngineStub()
    result = client.post(f"/lab/sessions/{key}/frames", json=frame(0)).json()
    kinds = [a["type"] for a in result["alerts"]]
    assert "road_debris" in kinds
    assert ("suspected_vehicle_collision" in kinds) is collision


def test_real_traffic_and_scene_readiness_do_not_fallback_to_synthetic(client,service,monkeypatch):
    monkeypatch.setattr(service,"real_traffic_ready",lambda:False)
    assert client.post("/lab/sessions",json={"source_kind":"image","model":"real-traffic"}).status_code==503
    monkeypatch.setattr(service,"real_traffic_ready",lambda:True)
    monkeypatch.setattr(service,"real_incident_ready",lambda:False)
    base={"source_kind":"video","model":"real-traffic","real_incident_scene":True,"fixed_camera":True}
    for change in ({"model":"day-night"},{"source_kind":"image"},{"fixed_camera":False},{"sampling_fps":2}):
        assert client.post("/lab/sessions",json={**base,**change}).status_code==422
    assert client.post("/lab/sessions",json=base).status_code==503
    plain=client.post("/lab/sessions",json={**base,"real_incident_scene":False})
    assert plain.status_code==200
    assert plain.json()["real_incident_scene_applied"] is False


def test_real_scene_is_reset_on_seek_and_released_on_stop(client,service,monkeypatch):
    import detection.real_incident as real_module
    class SceneStub:
        def __init__(self):self.resets=0
        def reset(self):self.resets+=1
        def update(self,image,record):return [],.75
    monkeypatch.setattr(service,"real_traffic_ready",lambda:True)
    monkeypatch.setattr(service,"real_incident_ready",lambda:True)
    monkeypatch.setattr(real_module,"RealIncidentScorer",SceneStub)
    key=client.post("/lab/sessions",json={"source_kind":"video","model":"real-traffic",
        "real_incident_scene":True,"fixed_camera":True}).json()["session_id"]
    client.post(f"/lab/sessions/{key}/frames",json=frame(5))
    result=client.post(f"/lab/sessions/{key}/frames",json=frame(1)).json()
    assert result["real_scene_vote_ratio"]==.75
    assert service.sessions[key]["real_scene"].resets==1
    report=client.post(f"/lab/sessions/{key}/stop").json()
    assert report["real_incident_scene_applied"] is True
    assert service.sessions[key]["real_scene"] is None
