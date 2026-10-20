"""SQLAlchemy 엔진과 세션.

기본 저장소는 PostgreSQL이다. SQLite는 명시적 URL과 로컬 테스트를 지원한다.
SQLite는 스레드를 가리지 않도록 두고, 외래 키 검사를 켠다.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, URL, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from backend.app.config import database_url
from backend.app.models import Base, Camera, Run, utcnow
from backend.app import catalog_models  # Register additive catalog tables before create_all.

engine: Engine | None = None
SessionLocal: sessionmaker | None = None


def _enable_sqlite_fk(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def configure(url: str | URL | None = None) -> None:
    """엔진을 만들거나 테스트용 URL로 갈아끼운다."""
    global engine, SessionLocal
    if engine is not None:
        engine.dispose()
    resolved = url or database_url()
    dialect = make_url(resolved).get_backend_name()
    kwargs: dict = {"pool_pre_ping": True, "hide_parameters": True}
    if dialect == "postgresql":
        kwargs["connect_args"] = {"connect_timeout": 5}
    if dialect == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = NullPool
    engine = create_engine(resolved, **kwargs)
    if dialect == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_fk)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    """SQLite 파일의 상위 폴더를 만들고 테이블을 생성한다."""
    if engine is None:
        configure()
    database = engine.url.database
    if engine.dialect.name == "sqlite" and database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    for table in Base.metadata.sorted_tables:
        for index in table.indexes:
            if index.name.startswith("ix_map_"):
                index.create(bind=engine, checkfirst=True)


def get_db():
    if SessionLocal is None:
        configure()
    session = SessionLocal()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def resolve_run_id(run_id: str | None, camera_id: str) -> str:
    """쿼리의 run_id가 없으면 카메라별 기본 실행 이름을 쓴다."""
    if run_id and run_id.strip():
        return run_id.strip()
    return f"{camera_id}-default"


def ensure_camera(db: Session, camera_id: str) -> Camera:
    """수신 데이터에 카메라가 없으면 source=unknown으로 만든다."""
    camera = db.get(Camera, camera_id)
    if camera is None:
        camera = Camera(
            camera_id=camera_id,
            name=camera_id,
            source="unknown",
            status="unknown",
            is_ptz=False,
            created_at=utcnow(),
        )
        db.add(camera)
        db.flush()
    return camera


def ensure_run(db: Session, run_id: str, camera_id: str, timestamp_kind: str | None) -> Run:
    """실행의 카메라와 시간 기준을 고정해 서로 다른 이력이 섞이지 않게 한다."""
    run = db.get(Run, run_id)
    if run is not None:
        if run.camera_id != camera_id:
            raise HTTPException(409, "run_id는 한 카메라에만 사용할 수 있습니다")
        if timestamp_kind and run.timestamp_kind and run.timestamp_kind != timestamp_kind:
            raise HTTPException(409, "실행의 timestamp_kind를 변경할 수 없습니다")
    ensure_camera(db, camera_id)
    if run is None:
        run = Run(
            run_id=run_id,
            camera_id=camera_id,
            timestamp_kind=timestamp_kind,
            started_at=utcnow(),
        )
        db.add(run)
        db.flush()
        return run
    if run.timestamp_kind is None and timestamp_kind:
        run.timestamp_kind = timestamp_kind
    return run


configure()
