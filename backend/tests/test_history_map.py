"""지도 위치의 근거, 실행 격리, 좌표 보존, 기존 DB 업그레이드를 검증한다."""
import math

import pytest
from sqlalchemy import inspect, select

from backend.tests.test_api import alert_record, detection_item, frame_record


def post_frame(client, run="run-a", **kwargs):
    response = client.post("/ingest/detections", params={"run_id": run}, json=frame_record(**kwargs))
    assert response.status_code == 200, response.text


def test_run_conflicts_rollback_entire_batch(client):
    records = [frame_record(camera_id="a"), frame_record(camera_id="b")]
    response = client.post("/ingest/detections?run_id=mixed", json=records)
    assert response.status_code == 409
    assert client.get("/runs").json()["items"] == []
    assert client.get("/cameras").json() == []
    post_frame(client)
    assert client.post("/ingest/detections?run_id=run-a", json=frame_record(timestamp_kind="video_seconds")).status_code == 409
    assert client.post("/ingest/alerts?run_id=run-a", json=alert_record(camera_id="other")).status_code == 409
    assert client.get("/alerts").json() == []


def test_alert_batch_conflict_rolls_back_savepoints(client):
    response = client.post("/ingest/alerts?run_id=mixed", json=[alert_record(), alert_record(camera_id="b", alert_id="b:2")])
    assert response.status_code == 409
    assert client.get("/alerts").json() == []
    assert client.get("/runs").json()["items"] == []


def test_coordinate_preservation_overwrite_and_pagination(client):
    d = detection_item(mapped_xz=[1, 2], mapped_xz_corrected=[3, 4])
    for n in (3, 1, 2):
        post_frame(client, frame=n, detections=[d])
    result = client.get("/runs/run-a/frames?limit=2").json()
    assert [r["frame"] for r in result["items"]] == [1, 2]
    assert result["next_after_frame"] == 2
    saved = result["items"][0]["detections"][0]
    assert saved["mapped_xz"] == [3, 4]
    assert saved["mapped_xz_raw"] == [1, 2]
    assert saved["mapped_xz_corrected"] == [3, 4]
    assert client.get("/runs/run-a/frames?after_frame=2").json()["items"][0]["frame"] == 3
    post_frame(client, frame=1, detections=[detection_item(mapped_xz=[0, 0])])
    rows = client.get("/runs/run-a/frames").json()["items"]
    assert rows[0]["detections"][0]["mapped_xz"] == [0, 0]
    assert rows[0]["detections"][0]["mapped_xz_corrected"] is None
    from backend.app import db
    from backend.app.models import DetectionCoordinates
    with db.SessionLocal() as session:
        assert len(session.scalars(select(DetectionCoordinates)).all()) == 3


def test_repeated_frame_in_single_batch(client):
    frames = [frame_record(detections=[detection_item(mapped_xz=[1, 2])]),
              frame_record(detections=[detection_item(mapped_xz=[5, 6])])]
    assert client.post("/ingest/detections?run_id=r", json=frames).status_code == 200
    items = client.get("/runs/r/frames").json()["items"]
    assert len(items) == 1
    assert items[0]["detections"][0]["mapped_xz_raw"] == [5, 6]


def test_map_namespaces_untracked_missing_coords_and_limits(client):
    for n in range(3):
        post_frame(client, frame=n, timestamp=n, detections=[
            detection_item(track_id=1, model_id="primary", mapped_xz=[n, n]),
            detection_item(track_id=1, model_id="road", mapped_xz=[n + 10, n]),
            detection_item(track_id=None, mapped_xz=[n, 20]),
            detection_item(track_id=2),
        ])
    result = client.get("/runs/run-a/map?frame_limit=2").json()
    assert result["frames_truncated"] is True
    assert result["first_frame"] == 1
    assert len(result["tracks"]) == 3
    assert len(result["untracked"]) == 2
    assert result["unmapped_detections"] == 2
    assert result["reference"] is None
    assert all(p["latlon"] is None for t in result["tracks"] for p in t["points"])


def test_reference_inverse_immutable_and_distance_guard(client):
    from backend.app.routers.history import to_latlon
    from backend.app.models import MapReference
    lat0, lon0, lat, lon = 36.78, 127.0, 36.781, 127.002
    e2 = (1 / 298.257223563) * (2 - 1 / 298.257223563)
    denom = 1 - e2 * math.sin(math.radians(lat0)) ** 2
    x = math.radians(lon - lon0) * 6378137 / math.sqrt(denom) * math.cos(math.radians(lat0))
    z = math.radians(lat - lat0) * 6378137 * (1 - e2) / denom ** 1.5
    ref = MapReference(origin_lat=lat0, origin_lon=lon0)
    assert to_latlon([x, z], ref) == pytest.approx([lat, lon], abs=1e-10)
    assert to_latlon([5001, 0], ref) is None
    post_frame(client, detections=[detection_item(mapped_xz=[x, z])])
    body = {"coordinate_system": "local_enu", "units": "m", "origin_lat": lat0, "origin_lon": lon0}
    assert client.put("/runs/run-a/map-reference", json=body).status_code == 200
    assert client.put("/runs/run-a/map-reference", json=body).status_code == 200
    result = client.get("/runs/run-a/map").json()
    assert result["tracks"][0]["points"][0]["latlon"] == pytest.approx([lat, lon])
    assert client.put("/runs/run-a/map-reference", json={**body, "origin_lat": 37}).status_code == 409
    assert client.put("/runs/run-a/map-reference", json={**body, "coordinate_system": "unity"}).status_code == 422
    assert client.put("/runs/run-a/map-reference", json={**body, "origin_lat": 90}).status_code == 422


def test_risk_uses_exact_frame_and_model_not_latest_or_camera(client):
    # Alert arrives first; map resolves it after its matching frame arrives.
    a = alert_record(camera_id="utic-1294", frame=1, evidence=[{"track_id": 15, "model_id": "primary", "class_name": "car"}])
    assert client.post("/ingest/alerts?run_id=run-a", json=a).status_code == 200
    assert client.get("/runs/run-a/map").json()["risks"][0]["locations"] == []
    post_frame(client, frame=1, detections=[detection_item(mapped_xz=[1, 2])])
    post_frame(client, frame=2, detections=[detection_item(mapped_xz=[99, 99])])
    result = client.get("/runs/run-a/map?frame_limit=1").json()
    assert result["risks"][0]["locations"] == [{"xz": [1, 2], "latlon": None}]
    a.update(alert_id="missing-model", evidence=[{"track_id": 15}])
    assert client.post("/ingest/alerts?run_id=run-a", json=a).status_code == 200
    risks = client.get("/runs/run-a/map").json()["risks"]
    assert next(r for r in risks if r["alert"]["alert_id"] == "missing-model")["location_basis"] == "unlocated"


def test_alert_history_noop_and_handler_changes(client):
    saved = client.post("/ingest/alerts", json=alert_record()).json()["saved"][0]
    path = f"/alerts/{saved['id']}"
    assert client.patch(path, json={}).status_code == 200
    assert client.get(path + "/history").json()["items"] == []
    for body in ({"status": "confirmed", "handled_by": "이상민"},
                 {"status": "confirmed", "handled_by": "이상민"}, {"handled_by": "operator"}):
        assert client.patch(path, json=body).status_code == 200
    history = client.get(path + "/history").json()["items"]
    assert len(history) == 2
    assert history[0]["old_status"] == "unconfirmed"
    assert history[0]["new_status"] == "confirmed"
    assert history[1]["old_handled_by"] == "이상민"
    assert history[1]["handled_by"] == "operator"
    page = client.get(path + "/history?limit=1").json()
    assert page["next_after_id"] == history[0]["id"]


def test_existing_database_additive_upgrade(client):
    from backend.app import db
    from backend.app.models import AlertHistory, DetectionCoordinates, MapReference
    post_frame(client, detections=[detection_item(mapped_xz_corrected=[7, 8])])
    # Emulate the legacy schema without deleting its data.
    for table in (AlertHistory.__table__, DetectionCoordinates.__table__, MapReference.__table__):
        table.drop(db.engine)
    db.init_db()
    db.init_db()
    assert "map_references" in inspect(db.engine).get_table_names()
    item = client.get("/runs/run-a/frames").json()["items"][0]["detections"][0]
    assert item["mapped_xz"] == [7, 8]
    assert item["coordinate_provenance"] == "legacy_preferred_only"
    assert item["mapped_xz_raw"] is None


@pytest.mark.parametrize("path", ["/runs/missing/map", "/runs/missing/frames", "/alerts/999/history"])
def test_unknown_history_404(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("body", [{"lat": 91}, {"lon": 181}])
def test_camera_coordinates_reject_invalid(client, body):
    assert client.post("/cameras", json={"camera_id": "bad", **body}).status_code == 422


def test_demo_end_to_end(client):
    from backend.scripts.seed_map_demo import seed
    seed(client, "test-demo")
    snapshot = client.get("/runs/test-demo/map").json()
    assert snapshot["last_frame"] == 29
    assert len(snapshot["tracks"]) == 2
    assert snapshot["risks"][0]["locations"][0]["latlon"] is not None


def test_its_invalid_coordinates_roll_back(client, tmp_path, monkeypatch):
    import json
    from backend.app import config
    path = tmp_path / "cameras.json"
    path.write_text(json.dumps([{"camera_id": "valid", "lat": 37, "lon": 127},
                                {"camera_id": "invalid", "lat": 999, "lon": 127}]))
    monkeypatch.setattr(config, "CANDIDATES_ITS_PATH", path)
    assert client.post("/cameras/import-its").status_code == 400
    assert client.get("/cameras").json() == []


def test_map_model_duplicate_evidence_is_not_guessed(client):
    post_frame(client, frame=1, detections=[detection_item(mapped_xz=[1, 2]), detection_item(mapped_xz=[3, 4])])
    record = alert_record(camera_id="utic-1294", frame=1, evidence=[{"track_id": 15, "model_id": "primary"}])
    assert client.post("/ingest/alerts?run_id=run-a", json=record).status_code == 200
    risk = client.get("/runs/run-a/map").json()["risks"][0]
    assert risk["locations"] == []
