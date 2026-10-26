"""저장소 루트의 .env를 읽고 실행 설정을 제공한다.

비밀값(API 키 등)은 코드에 두지 않고 .env의 환경 변수로만 읽는다.
정식 DB로 바꿀 때는 DATABASE_URL만 교체하면 된다.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy.engine import make_url

# backend/app/config.py 기준 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

# ITS 교차로 후보. fetch_its_cctv.py가 이 경로에 쓴다.
CANDIDATES_ITS_PATH = REPO_ROOT / "backend" / "data" / "its" / "candidates_its.json"
ITS_CALL_LOG = REPO_ROOT / "backend" / "data" / "its" / "call_log.txt"
DEFAULT_SQLITE_PATH = REPO_ROOT / "backend" / "data" / "twinsight.db"


def database_url() -> str:
    """DATABASE_URL이 없으면 임시 SQLite 파일의 절대 경로를 쓴다."""
    url = os.getenv("DATABASE_URL")
    if url:
        parsed = make_url(url)
        if parsed.drivername in ("postgres", "postgresql"):
            parsed = parsed.set(drivername="postgresql+psycopg")
        return parsed
    return "sqlite:///" + DEFAULT_SQLITE_PATH.resolve().as_posix()


def stream_ttl_minutes() -> float:
    """ITS 스트림 주소를 다시 받는 간격. .env의 STREAM_TTL_MINUTES, 기본 30분."""
    raw = os.getenv("STREAM_TTL_MINUTES", "30").strip()
    try:
        value = float(raw)
    except ValueError:
        return 30
    if value < 0:
        return 30
    return value
