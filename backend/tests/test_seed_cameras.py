"""카메라 시드가 주소와 키 없이 위경도만 등록하는지 확인한다."""

import json

from backend.scripts.seed_cameras import SEED_PATH, public_record, register


def test_seed_file_has_coordinates_without_streams():
    text = SEED_PATH.read_text(encoding="utf-8")
    lowered = text.lower()
    rows = json.loads(text)
    assert len(rows) == 262
    assert "stream_url" not in lowered
    assert "cctvurl" not in lowered
    assert "http://" not in lowered
    assert "https://" not in lowered
    assert "apikey" not in lowered
    assert all(row["lat"] is not None and row["lon"] is not None for row in rows)
    assert {key for row in rows for key in row} <= {"camera_id", "name", "source", "lat", "lon"}


def test_public_record_drops_stream_url():
    row = public_record(
        {
            "camera_id": "its-sample",
            "name": "샘플교차로",
            "source": "ITS",
            "lat": "37.5",
            "lon": "127.0",
            "stream_url": "https://example.test/signed",
            "road_type": "its",
        }
    )
    assert row == {
        "camera_id": "its-sample",
        "name": "샘플교차로",
        "source": "ITS",
        "lat": 37.5,
        "lon": 127.0,
    }


def test_register_stores_coordinates_without_stream(client):
    register(
        [
            public_record(
                {
                    "camera_id": "its-sample",
                    "name": "샘플교차로",
                    "lat": 37.5,
                    "lon": 127.0,
                    "stream_url": "https://example.test/signed",
                }
            )
        ]
    )
    camera = client.get("/cameras/its-sample").json()
    assert camera["lat"] == 37.5
    assert camera["lon"] == 127.0
    assert camera["stream_url"] is None
    assert camera["source"] == "ITS"
