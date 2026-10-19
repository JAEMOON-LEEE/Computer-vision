"""ITS 스트림 갱신. 실제 ITS 호출은 하지 않는다."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from backend.app import config
from backend.app.services.its import ItsError, choose_stream, clear_cache, parse_cctv_list


@pytest.fixture(autouse=True)
def _isolate_its(tmp_path, monkeypatch):
    clear_cache()
    monkeypatch.setattr(config, "ITS_CALL_LOG", tmp_path / "call_log.txt")
    monkeypatch.setenv("ITS_API_KEY", "dummy-test-key")
    yield
    clear_cache()


def _its_body(url="http://example.test/live", name="테스트교차로"):
    return json.dumps(
        {
            "response": {
                "data": [
                    {
                        "cctvname": name,
                        "cctvurl": url,
                        "coordx": "127.0",
                        "coordy": "37.5",
                    }
                ]
            }
        },
        ensure_ascii=False,
    )


def test_parse_its_xml_and_choose_closest_same_name():
    text = (
        "<response><data><cctvname>교차로</cctvname><cctvurl>http://far</cctvurl>"
        "<coordx>127.2</coordx><coordy>37.5</coordy></data>"
        "<data><cctvname>교차로</cctvname><cctvurl>http://near</cctvurl>"
        "<coordx>127.0</coordx><coordy>37.5</coordy></data></response>"
    )
    items = parse_cctv_list(text)
    camera = SimpleNamespace(name="교차로", lat=37.5, lon=127.0, camera_id="c")
    assert choose_stream(camera, items) == "http://near"
    other = [{"cctvname": "다른곳", "cctvurl": "http://x", "coordx": "127", "coordy": "37.5"}]
    with pytest.raises(ItsError, match="가장 가까운 항목"):
        choose_stream(camera, other)


def test_stream_non_its(client, monkeypatch):
    from backend.app.services import its

    def fail_if_called(url, timeout=30):
        raise AssertionError("ITS가 아닌 카메라에서 호출되면 안 됩니다")

    monkeypatch.setattr(its, "request_text", fail_if_called)
    missing = client.post("/cameras", json={"camera_id": "tapo-empty", "source": "TAPO", "name": "빈 카메라"})
    assert missing.status_code == 200
    assert client.get("/cameras/tapo-empty/stream").status_code == 404

    created = client.post(
        "/cameras",
        json={
            "camera_id": "tapo-1",
            "source": "TAPO",
            "name": "실내",
            "stream_url": "rtsp://example.test/tapo",
        },
    )
    assert created.status_code == 200
    body = client.get("/cameras/tapo-1/stream").json()
    assert body["stream_url"] == "rtsp://example.test/tapo"
    assert body["refreshed"] is False
    assert body["warning"] is None


def test_stream_its_within_ttl_does_not_refresh(client, monkeypatch):
    from backend.app.services import its

    def fail_if_called(url, timeout=30):
        raise AssertionError("TTL 안에서는 ITS를 호출하면 안 됩니다")

    monkeypatch.setattr(its, "request_text", fail_if_called)
    fresh = datetime.now().astimezone().isoformat()
    created = client.post(
        "/cameras",
        json={
            "camera_id": "its-fresh",
            "name": "테스트교차로",
            "source": "ITS",
            "lat": 37.5,
            "lon": 127.0,
            "stream_url": "http://example.test/still-valid",
            "stream_fetched_at": fresh,
        },
    )
    assert created.status_code == 200
    body = client.get("/cameras/its-fresh/stream").json()
    assert body["refreshed"] is False
    assert body["stream_url"] == "http://example.test/still-valid"
    assert not config.ITS_CALL_LOG.exists()


def test_stream_its_expired_refreshes(client, monkeypatch):
    from backend.app.services import its

    seen = []

    def fake(url, timeout=30):
        seen.append(url)
        return _its_body("http://example.test/renewed")

    monkeypatch.setattr(its, "request_text", fake)
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    client.post(
        "/cameras",
        json={
            "camera_id": "its-old",
            "name": "테스트교차로",
            "source": "ITS",
            "lat": 37.5,
            "lon": 127.0,
            "stream_url": "http://example.test/expired",
            "stream_fetched_at": old,
        },
    )
    first = client.get("/cameras/its-old/stream")
    assert first.status_code == 200
    body = first.json()
    assert body["refreshed"] is True
    assert body["stream_url"] == "http://example.test/renewed"
    assert body["stream_fetched_at"].endswith("+00:00")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(seen[0]).query)
    assert query["type"] == ["its"]
    assert query["cctvType"] == ["1"]
    assert query["getType"] == ["json"]
    assert query["apiKey"] == ["dummy-test-key"]
    assert float(query["minX"][0]) == pytest.approx(126.99)
    assert float(query["maxX"][0]) == pytest.approx(127.01)
    assert float(query["minY"][0]) == pytest.approx(37.49)
    assert float(query["maxY"][0]) == pytest.approx(37.51)

    second = client.get("/cameras/its-old/stream")
    assert second.json()["refreshed"] is False
    assert len(seen) == 1
    log = config.ITS_CALL_LOG.read_text(encoding="utf-8").strip()
    assert "\ttype=its\t" in f"\t{log}" or "type=its" in log
    assert "results=1" in log


def test_stream_its_failure_keeps_old_url(client, monkeypatch):
    from backend.app.services import its

    def boom(url, timeout=30):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(its, "request_text", boom)
    client.post(
        "/cameras",
        json={
            "camera_id": "its-fail",
            "name": "테스트교차로",
            "source": "ITS",
            "lat": 37.5,
            "lon": 127.0,
            "stream_url": "http://example.test/keep",
            "stream_fetched_at": "2020-01-01T00:00:00+00:00",
        },
    )
    body = client.get("/cameras/its-fail/stream").json()
    assert body["refreshed"] is False
    assert body["stream_url"] == "http://example.test/keep"
    assert "ITS" in body["warning"]
    stored = client.get("/cameras/its-fail").json()
    assert stored["stream_url"] == "http://example.test/keep"
