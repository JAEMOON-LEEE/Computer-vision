"""기본은 임시 SQLite, TEST_DATABASE_URL 설정 시 격리된 PostgreSQL 스키마."""

from __future__ import annotations

import sys
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url
    postgres_url = os.getenv("TEST_DATABASE_URL")
    schema = "test_" + uuid.uuid4().hex if postgres_url else None
    admin = None
    if postgres_url:
        if make_url(postgres_url).get_backend_name() != "postgresql":
            raise ValueError("TEST_DATABASE_URL must be PostgreSQL")
        admin = create_engine(postgres_url, hide_parameters=True)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        url = make_url(postgres_url).update_query_dict({"options": f"-csearch_path={schema}"})
    else:
        db_path = tmp_path / "test.db"
        url = "sqlite:///" + db_path.resolve().as_posix()

    from backend.app import db as dbmod
    from backend.app.ws_manager import manager

    dbmod.configure(url)
    manager.active.clear()

    from backend.app.main import app

    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        manager.active.clear()
        if dbmod.engine is not None:
            dbmod.engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()
