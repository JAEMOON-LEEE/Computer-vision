"""Check ORM writes and additive indexes in an isolated PostgreSQL namespace."""
import os
import uuid

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.schema import DropSchema
from sqlalchemy.orm import Session


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL integration only")
def test_cloud_schema_isolated(monkeypatch):
    from backend.app import db
    from backend.app.models import Base, Camera, Run
    schema = "test_cloud_" + uuid.uuid4().hex
    monkeypatch.setenv("DATABASE_SCHEMA", schema)
    monkeypatch.setenv("DATABASE_AUTO_CREATE", "true")
    url = os.environ["TEST_DATABASE_URL"]
    admin = create_engine(url)
    try:
        db.configure(url)
        db.init_db()
        db.init_db()  # Restart must also work with existing tables and indexes.
        monkeypatch.setenv("DATABASE_AUTO_CREATE", "false")
        db.init_db()
        assert set(inspect(admin).get_table_names(schema=schema)) == set(Base.metadata.tables)
        with Session(db.engine) as s:
            s.add(Camera(camera_id="cloud", name="클라우드"))
            s.flush()
            s.add(Run(run_id="cloud-run", camera_id="cloud"))
            s.commit()
            assert s.scalar(select(Camera.name).where(Camera.camera_id == "cloud")) == "클라우드"
        assert "ix_map_runs_camera_started" in {
            i["name"] for i in inspect(admin).get_indexes("runs", schema=schema)
        }
    finally:
        db.engine.dispose()
        with admin.begin() as c:
            c.execute(DropSchema(schema, cascade=True, if_exists=True))
        admin.dispose()
