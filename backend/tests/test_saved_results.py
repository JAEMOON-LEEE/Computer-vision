import json

from backend.app import db
from backend.app.catalog_models import CatalogLog, CatalogRecord


def seed(message):
    with db.SessionLocal() as session:
        session.add(CatalogRecord(record_id="saved", kind="detection", title="실험", owner="team",
                                  data_origin="synthetic", status="completed", details={}, fingerprint="a" * 64))
        session.flush()
        session.add(CatalogLog(record_id="saved", stream="detections.jsonl-abc", line_no=1, message=message))
        session.commit()


def test_saved_playback_does_not_create_live_data(client):
    seed(json.dumps({"camera_id": "cam", "frame": 0, "timestamp": 0, "width": 720, "height": 480,
                     "detections": [{"class_name": "car", "confidence": .9, "bbox_xyxy": [1, 2, 10, 20]}]}))
    items = client.get("/api/database/saved-results").json()
    assert items[0]["frames"] == 1
    assert items[0]["origin"] == "synthetic"
    response = client.get("/api/database/saved-results/frame?record_id=saved").json()
    assert response["camera_location"] is None
    assert len(response["detections"]) == 1
    client.post("/api/database/cameras", json={"camera_id": "cam", "name": "확인된 촬영 위치", "lat": 37.5, "lon": 127})
    assert client.get("/api/database/saved-results/frame?record_id=saved").json()["camera_location"] == {"lat": 37.5, "lon": 127}
    assert client.get("/api/database/tables/detections").json()["total"] == 0
    assert client.get("/api/database/saved-results/frame?record_id=saved&offset=1").status_code == 404
    assert client.get("/api/database/saved-results/frame?record_id=saved&offset=-1").status_code == 422


def test_malformed_saved_frame_is_reported(client):
    seed('{"width":NaN,"height":480,"detections":[]}')
    assert client.get("/api/database/saved-results/frame?record_id=saved").status_code == 422
    assert client.get("/api/database/saved-results/frame?record_id=missing").status_code == 404


def test_virtual_ground_truth_keeps_world_coordinates_separate(client):
    seed('{"width":720,"height":480,"detections":[]}')
    with db.SessionLocal() as session:
        session.add(CatalogLog(record_id="saved", stream="ground_truth.jsonl-abc", line_no=1,
            message=json.dumps({"camera_id": "sim", "frame": 0, "width": 720, "height": 480,
                "objects": [{"class_name": "car", "bbox_xyxy": [1,2,10,20], "ground_point_world": [3,0.5,-7]}]})))
        session.commit()
    rows = client.get("/api/database/saved-results").json()
    assert {r["source"] for r in rows} == {"detections", "ground_truth"}
    frame = client.get("/api/database/saved-results/frame?record_id=saved&source=ground_truth").json()
    assert frame["detections"][0]["world_xz"] == [3,-7]
    assert frame["camera_location"] is None
    assert client.get("/api/database/saved-results/frame?record_id=saved").json()["detections"] == []
    assert client.get("/api/database/saved-results/frame?record_id=saved&source=other").status_code == 422
