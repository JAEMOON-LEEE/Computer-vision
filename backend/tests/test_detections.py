"""검출 이력 조회. 카메라·클래스·기간·페이지마다 한 번씩 확인한다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.tests.test_api import detection_item, frame_record

KST = timezone(timedelta(hours=9))
# 2026-10-19 15:30 KST
ORIGIN = datetime(2026, 10, 19, 15, 30, tzinfo=KST)


def _post(client, camera_id: str, frame: int, timestamp: float, names: list[str]):
    record = frame_record(
        camera_id=camera_id,
        frame=frame,
        timestamp=timestamp,
        timestamp_kind="unix_seconds",
        detections=[detection_item(class_name=name, track_id=index + 1) for index, name in enumerate(names)],
    )
    response = client.post("/ingest/detections", json=record)
    assert response.status_code == 200


def _seed(client):
    origin = ORIGIN.timestamp()
    _post(client, "cam-a", 1, origin, ["car", "person"])
    _post(client, "cam-a", 2, origin + 3600, ["car"])
    _post(client, "cam-b", 1, origin + 10, ["pothole"])
    _post(client, "cam-a", 3, origin - 7200, ["truck"])
    return origin


def test_detections_newest_first_and_total(client):
    origin = _seed(client)
    body = client.get("/detections").json()
    assert body["total"] == 5
    assert body["items"][0]["timestamp"] == origin + 3600
    assert body["items"][0]["class_name"] == "car"
    assert body["items"][0]["camera_id"] == "cam-a"
    assert body["items"][0]["timestamp_kind"] == "unix_seconds"
    assert [item["timestamp"] for item in body["items"]] == sorted(
        (item["timestamp"] for item in body["items"]), reverse=True
    )


def test_detections_filter_camera(client):
    _seed(client)
    body = client.get("/detections", params={"camera_id": "cam-b"}).json()
    assert body["total"] == 1
    assert body["items"][0]["class_name"] == "pothole"
    assert body["items"][0]["camera_id"] == "cam-b"


def test_detections_filter_classes(client):
    _seed(client)
    body = client.get("/detections", params=[("class_name", "car"), ("class_name", "person")]).json()
    assert body["total"] == 3
    assert {item["class_name"] for item in body["items"]} == {"car", "person"}


def test_detections_filter_period(client):
    origin = _seed(client)
    start = (ORIGIN - timedelta(minutes=1)).isoformat()
    end = (ORIGIN + timedelta(minutes=30)).isoformat()
    body = client.get("/detections", params={"from": start, "to": end}).json()
    assert body["total"] == 3
    assert all(origin - 60 <= item["timestamp"] <= origin + 1800 for item in body["items"])
    assert "truck" not in {item["class_name"] for item in body["items"]}


def test_detections_limit_offset(client):
    _seed(client)
    first = client.get("/detections", params={"limit": 1, "offset": 0}).json()
    second = client.get("/detections", params={"limit": 1, "offset": 1}).json()
    assert first["total"] == 5
    assert len(first["items"]) == 1
    assert len(second["items"]) == 1
    assert first["items"][0]["frame"] != second["items"][0]["frame"] or first["items"][0]["class_name"] != second["items"][0]["class_name"]


def test_detections_reject_naive_bound(client):
    response = client.get("/detections", params={"from": "2026-10-19T15:00:00"})
    assert response.status_code == 400
    assert "오프셋" in response.json()["detail"]


def test_detection_stats_by_class_and_kst_hour(client):
    origin = _seed(client)
    start = (ORIGIN - timedelta(hours=1)).isoformat()
    end = (ORIGIN + timedelta(hours=2)).isoformat()
    body = client.get(
        "/detections/stats",
        params={"camera_id": "cam-a", "from": start, "to": end, "class_name": "car"},
    ).json()
    assert body["by_class"] == [{"class_name": "car", "count": 2}]
    hours = {row["hour"]: row["count"] for row in body["by_hour"]}
    assert hours["2026-10-19T15:00:00+09:00"] == 1
    assert hours["2026-10-19T16:00:00+09:00"] == 1
    assert all(hour.endswith("+09:00") for hour in hours)
    assert origin > 0
