"""프로젝트 산출물 카탈로그. 대용량 파일은 원본 저장소에, 관계·해시는 DB에 둔다."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from backend.app.models import Base, utcnow


class CatalogRecord(Base):
    __tablename__ = "catalog_records"
    record_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(256))
    owner: Mapped[str] = mapped_column(String(128))
    data_origin: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32))
    camera_id: Mapped[str | None] = mapped_column(ForeignKey("cameras.camera_id"), index=True)
    detection_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.run_id"), index=True)
    details: Mapped[dict] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CatalogParent(Base):
    __tablename__ = "catalog_parents"
    record_id: Mapped[str] = mapped_column(ForeignKey("catalog_records.record_id"), primary_key=True)
    parent_id: Mapped[str] = mapped_column(ForeignKey("catalog_records.record_id"), primary_key=True, index=True)


class CatalogFile(Base):
    __tablename__ = "catalog_files"
    __table_args__ = (UniqueConstraint("record_id", "path", name="uq_catalog_file_path"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("catalog_records.record_id"), index=True)
    path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(64))


class CatalogLog(Base):
    __tablename__ = "catalog_logs"
    __table_args__ = (UniqueConstraint("record_id", "stream", "line_no", name="uq_catalog_log_line"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("catalog_records.record_id"), index=True)
    stream: Mapped[str] = mapped_column(String(128))
    line_no: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
