import pytest
from sqlalchemy import create_engine
from backend.app import db
from backend.app.config import database_url


def test_supabase_url_uses_psycopg3(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:encoded%40secret@pooler.example:5432/postgres?sslmode=require")
    url = database_url()
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "encoded@secret"
    assert url.query["sslmode"] == "require"


def test_bad_schema_rejected_before_connect(monkeypatch):
    monkeypatch.setenv("DATABASE_SCHEMA", "public; DROP SCHEMA public")
    with pytest.raises(ValueError, match="DATABASE_SCHEMA"):
        db.configure("postgresql://user:password@localhost/test")


def test_missing_schema_does_not_create_tables(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_AUTO_CREATE", "false")
    url = "sqlite:///" + (tmp_path / "empty.db").as_posix()
    db.configure(url)
    with pytest.raises(RuntimeError, match="migration required"):
        db.init_db()
    from sqlalchemy import inspect
    assert inspect(db.engine).get_table_names() == []


def test_missing_columns_reported(monkeypatch, tmp_path):
    from backend.app.models import Base
    url = "sqlite:///" + (tmp_path / "old.db").as_posix()
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql("ALTER TABLE cameras DROP COLUMN image_width")
    engine.dispose()
    monkeypatch.setenv("DATABASE_AUTO_CREATE", "false")
    db.configure(url)
    with pytest.raises(RuntimeError, match="image_width"):
        db.init_db()
