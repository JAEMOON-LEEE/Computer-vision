"""수신·조회·WebSocket·ITS 가져오기를 임시 SQLite로 확인한다."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
POTHOLE_ALERT = ROOT / "docs" / "validation" / "pothole-alert.jsonl"


def detection_item(**overrides):
    item = {
        "class_name": "car",
        "class_id": 2,
        "category_id": 1,
        "model_id": "primary",
        "bbox_xyxy": [310.0, 340.5, 335.1, 385.0],
        "confidence": 0.87,
        "track_id": 15,
        "ground_point_px": [322.55, 385.0],
        "extra_box_field": True,
    }
    item.update(overrides)
    return item


def frame_record(**overrides):
    record = {
        "camera_id": "utic-1294",
        "frame": 12,
        "timestamp": 1760688000.4,
        "timestamp_kind": "unix_seconds",
        "width": 720,
        "height": 480,
        "inference_ms": 12.5,
        "image": "frames/000012.jpg",
        "alert_ids": ["utic-1294:1"],
        "unexpected_field": "ignore-me",
        "detections": [detection_item()],
    }
    record.update(overrides)
    return record


def alert_record(**overrides):
    record = {
        "alert_id": "cam-a:1",
        "camera_id": "cam-a",
        "frame": 2,
        "timestamp": 10.0,
        "type": "road_damage",
        "severity": "warning",
        "status": "unconfirmed",
        "message": "Persistent pothole detected on the road",
        "evidence": [
            {
                "class_name": "pothole",
                "track_id": 1,
                "model_id": "road",
                "bbox_xyxy": [1.0, 2.0, 3.0, 4.0],
                "confidence": 0.6,
            }
        ],
        "basis": "visual_detections_and_motion",
        "debug_note": "ignore-me",
    }
    record.update(overrides)
    return record


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_openapi_has_main_paths(client):
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/health",
        "/cameras",
        "/cameras/import-its",
        "/cameras/{camera_id}",
        "/cameras/{camera_id}/detections/latest",
        "/ingest/detections",
        "/ingest/alerts",
        "/alerts",
        "/alerts/{id}",
    ):
        assert path in paths


def test_camera_upsert_and_get(client):
    created = client.post(
        "/cameras",
        json={
            "camera_id": "cam-1",
            "name": "테스트 카메라",
            "source": "TAPO",
            "lat": 37.1,
            "lon": 127.1,
            "is_ptz": False,
            "status": "online",
            "vendor_only": "ignore-me",
        },
    )
    assert created.status_code == 200
    assert created.json()["source"] == "TAPO"
    assert created.json()["name"] == "테스트 카메라"

    renamed = client.post("/cameras", json={"camera_id": "cam-1", "name": "수정된 이름"})
    assert renamed.status_code == 200
    body = client.get("/cameras/cam-1").json()
    assert body["name"] == "수정된 이름"
    assert body["source"] == "TAPO"
    assert body["status"] == "online"
    assert body["is_ptz"] is False

    listed = client.get("/cameras").json()
    assert len(listed) == 1
    assert listed[0]["camera_id"] == "cam-1"
    assert client.get("/cameras/없는카메라").status_code == 404


def test_ingest_detections_and_latest(client):
    without_mapped = client.post("/ingest/detections", json=[frame_record()])
    assert without_mapped.status_code == 200
    assert without_mapped.json()["saved"][0]["run_id"] == "utic-1294-default"

    latest = client.get("/cameras/utic-1294/detections/latest").json()
    assert latest["frame"] == 12
    assert latest["width"] == 720
    assert latest["height"] == 480
    assert latest["image"] == "frames/000012.jpg"
    assert latest["detections"][0]["class_name"] == "car"
    assert latest["detections"][0]["category_id"] == 1
    assert latest["detections"][0]["mapped_xz"] is None
    assert latest["detections"][0]["ground_point_px"] == pytest.approx([322.55, 385.0])

    only_mapped = frame_record(
        frame=13,
        detections=[detection_item(mapped_xz=[3.42, 41.87])],
    )
    assert client.post("/ingest/detections", json=only_mapped).status_code == 200
    mapped_latest = client.get("/cameras/utic-1294/detections/latest").json()
    assert mapped_latest["frame"] == 13
    assert mapped_latest["detections"][0]["mapped_xz"] == pytest.approx([3.42, 41.87])

    both = frame_record(
        frame=14,
        detections=[
            detection_item(
                mapped_xz=[3.42, 41.87],
                mapped_xz_corrected=[3.61, 44.15],
            )
        ],
    )
    assert client.post("/ingest/detections", json=both).status_code == 200
    corrected = client.get("/cameras/utic-1294/detections/latest").json()
    assert corrected["frame"] == 14
    assert corrected["width"] == 720
    assert corrected["height"] == 480
    assert corrected["detections"][0]["mapped_xz"] == pytest.approx([3.61, 44.15])

    overwritten = frame_record(
        frame=14,
        detections=[
            detection_item(
                confidence=0.42,
                class_name="truck",
                category_id=2,
                mapped_xz=[1.0, 2.0],
                mapped_xz_corrected=[9.5, 8.5],
            )
        ],
    )
    assert client.post("/ingest/detections", json=overwritten).status_code == 200
    replaced = client.get("/cameras/utic-1294/detections/latest").json()
    assert len(replaced["detections"]) == 1
    assert replaced["detections"][0]["class_name"] == "truck"
    assert replaced["detections"][0]["confidence"] == pytest.approx(0.42)
    assert replaced["detections"][0]["mapped_xz"] == pytest.approx([9.5, 8.5])

    camera = client.get("/cameras/utic-1294").json()
    assert camera["source"] == "unknown"


def test_alerts_idempotent_per_run_and_filters(client):
    first = alert_record()
    second = alert_record(
        alert_id="cam-a:2",
        camera_id="cam-b",
        timestamp=20.0,
        type="road_debris",
        message="Persistent debris detected on the road",
    )
    created = client.post("/ingest/alerts", params={"run_id": "run-a"}, json=[first, second])
    assert created.status_code == 200
    assert len(created.json()["saved"]) == 2
    assert created.json()["ignored"] == []

    duplicate = client.post("/ingest/alerts", params={"run_id": "run-a"}, json=[first, second])
    assert duplicate.status_code == 200
    assert duplicate.json()["saved"] == []
    assert duplicate.json()["ignored"] == ["cam-a:1", "cam-a:2"]

    other_run = client.post("/ingest/alerts", params={"run_id": "run-b"}, json=first)
    assert other_run.status_code == 200
    assert len(other_run.json()["saved"]) == 1
    assert other_run.json()["saved"][0]["alert_id"] == "cam-a:1"
    assert other_run.json()["saved"][0]["run_id"] == "run-b"

    rows = client.get("/alerts").json()
    assert len(rows) == 3
    assert rows[0]["timestamp"] == pytest.approx(20.0)
    same_alert = [row for row in rows if row["alert_id"] == "cam-a:1"]
    assert {row["run_id"] for row in same_alert} == {"run-a", "run-b"}
    assert len({row["id"] for row in same_alert}) == 2

    assert len(client.get("/alerts", params={"run_id": "run-a"}).json()) == 2
    assert len(client.get("/alerts", params={"camera_id": "cam-b"}).json()) == 1
    assert client.get("/alerts", params={"type": "road_debris"}).json()[0]["alert_id"] == "cam-a:2"
    assert len(client.get("/alerts", params={"from_ts": 15}).json()) == 1
    assert len(client.get("/alerts", params={"to_ts": 15}).json()) == 2
    assert client.get("/alerts", params={"status": "unconfirmed"}).json()

    target = client.get("/alerts", params={"run_id": "run-a", "type": "road_damage"}).json()[0]
    patched = client.patch(
        f"/alerts/{target['id']}",
        json={"status": "confirmed", "handled_by": "dashboard"},
    )
    assert patched.status_code == 200
    assert patched.json()["status"] == "confirmed"
    assert patched.json()["handled_by"] == "dashboard"
    assert patched.json()["id"] == target["id"]

    confirmed = client.get("/alerts", params={"status": "confirmed"}).json()
    assert len(confirmed) == 1
    assert confirmed[0]["alert_id"] == "cam-a:1"
    assert confirmed[0]["run_id"] == "run-a"
    still_open = client.get("/alerts", params={"run_id": "run-b", "status": "unconfirmed"}).json()
    assert len(still_open) == 1
    assert still_open[0]["status"] == "unconfirmed"


def test_websocket_receives_alert(client):
    payload = alert_record(alert_id="cam-ws:1", camera_id="cam-ws", timestamp=3.0)
    with client.websocket_connect("/ws") as websocket:
        created = client.post("/ingest/alerts", params={"run_id": "run-ws"}, json=payload)
        assert created.status_code == 200
        message = websocket.receive_json()
        assert message["type"] == "alert"
        assert message["alert"]["alert_id"] == "cam-ws:1"
        assert message["alert"]["run_id"] == "run-ws"
        assert isinstance(message["alert"]["id"], int)
        assert message["alert"]["status"] == "unconfirmed"

        patched = client.patch(
            f"/alerts/{message['alert']['id']}",
            json={"status": "dismissed", "handled_by": "operator"},
        )
        assert patched.status_code == 200
        updated = websocket.receive_json()
        assert updated["type"] == "alert_updated"
        assert updated["alert"]["id"] == message["alert"]["id"]
        assert updated["alert"]["status"] == "dismissed"
        assert updated["alert"]["handled_by"] == "operator"

    follow_up = client.post("/ingest/alerts", params={"run_id": "run-ws-2"}, json=payload)
    assert follow_up.status_code == 200


def test_import_its(client, tmp_path, monkeypatch):
    from backend.app import config

    path = tmp_path / "candidates_its.json"
    path.write_text(
        json.dumps(
            [
                {
                    "camera_id": "its-테스트교차로",
                    "name": "테스트교차로",
                    "source": "ITS",
                    "road_type": "its",
                    "lat": 37.5,
                    "lon": 127.0,
                    "stream_url": "http://example.test/stream",
                    "fetched_at": "2026-10-18T19:00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CANDIDATES_ITS_PATH", path)

    imported = client.post("/cameras/import-its")
    assert imported.status_code == 200
    assert imported.json()["imported"] == 1

    path.write_text(
        json.dumps(
            [
                {
                    "camera_id": "its-테스트교차로",
                    "name": "바뀐이름",
                    "source": "ITS",
                    "road_type": "ex",
                    "lat": 37.5,
                    "lon": 127.0,
                    "stream_url": "http://example.test/stream-2",
                    "fetched_at": "2026-10-18T20:00:00",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert client.post("/cameras/import-its").status_code == 200
    listed = client.get("/cameras").json()
    assert len(listed) == 1
    camera = listed[0]
    assert camera["camera_id"] == "its-테스트교차로"
    assert camera["name"] == "바뀐이름"
    assert camera["source"] == "ITS"
    assert camera["lat"] == pytest.approx(37.5)
    assert camera["lon"] == pytest.approx(127.0)
    assert camera["stream_url"] == "http://example.test/stream-2"
    assert camera["stream_fetched_at"].startswith("2026-10-18T20:00:00")
    assert camera["is_ptz"] is False
    assert "road_type" not in camera


def test_import_its_missing_file(client, tmp_path, monkeypatch):
    from backend.app import config

    monkeypatch.setattr(config, "CANDIDATES_ITS_PATH", tmp_path / "missing.json")
    response = client.post("/cameras/import-its")
    assert response.status_code == 404
    assert response.json()["detail"] == "fetch_its_cctv.py를 먼저 실행하세요"


def test_pothole_alert_sample(client):
    record = json.loads(POTHOLE_ALERT.read_text(encoding="utf-8"))
    created = client.post("/ingest/alerts", json=record)
    assert created.status_code == 200
    saved = created.json()["saved"][0]
    assert saved["alert_id"] == record["alert_id"]
    assert saved["run_id"] == "fixed-pothole-warning-default"
    assert isinstance(saved["id"], int)

    again = client.post("/ingest/alerts", json=record)
    assert again.json()["ignored"] == [record["alert_id"]]
    assert again.json()["saved"] == []

    other = client.post("/ingest/alerts", params={"run_id": "replay-2"}, json=record)
    assert len(other.json()["saved"]) == 1
    assert other.json()["saved"][0]["run_id"] == "replay-2"
    assert other.json()["saved"][0]["id"] != saved["id"]

    rows = client.get("/alerts", params={"camera_id": record["camera_id"]}).json()
    assert len(rows) == 2
    got = next(row for row in rows if row["run_id"] == "fixed-pothole-warning-default")
    assert got["type"] == record["type"]
    assert got["severity"] == record["severity"]
    assert got["status"] == record["status"]
    assert got["message"] == record["message"]
    assert got["basis"] == record["basis"]
    assert got["frame"] == record["frame"]
    assert got["timestamp"] == pytest.approx(record["timestamp"])
    assert got["evidence"][0]["class_name"] == record["evidence"][0]["class_name"]
    assert got["evidence"][0]["track_id"] == record["evidence"][0]["track_id"]
    assert got["evidence"][0]["model_id"] == record["evidence"][0]["model_id"]
    assert got["evidence"][0]["bbox_xyxy"] == pytest.approx(record["evidence"][0]["bbox_xyxy"])
    assert got["evidence"][0]["confidence"] == pytest.approx(record["evidence"][0]["confidence"])

    camera = client.get(f"/cameras/{record['camera_id']}").json()
    assert camera["source"] == "unknown"
