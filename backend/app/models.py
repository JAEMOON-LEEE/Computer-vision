"""Supabase twinsight 스키마와 로컬 개발에 사용하는 ORM 모델.

track_id와 alert_id의 번호는 한 번의 실행(Run) 안에서만 유효하다.
alert_id는 "카메라ID:번호" 형태이며 실행마다 1부터 다시 시작하므로 전역 고유값이 아니다.
실행별 지도 기준은 MapReference에 보존한다.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    """naive는 UTC로 보고, 오프셋이 있으면 UTC로 바꾼다."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class UtcDateTime(TypeDecorator):
    """DB에 넣기 전과 꺼낸 뒤 모두 UTC aware datetime으로 맞춘다."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip().replace("Z", "+00:00")
            return as_utc(datetime.fromisoformat(text))
        return as_utc(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            text = value.strip().replace("Z", "+00:00")
            return as_utc(datetime.fromisoformat(text))
        return as_utc(value)


class Base(DeclarativeBase):
    pass


class Camera(Base):
    """CCTV 한 대. stream_url은 만료되므로 stream_fetched_at을 함께 둔다."""

    __tablename__ = "cameras"

    camera_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, default="unknown", nullable=False)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    stream_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    stream_fetched_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    image_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_ptz: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String, default="unknown", nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)


class Run(Base):
    """검출·경고를 한 번 돌린 단위. 추적 ID와 경고 번호의 범위다."""

    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.camera_id"), nullable=False)
    timestamp_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)


class Frame(Base):
    """detections.jsonl 한 줄. 같은 실행의 같은 프레임 번호는 한 행만 둔다."""

    __tablename__ = "frames"
    __table_args__ = (UniqueConstraint("run_id", "frame_no", name="uq_frames_run_frame"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    frame_no: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp_kind: Mapped[str] = mapped_column(String, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    inference_ms: Mapped[float] = mapped_column(Float, nullable=False)


class Detection(Base):
    """프레임 안의 검출 상자 하나.

    mapped_x/mapped_z는 mapped_xz_corrected가 있으면 그 값, 없으면 mapped_xz,
    둘 다 없으면 null이다. 원본과 보정 좌표는 DetectionCoordinates에 따로 보존한다.
    """

    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    frame_id: Mapped[int] = mapped_column(ForeignKey("frames.id"), index=True, nullable=False)
    class_name: Mapped[str] = mapped_column(String, index=True, nullable=False)
    class_id: Mapped[int] = mapped_column(Integer, nullable=False)
    category_id: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[str] = mapped_column(String, nullable=False)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    x1: Mapped[float] = mapped_column(Float, nullable=False)
    y1: Mapped[float] = mapped_column(Float, nullable=False)
    x2: Mapped[float] = mapped_column(Float, nullable=False)
    y2: Mapped[float] = mapped_column(Float, nullable=False)
    ground_px_u: Mapped[float | None] = mapped_column(Float, nullable=True)
    ground_px_v: Mapped[float | None] = mapped_column(Float, nullable=True)
    mapped_x: Mapped[float | None] = mapped_column(Float, nullable=True)
    mapped_z: Mapped[float | None] = mapped_column(Float, nullable=True)


class Alert(Base):
    """alerts.jsonl 한 줄. 서버 id와 입력 alert_id는 다르다.

    (run_id, alert_id)만 고유하다. 다른 실행의 같은 alert_id는 별도 행이다.
    """

    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("run_id", "alert_id", name="uq_alerts_run_alert"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), nullable=False)
    alert_id: Mapped[str] = mapped_column(String, nullable=False)
    camera_id: Mapped[str] = mapped_column(String, nullable=False)
    frame_no: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    type: Mapped[str] = mapped_column(String, nullable=False)
    severity: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="unconfirmed", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)
    handled_by: Mapped[str | None] = mapped_column(String, nullable=True)


class DetectionCoordinates(Base):
    """입력 좌표 두 쌍을 보존. 기존 검출은 원본을 복원하지 않고 행을 비워 둔다."""

    __tablename__ = "detection_coordinates"
    detection_id: Mapped[int] = mapped_column(ForeignKey("detections.id", ondelete="CASCADE"), primary_key=True)
    raw_xz: Mapped[list | None] = mapped_column(JSON, nullable=True)
    corrected_xz: Mapped[list | None] = mapped_column(JSON, nullable=True)


class MapReference(Base):
    """한 실행의 지역 ENU 기준. 등록 후 수정하지 않아 과거 경로가 이동하지 않는다."""

    __tablename__ = "map_references"
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.run_id"), primary_key=True)
    origin_lat: Mapped[float] = mapped_column(Float, nullable=False)
    origin_lon: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)


class AlertHistory(Base):
    """경고 처리 상태와 처리자 변경 감사 이력. 경고 변경과 같은 트랜잭션에 저장."""

    __tablename__ = "alert_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True, nullable=False)
    old_status: Mapped[str] = mapped_column(String, nullable=False)
    new_status: Mapped[str] = mapped_column(String, nullable=False)
    old_handled_by: Mapped[str | None] = mapped_column(String, nullable=True)
    handled_by: Mapped[str | None] = mapped_column(String, nullable=True)
    changed_at: Mapped[datetime] = mapped_column(UtcDateTime(), default=utcnow, nullable=False)


# These are also installed on existing tables by init_db (create_all alone skips old tables).
Index("ix_map_runs_camera_started", Run.camera_id, Run.started_at)
Index("ix_map_alerts_run_timestamp", Alert.run_id, Alert.timestamp)
