"""테스트마다 임시 SQLite 파일을 쓴다."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_SCHEMA", "")
    monkeypatch.setenv("TEAM_ACCESS_TOKEN", "")
    monkeypatch.setenv("DATABASE_AUTO_CREATE", "true")
    db_path = tmp_path / "test.db"
    url = "sqlite:///" + db_path.resolve().as_posix()
    monkeypatch.setenv("DATABASE_URL", url)

    from backend.app import db as dbmod
    from backend.app.ws_manager import manager

    dbmod.configure(url)
    manager.active.clear()

    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client
    manager.active.clear()
    if dbmod.engine is not None:
        dbmod.engine.dispose()
