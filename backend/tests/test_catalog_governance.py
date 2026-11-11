import json

from backend.app import db
from backend.app.catalog_models import CatalogLog
from backend.tests.test_saved_results import seed


def calibration(**overrides):
    return {"calibration_id": "cal-v1", "camera_id": "cam", "version": "v1", "image_width": 720,
            "image_height": 480, "coordinate_system": "unity_xz_m", "parameters": {"fov": 60},
            "source_sha256": "a" * 64, **overrides}


def binding(**overrides):
    return {"record_id": "saved", "stream": "detections.jsonl-abc", "experiment_id": "saved",
            "camera_id": "cam", "image_width": 720, "image_height": 480, "calibration_id": "cal-v1", **overrides}


def test_registration_rejects_wrong_camera_and_resolution(client):
    seed(json.dumps({"camera_id": "cam", "width": 720, "height": 480, "detections": []}))
    assert client.post("/api/database/calibrations", json=calibration()).status_code == 201
    assert client.post("/api/database/calibrations", json=calibration(calibration_id="duplicate-version")).status_code == 409
    assert client.post("/api/database/calibrations", json=calibration(coordinate_system="unknown")).status_code == 422
    for changes, status in (({"camera_id": "other"}, 422), ({"image_width": 1440}, 422),
                            ({"calibration_id": "missing"}, 422), ({"stream": "missing"}, 404),
                            ({"experiment_id": "missing"}, 404)):
        assert client.post("/api/database/experiment-bindings", json=binding(**changes)).status_code == status
    assert client.post("/api/database/experiment-bindings", json=binding()).status_code == 201
    assert client.post("/api/database/experiment-bindings", json=binding()).status_code == 409
    data = client.get("/api/database/saved-results/record?record_id=saved").json()
    assert data["bindings"][0]["calibration_id"] == "cal-v1"


def test_entire_stream_must_match_not_just_first_frame(client):
    seed(json.dumps({"camera_id": "cam", "width": 720, "height": 480, "detections": []}))
    with db.SessionLocal() as s:
        s.add(CatalogLog(record_id="saved", stream="detections.jsonl-abc", line_no=2,
                        message=json.dumps({"camera_id": "different", "width": 720, "height": 480})))
        s.commit()
    assert client.post("/api/database/experiment-bindings", json=binding(calibration_id=None)).status_code == 422


def test_saved_search_is_bounded_and_summary_is_lazy(client):
    seed('{"width":720,"height":480,"detections":[]}')
    with db.SessionLocal() as s:
        s.add(CatalogLog(record_id="saved", stream="ground_truth.jsonl-abc", line_no=1, message="{}"))
        s.commit()
    first = client.get("/api/database/saved-results/search?limit=1").json()
    second = client.get("/api/database/saved-results/search?limit=1&offset=1").json()
    assert first["total"] == 2 and len(first["items"]) == 1
    assert first["items"][0]["source"] != second["items"][0]["source"]
    assert "summary" not in first["items"][0]
    assert client.get("/api/database/saved-results/search?q=%25").json()["total"] == 0
    assert client.get("/api/database/saved-results/search?q=실험").json()["total"] == 2
    assert client.get("/api/database/saved-results/search?limit=101").status_code == 422
    assert client.get("/api/database/saved-results/record?record_id=saved").json()["summary"] == {}
    assert client.get("/api/database/saved-results/record?record_id=missing").status_code == 404
