"""HLS 중계. 가짜 영상 서버(httpx.MockTransport)를 쓰고 실제 ITS에는 연결하지 않는다."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from backend.app.services import hls_proxy

ORIGIN = "http://cctvsec.ktict.co.kr/71293/TOKEN+abc="
MASTER = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000\nchunk/low.m3u8\n"
MEDIA = ("#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-KEY:METHOD=AES-128,URI=\"key.bin\"\n"
         "#EXTINF:2.0,\nseg001.ts\n#EXTINF:2.0,\nhttp://cctvsec.ktict.co.kr/abs/seg002.ts\n")


@pytest.fixture
def upstream(monkeypatch):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url == ORIGIN:
            return httpx.Response(200, text=MASTER, headers={"content-type": "application/vnd.apple.mpegurl"})
        if url.endswith("/chunk/low.m3u8"):
            return httpx.Response(200, text=MEDIA, headers={"content-type": "application/x-mpegURL"})
        if url.endswith("/redirect.ts"):
            return httpx.Response(302, headers={"location": "http://evil.example/x.ts"})
        if url.endswith("/hop.ts"):
            return httpx.Response(302, headers={"location": "/abs/seg002.ts"})
        if url.endswith(".ts"):
            return httpx.Response(200, content=b"TSDATA-" + url.encode(), headers={"content-type": "video/mp2t"})
        if url.endswith("key.bin"):
            return httpx.Response(200, content=b"0123456789abcdef", headers={"content-type": "application/octet-stream"})
        return httpx.Response(404)

    monkeypatch.setattr(hls_proxy, "transport", httpx.MockTransport(handler))
    monkeypatch.setenv("STREAM_PROXY", "1")
    hls_proxy.clear_cache()
    yield calls
    hls_proxy.clear_cache()


def _add_camera(client, url=ORIGIN):
    client.post("/cameras", json={
        "camera_id": "its-test", "name": "테스트", "source": "ITS", "lat": 37.5, "lon": 127.0,
        "stream_url": url, "stream_fetched_at": datetime.now(timezone.utc).isoformat(),
    })


def _relay_links(text: str) -> list[str]:
    return [line for line in text.splitlines() if line and not line.startswith("#")]


def test_stream_returns_relay_address_under_same_prefix(client, upstream):
    _add_camera(client)
    assert client.get("/cameras/its-test/stream").json()["stream_url"] == "/cameras/its-test/hls/index.m3u8"
    assert client.get("/api/cameras/its-test/stream").json()["stream_url"] == "/api/cameras/its-test/hls/index.m3u8"
    assert upstream == []  # 주소만 주고 영상 서버에는 아직 가지 않는다


def test_stream_keeps_original_when_relay_off(client, upstream, monkeypatch):
    monkeypatch.setenv("STREAM_PROXY", "0")
    _add_camera(client)
    assert client.get("/cameras/its-test/stream").json()["stream_url"] == ORIGIN


def test_playlists_and_segments_are_relayed(client, upstream):
    _add_camera(client)
    master = client.get("/api/cameras/its-test/hls/index.m3u8")
    assert master.status_code == 200
    assert master.headers["content-type"].startswith("application/vnd.apple.mpegurl")
    [child] = _relay_links(master.text)
    assert child.startswith("/api/cameras/its-test/hls/p?u=")
    assert "cctvsec" not in master.text

    media = client.get(child)
    assert media.status_code == 200
    segments = _relay_links(media.text)
    assert len(segments) == 2 and all(s.startswith("/api/cameras/its-test/hls/p?") for s in segments)
    key_line = next(l for l in media.text.splitlines() if l.startswith("#EXT-X-KEY"))
    assert 'URI="/api/cameras/its-test/hls/p?' in key_line

    first = client.get(segments[0])
    assert first.status_code == 200 and first.headers["content-type"] == "video/mp2t"
    assert first.content == b"TSDATA-http://cctvsec.ktict.co.kr/71293/chunk/seg001.ts"
    assert client.get(segments[1]).content.endswith(b"/abs/seg002.ts")


def test_segments_are_cached_but_playlists_are_not(client, upstream):
    _add_camera(client)
    child = _relay_links(client.get("/cameras/its-test/hls/index.m3u8").text)[0]
    seg = _relay_links(client.get(child).text)[0]
    client.get(seg); client.get(seg)
    client.get("/cameras/its-test/hls/index.m3u8")
    assert sum(u.endswith("seg001.ts") for u in upstream) == 1
    assert sum(u == ORIGIN for u in upstream) == 2


def test_tampered_or_foreign_links_are_rejected(client, upstream):
    _add_camera(client)
    child = _relay_links(client.get("/cameras/its-test/hls/index.m3u8").text)[0]
    query = parse_qs(urlsplit(child).query)
    other = hls_proxy.proxied_url("", "its-test", "http://cctvsec.ktict.co.kr/other.ts")
    other_u = parse_qs(urlsplit(other).query)["u"][0]
    # 다른 주소에 기존 서명을 붙이면 거절
    assert client.get("/cameras/its-test/hls/p", params={"u": other_u, "s": query["s"][0]}).status_code == 403
    # 다른 카메라 이름으로 같은 서명을 쓰면 거절
    assert client.get("/cameras/its-other/hls/p", params={"u": query["u"][0], "s": query["s"][0]}).status_code == 403
    # 허용 호스트가 아니면 서명이 있어도 받지 않음
    evil = urlsplit(hls_proxy.proxied_url("", "its-test", "http://169.254.169.254/latest"))
    assert client.get(evil.path + "?" + evil.query).status_code == 403
    # 허용 호스트에서 다른 곳으로 보내도 따라가지 않음
    bounce = urlsplit(hls_proxy.proxied_url("", "its-test", "http://cctvsec.ktict.co.kr/redirect.ts"))
    assert client.get(bounce.path + "?" + bounce.query).status_code == 502
    assert not any("evil.example" in u for u in upstream)  # 허용 밖 주소로는 요청을 보내지 않는다
    # 허용 호스트 안에서의 리다이렉트는 따라간다
    hop = urlsplit(hls_proxy.proxied_url("", "its-test", "http://cctvsec.ktict.co.kr/hop.ts"))
    assert client.get(hop.path + "?" + hop.query).content.endswith(b"/abs/seg002.ts")


def test_non_its_host_is_not_relayed(client, upstream):
    _add_camera(client, url="http://example.test/live.m3u8")
    assert client.get("/cameras/its-test/stream").json()["stream_url"] == "http://example.test/live.m3u8"
    assert client.get("/cameras/its-test/hls/index.m3u8").status_code == 403


def test_upstream_error_becomes_502(client, upstream):
    _add_camera(client, url="http://cctvsec.ktict.co.kr/missing.m3u8")
    response = client.get("/cameras/its-test/hls/index.m3u8")
    assert response.status_code == 502 and "HTTP 404" in response.json()["detail"]
