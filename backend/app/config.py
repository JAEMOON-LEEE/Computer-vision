"""저장소 루트의 .env를 읽고 실행 설정을 제공한다.

비밀값(API 키 등)은 코드에 두지 않고 .env의 환경 변수로만 읽는다.
정식 DB로 바꿀 때는 DATABASE_URL만 교체하면 된다.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/app/config.py 기준 저장소 루트
REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

# ITS 교차로 후보. fetch_its_cctv.py가 이 경로에 쓴다.
CANDIDATES_ITS_PATH = REPO_ROOT / "backend" / "data" / "its" / "candidates_its.json"
DEFAULT_SQLITE_PATH = REPO_ROOT / "backend" / "data" / "twinsight.db"


def database_url() -> str:
    """DATABASE_URL이 없으면 임시 SQLite 파일의 절대 경로를 쓴다."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    return "sqlite:///" + DEFAULT_SQLITE_PATH.resolve().as_posix()
