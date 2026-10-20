"""ITS CCTV 스트림 주소를 카메라 주변에서 다시 받는다.

호출 형식과 call_log.txt 기록은 backend/scripts/fetch_its_cctv.py와 같다.
같은 카메라는 5분 안에 API를 다시 치지 않는다.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from backend.app import config

ENDPOINT = "https://openapi.its.go.kr:9443/cctvInfo"
CACHE_SECONDS = 300
# camera_id -> (monotonic 시각, url, fetched_at)
_cache: dict[str, tuple[float, str, datetime]] = {}


class ItsError(Exception):
    """스트림 주소를 받지 못했을 때."""


def clear_cache() -> None:
    _cache.clear()


def load_api_key() -> str:
    key = os.getenv("ITS_API_KEY", "").strip().strip('"').strip("'")
    if not key or not key.isascii() or "여기에" in key:
        raise ItsError("ITS_API_KEY가 없습니다. 저장소 루트 .env에 ITS_API_KEY=발급키 를 넣어주세요.")
    return key


def parse_cctv_list(text: str) -> list[dict]:
    """JSON 또는 XML 응답에서 CCTV 항목 배열을 꺼낸다."""
    try:
        body = json.loads(text)
        data = body.get("response", {}).get("data", [])
        if data is None:
            return []
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        pass
    root = ET.fromstring(text)
    items = []
    for node in root.iter("data"):
        item = {child.tag: (child.text or "").strip() for child in node}
        if item:
            items.append(item)
    return items


def log_call(type_: str, bbox, count: int) -> None:
    """fetch_its_cctv.py와 같은 탭 구분 한 줄을 남긴다."""
    path = config.ITS_CALL_LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{now:%Y-%m-%d %H:%M:%S}\ttype={type_}\tbbox={bbox}\tresults={count}\n")


def request_text(url: str, timeout: float = 30) -> str:
    """ITS HTTP 응답 본문. 테스트에서는 이 함수를 가짜로 바꾼다."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise ItsError(f"ITS 호출에 실패했습니다: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ItsError(f"ITS 호출에 실패했습니다: {exc.reason}") from exc


def _distance(camera, item: dict) -> float:
    try:
        lon = float(item.get("coordx"))
        lat = float(item.get("coordy"))
    except (TypeError, ValueError):
        return float("inf")
    return (lon - float(camera.lon)) ** 2 + (lat - float(camera.lat)) ** 2


def choose_stream(camera, items: list[dict]) -> str:
    """이름이 같은 항목의 주소를 고른다. 없으면 가장 가까운 항목 이름이 다를 때 오류."""
    name = camera.name or ""
    named = [item for item in items if (item.get("cctvname") or "") == name]
    pool = named or list(items)
    if not pool:
        raise ItsError("ITS 응답에 CCTV가 없습니다.")
    best = min(pool, key=lambda item: _distance(camera, item))
    if (best.get("cctvname") or "") != name:
        raise ItsError(f"이름이 같은 CCTV가 없습니다. 가장 가까운 항목은 '{best.get('cctvname')}' 입니다.")
    url = (best.get("cctvurl") or "").strip()
    if not url:
        raise ItsError("CCTV 항목에 스트림 주소가 없습니다.")
    return url


def refresh_stream_url(camera) -> tuple[str, datetime]:
    """(stream_url, 받은 시각)을 돌려준다. 5분 캐시가 있으면 API를 호출하지 않는다."""
    now_mono = time.monotonic()
    cached = _cache.get(camera.camera_id)
    if cached is not None and now_mono - cached[0] < CACHE_SECONDS:
        return cached[1], cached[2]
    if camera.lat is None or camera.lon is None:
        raise ItsError("카메라 위도·경도가 없어 스트림 주소를 갱신할 수 없습니다.")
    key = load_api_key()
    min_x, max_x = float(camera.lon) - 0.01, float(camera.lon) + 0.01
    min_y, max_y = float(camera.lat) - 0.01, float(camera.lat) + 0.01
    bbox = (min_x, max_x, min_y, max_y)
    params = {
        "apiKey": key,
        "type": "its",
        "cctvType": 1,
        "minX": min_x,
        "maxX": max_x,
        "minY": min_y,
        "maxY": max_y,
        "getType": "json",
    }
    url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
    try:
        text = request_text(url)
    except ItsError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ItsError(f"ITS 호출에 실패했습니다: {exc}") from exc
    try:
        items = parse_cctv_list(text)
    except ET.ParseError as exc:
        raise ItsError("ITS 응답을 해석하지 못했습니다.") from exc
    log_call("its", bbox, len(items))
    stream_url = choose_stream(camera, items)
    fetched_at = datetime.now(timezone.utc)
    _cache[camera.camera_id] = (time.monotonic(), stream_url, fetched_at)
    return stream_url, fetched_at
