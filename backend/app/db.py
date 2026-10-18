"""SQLAlchemy 엔진과 세션.

기본 저장소는 임시 SQLite다. DATABASE_URL을 바꾸면 같은 모델로 다른 DB에 붙는다.
SQLite는 스레드를 가리지 않도록 두고, 외래 키 검사를 켠다.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from backend.app.config import database_url
from backend.app.models import Base, Camera, Run, utcnow

engine: Engine | None = None
SessionLocal: sessionmaker | None = None


def _enable_sqlite_fk(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def configure(url: str | None = None) -> None:
    """엔진을 만들거나 테스트용 URL로 갈아끼운다."""
    global engine, SessionLocal
    if engine is not None:
        engine.dispose()
    resolved = url or database_url()
    kwargs: dict = {}
    if resolved.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = NullPool
    engine = create_engine(resolved, **kwargs)
    if resolved.startswith("sqlite"):
        event.listen(engine, "connect", _enable_sqlite_fk)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def init_db() -> None:
    """SQLite 파일의 상위 폴더를 만들고 테이블을 생성한다."""
    if engine is None:
        configure()
    database = engine.url.database
    if str(engine.url).startswith("sqlite") and database and database != ":memory:":
        Path(database).parent.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)


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
    """실행이 없으면 만들고, 이미 있으면 카메라 ID는 바꾸지 않는다.

    한 실행은 카메라 하나에 묶는다. 같은 run_id로 다른 카메라가 나중에 오면
    먼저 만든 실행을 그대로 쓰고, 경고 행의 camera_id만 입력값을 따른다.
    """
    ensure_camera(db, camera_id)
    run = db.get(Run, run_id)
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
