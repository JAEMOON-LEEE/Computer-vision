"""Apply the shipped SQL and run ORM operations as a non-owner PostgreSQL role.

Uses a disposable schema/NOLOGIN role; never uses the live twinsight schema.
TEST_ADMIN_DATABASE_URL is only for a disposable/local test server.
"""
import os
from pathlib import Path
import uuid

import pytest
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session


@pytest.mark.skipif(not os.getenv("TEST_ADMIN_DATABASE_URL"), reason="Local PostgreSQL admin integration only")
def test_shipped_sql_runtime_permissions(monkeypatch):
    from backend.app import db
    from backend.app.models import Camera, Run, Frame

    suffix = uuid.uuid4().hex[:12]
    schema, role = "test_deploy_" + suffix, "test_role_" + suffix
    admin_url = make_url(os.environ["TEST_ADMIN_DATABASE_URL"])
    if admin_url.host not in ("localhost", "127.0.0.1", "::1"):
        pytest.fail("Admin deployment tests are restricted to localhost")
    admin = create_engine(admin_url, hide_parameters=True)
    root = Path(__file__).resolve().parents[2]
    statements = []
    for filename in ("twinsight_schema.sql", "twinsight_runtime_role.sql"):
        source = (root / "deploy" / filename).read_text(encoding="utf-8")
        source = source.replace("twinsight_backend", role).replace("twinsight", schema)
        source = source.replace("PUBLIC, anon, authenticated", "PUBLIC")
        statements.append(source)
    try:
        with admin.begin() as c:
            for source in statements:
                with c.connection.cursor() as cursor:
                    cursor.execute(source, prepare=False)
        monkeypatch.setenv("DATABASE_SCHEMA", schema)
        monkeypatch.setenv("DATABASE_AUTO_CREATE", "false")
        db.configure(admin_url)

        @event.listens_for(db.engine, "connect")
        def use_runtime_role(connection, _):
            original = connection.autocommit
            connection.autocommit = True
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f'SET ROLE "{role}"')
            finally:
                connection.autocommit = original

        db.init_db()  # Must work with no CREATE/ALTER privilege.
        assert len(inspect(admin).get_table_names(schema=schema)) == 12
        with Session(db.engine) as s:
            s.add(Camera(camera_id="permission-test", name="권한 검증"))
            s.flush()
            s.add(Run(run_id="run", camera_id="permission-test"))
            s.flush()
            s.add(Frame(run_id="run", frame_no=0, timestamp=0,
                        timestamp_kind="video_seconds", width=640, height=480, inference_ms=1))
            s.commit()
            assert s.scalar(select(Camera.name)) == "권한 검증"
            camera = s.get(Camera, "permission-test")
            camera.name = "변경 검증"
            s.commit()
            assert s.scalar(select(Camera.name)) == "변경 검증"
        with pytest.raises(DBAPIError):
            with db.engine.begin() as c:
                c.exec_driver_sql(f'ALTER TABLE "{schema}".cameras ADD COLUMN forbidden text')
        with pytest.raises(DBAPIError):
            with db.engine.begin() as c:
                c.exec_driver_sql(f'UPDATE "{schema}".frames SET width=0')
        with pytest.raises(DBAPIError):
            with db.engine.begin() as c:
                c.exec_driver_sql(f'INSERT INTO "{schema}".runs(run_id,camera_id) VALUES (\'bad\',\'missing\')')
        with db.engine.begin() as c:
            c.exec_driver_sql(f'DELETE FROM "{schema}".frames')
        with admin.connect() as c:
            assert c.scalar(text("SELECT rolbypassrls FROM pg_roles WHERE rolname=:role"), {"role": role}) is False
    finally:
        if db.engine is not None:
            db.engine.dispose()
        with admin.begin() as c:
            c.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            # ALTER DEFAULT PRIVILEGES statements are scoped to the disposable schema.
            c.exec_driver_sql(f'DROP ROLE IF EXISTS "{role}"')
        admin.dispose()
