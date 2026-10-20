"""Integration checks use only the per-test PostgreSQL schema."""
import os

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.exc import IntegrityError

from backend.app.models import Base, Camera, Run, Frame
from backend.scripts.migrate_sqlite import migrate

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL integration only")


def source_db(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "source.db").as_posix())
    Base.metadata.create_all(engine)
    return engine


def test_migration_preserves_rows_and_sequence(client, tmp_path):
    from backend.app import db
    source = source_db(tmp_path)
    try:
        with source.begin() as c:
            c.execute(Camera.__table__.insert(), {"camera_id": "c", "name": "실제 카메라"})
            c.execute(Run.__table__.insert(), {"run_id": "r", "camera_id": "c"})
            c.execute(Frame.__table__.insert(), {"id": 15, "run_id": "r", "frame_no": 1,
                      "timestamp": 0, "timestamp_kind": "video", "width": 640, "height": 480, "inference_ms": 1.5})
        report = migrate(source, db.engine)
        assert report["frames"]["rows"] == 1
        with db.engine.begin() as c:
            assert c.scalar(select(Camera.name)) == "실제 카메라"
            row = c.execute(select(Frame.__table__)).mappings().one()
            assert row["received_at"].tzinfo is not None
            new = dict(row)
            del new["id"]
            new["frame_no"] = 2
            assert c.execute(Frame.__table__.insert().returning(Frame.id), new).scalar_one() == 16
        with pytest.raises(ValueError, match="empty"):
            migrate(source, db.engine)
        with db.engine.connect() as c:
            assert c.scalar(select(func.count()).select_from(Frame)) == 2
    finally:
        source.dispose()


def test_migration_rolls_back_invalid_foreign_key(client, tmp_path):
    from backend.app import db
    source = source_db(tmp_path)
    try:
        with source.begin() as c:
            c.execute(Camera.__table__.insert(), {"camera_id": "valid"})
            c.execute(Run.__table__.insert(), {"run_id": "orphan", "camera_id": "missing"})
        with pytest.raises(IntegrityError):
            migrate(source, db.engine)
        with db.engine.connect() as c:
            assert c.scalar(select(func.count()).select_from(Camera)) == 0
    finally:
        source.dispose()
