"""ITS HLS 영상 중계.

ITS가 주는 재생 주소는 http(예: http://cctvsec.ktict.co.kr/...)라서 https 대시보드에서는 브라우저가 막는다.
서버가 재생목록(m3u8)과 조각(ts)을 대신 받아 같은 출처로 내려준다.

- 재생목록 안의 주소는 모두 서버 주소(…/hls/p?u=…&s=…)로 바꾼다.
- u는 원래 주소, s는 서버 비밀값으로 만든 서명이다. 서명이 맞는 주소만 받아 오므로 아무 주소나 대신 여는 중계가 되지 않는다.
- 허용 호스트(기본 ktict.co.kr, its.go.kr)가 아니면 받지 않는다. HLS_ALLOWED_HOSTS로 바꿀 수 있다.
- 같은 조각을 여러 명이 보면 짧게(기본 30초) 메모리에 두고 다시 쓴다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from urllib.parse import urljoin, urlsplit

import httpx

PLAYLIST_TYPES = ("application/vnd.apple.mpegurl", "application/x-mpegurl", "audio/mpegurl", "audio/x-mpegurl")
_URI_ATTR = re.compile(r'URI="([^"]+)"')
_SECRET = (os.getenv("HLS_PROXY_SECRET") or "").encode() or secrets.token_bytes(32)

# 테스트에서 httpx.MockTransport로 바꾼다.
transport: httpx.BaseTransport | None = None

_cache: "OrderedDict[str, tuple[float, bytes, str]]" = OrderedDict()
_cache_lock = threading.Lock()


class HlsError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def enabled() -> bool:
    """STREAM_PROXY=1이면 /stream 응답이 중계 주소를 준다. 기본은 꺼짐(로컬 http 화면에서는 필요 없음)."""
    return os.getenv("STREAM_PROXY", "0").strip().lower() in ("1", "true", "yes", "on")


def allowed_hosts() -> list[str]:
    raw = os.getenv("HLS_ALLOWED_HOSTS", "ktict.co.kr,its.go.kr")
    return [h.strip().lower().lstrip(".") for h in raw.split(",") if h.strip()]


def host_allowed(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        return False
    return any(host == h or host.endswith("." + h) for h in allowed_hosts())


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def sign(camera_id: str, url: str) -> str:
    return _b64(hmac.new(_SECRET, f"{camera_id}\n{url}".encode(), hashlib.sha256).digest()[:18])


def proxied_url(prefix: str, camera_id: str, url: str) -> str:
    token = _b64(url.encode())
    return f"{prefix}/cameras/{camera_id}/hls/p?u={token}&s={sign(camera_id, url)}"


def verify(camera_id: str, token: str, signature: str) -> str:
    try:
        url = _unb64(token).decode()
    except (ValueError, UnicodeDecodeError) as exc:
        raise HlsError("잘못된 중계 주소입니다.", 400) from exc
    if not hmac.compare_digest(sign(camera_id, url), signature or ""):
        raise HlsError("중계 주소 서명이 맞지 않습니다.", 403)
    return url


def is_playlist(url: str, content_type: str, body: bytes) -> bool:
    ctype = content_type.split(";")[0].strip().lower()
    return ctype in PLAYLIST_TYPES or urlsplit(url).path.lower().endswith(".m3u8") or body.lstrip()[:7] == b"#EXTM3U"


def rewrite_playlist(text: str, base_url: str, camera_id: str, prefix: str) -> str:
    """재생목록 안의 조각·하위 재생목록·키 주소를 서버 중계 주소로 바꾼다."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            out.append(line)
        elif stripped.startswith("#"):
            out.append(_URI_ATTR.sub(
                lambda m: f'URI="{proxied_url(prefix, camera_id, urljoin(base_url, m.group(1)))}"', line))
        else:
            out.append(proxied_url(prefix, camera_id, urljoin(base_url, stripped)))
    return "\n".join(out) + "\n"


def _cache_ttl() -> float:
    try:
        return float(os.getenv("HLS_CACHE_SECONDS", "30"))
    except ValueError:
        return 30.0


def fetch(url: str) -> tuple[bytes, str, str]:
    """(본문, Content-Type, 최종 주소). 재생목록은 캐시하지 않고 조각만 캐시한다."""
    if not host_allowed(url):
        raise HlsError("허용되지 않은 영상 주소입니다.", 403)
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < _cache_ttl():
            _cache.move_to_end(url)
            return hit[1], hit[2], url
    current = url
    try:
        with httpx.Client(transport=transport, timeout=httpx.Timeout(15.0, connect=5.0),
                          follow_redirects=False, headers={"User-Agent": "TwinSight-HLS-Relay/1.0"}) as client:
            # 리다이렉트는 직접 따라가며 매 단계 허용 호스트인지 먼저 확인한다(허용 밖 주소로는 요청 자체를 보내지 않음).
            for _ in range(5):
                response = client.get(current)
                if response.status_code not in (301, 302, 303, 307, 308):
                    break
                current = urljoin(current, response.headers.get("location", ""))
                if not host_allowed(current):
                    raise HlsError("영상 서버가 허용되지 않은 주소로 보냈습니다.", 502)
            else:
                raise HlsError("영상 서버 리다이렉트가 너무 많습니다.", 502)
    except httpx.HTTPError as exc:
        raise HlsError(f"영상 서버에 연결하지 못했습니다: {type(exc).__name__}") from exc
    final_url = current
    if response.status_code >= 400:
        raise HlsError(f"영상 서버 응답 오류: HTTP {response.status_code}", 502)
    body = response.content
    ctype = response.headers.get("content-type", "application/octet-stream")
    if not is_playlist(final_url, ctype, body):
        with _cache_lock:
            _cache[url] = (now, body, ctype)
            _cache.move_to_end(url)
            while len(_cache) > 64:
                _cache.popitem(last=False)
    return body, ctype, final_url


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
