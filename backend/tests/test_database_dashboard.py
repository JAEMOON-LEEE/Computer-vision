from backend.tests.test_api import alert_record, detection_item, frame_record


def test_overview_and_table_allowlist(client):
    overview = client.get("/api/database/overview")
    assert overview.status_code == 200
    assert len(overview.json()["tables"]) == 12
    assert "password" not in overview.text
    assert client.get("/api/database/tables/pg_authid").status_code == 404
    assert client.get("/api/database/tables/cameras?limit=101").status_code == 422


def test_camera_edit_preserves_stream_and_validates_coordinates(client):
    payload = {"camera_id": "edit-cam", "name": "테스트", "lat": 37.5, "lon": 127, "status": "active"}
    assert client.post("/api/database/cameras", json=payload).status_code == 201
    assert client.post("/api/database/cameras", json=payload).status_code == 409
    assert client.post("/api/database/cameras", json={**payload, "lat": 91}).status_code == 422
    assert client.post("/api/database/cameras", json={**payload, "lat": None}).status_code == 422
    from backend.app import db
    from backend.app.models import Camera
    with db.SessionLocal() as session:
        session.get(Camera, "edit-cam").stream_url = "https://example.org/stream"
        session.commit()
    assert client.put("/api/database/cameras/edit-cam", json={**payload, "name": "수정"}).status_code == 200
    row = client.get("/api/database/tables/cameras?q=edit-cam").json()["items"][0]
    assert row["name"] == "수정"
    assert row["stream_url"] == "https://example.org/stream"


def test_literal_id_search_and_pagination(client):
    for name in ("a_1", "ab1", "c-3"):
        client.post("/api/database/cameras", json={"camera_id": name, "name": name})
    result = client.get("/api/database/tables/cameras?q=_").json()
    assert result["total"] == 1
    assert result["items"][0]["camera_id"] == "a_1"
    first = client.get("/api/database/tables/cameras?limit=2").json()
    second = client.get("/api/database/tables/cameras?limit=2&offset=2").json()
    assert first["total"] == 3
    assert len(second["items"]) == 1
    assert {r["camera_id"] for r in first["items"]}.isdisjoint(r["camera_id"] for r in second["items"])


def test_map_reference_requires_run_and_is_immutable(client):
    payload = {"run_id": "map-run", "origin_lat": 37.5, "origin_lon": 127}
    assert client.post("/api/database/map-references", json=payload).status_code == 404
    client.post("/api/ingest/detections?run_id=map-run", json=frame_record())
    assert client.get("/api/database/map-reference", params={"run_id": "map-run"}).json() is None
    assert client.post("/api/database/map-references", json=payload).status_code == 201
    assert client.get("/api/database/map-reference", params={"run_id": "map-run"}).json() == payload
    assert client.post("/api/database/map-references", json={**payload, "origin_lat": 38}).status_code == 409
    assert client.post("/api/database/map-references", json={**payload, "origin_lat": 85}).status_code == 422


def test_alert_change_creates_one_history_row(client):
    result = client.post("/api/ingest/alerts", json=alert_record()).json()
    alert_id = result["saved"][0]["id"]
    for _ in range(2):
        assert client.patch(f"/api/alerts/{alert_id}", json={"status": "confirmed", "handled_by": "dashboard"}).status_code == 200
    history = client.get("/api/database/tables/alert_history").json()
    assert history["total"] == 1
    assert history["items"][0]["old_status"] == "unconfirmed"
    assert history["items"][0]["new_status"] == "confirmed"


def test_ingest_preserves_original_coordinates_on_frame_replacement(client):
    for x in (1, 2):
        payload = frame_record(detections=[detection_item(mapped_xz=[x, 3], mapped_xz_corrected=[4, 5])])
        assert client.post("/api/ingest/detections", json=payload).status_code == 200
    result = client.get("/api/database/tables/detection_coordinates").json()
    assert result["total"] == 1
    assert result["items"][0]["raw_xz"] == [2, 3]


def test_run_cannot_switch_camera(client):
    client.post("/api/ingest/detections?run_id=same", json=frame_record(camera_id="a"))
    assert client.post("/api/ingest/detections?run_id=same", json=frame_record(camera_id="b")).status_code == 409


def test_hour_bucket_floors_at_half_hour(client):
    from datetime import datetime, timezone
    timestamp = datetime(2026, 10, 26, 0, 45, tzinfo=timezone.utc).timestamp()
    client.post("/api/ingest/detections", json=frame_record(timestamp=timestamp))
    result = client.get("/api/detections/stats").json()
    assert result["by_hour"][0]["hour"] == "2026-10-26T09:00:00+09:00"
