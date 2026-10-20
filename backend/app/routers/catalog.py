"""CCTV→좌표→가상환경→데이터셋→모델→검증의 출처와 결과 조회 API."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import PurePosixPath
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Camera, Run
from backend.app.catalog_models import CatalogFile, CatalogLog, CatalogParent, CatalogRecord

router = APIRouter(prefix="/catalog", tags=["project-data"])
Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
Kind = Literal["cctv_info", "calibration", "simulation", "capture", "dataset", "training", "model", "evaluation", "detection", "road_recognition"]


class RecordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: Identifier
    kind: Kind
    title: str = Field(min_length=1, max_length=256)
    owner: str = Field(min_length=1, max_length=128)
    data_origin: Literal["real", "synthetic", "mixed", "unspecified"]
    status: Literal["draft", "running", "completed", "failed"]
    camera_id: str | None = None
    detection_run_id: str | None = None
    parents: list[Identifier] = Field(default_factory=list, max_length=100)
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("details")
    @classmethod
    def finite_json(cls, value):
        try:
            encoded = json.dumps(value, allow_nan=False, ensure_ascii=False)
        except (ValueError, TypeError) as exc:
            raise ValueError("details must be finite JSON") from exc
        if len(encoded.encode("utf-8")) > 524288:
            raise ValueError("details exceeds 512 KiB; register large files separately")
        return value

    @model_validator(mode="after")
    def valid_parents(self):
        if self.record_id in self.parents or len(set(self.parents)) != len(self.parents):
            raise ValueError("parents must be unique and cannot include self")
        return self


class RecordOut(RecordIn):
    created_at: datetime


class RecordPage(BaseModel):
    items: list[RecordOut]
    next_after_id: str | None


class FileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=512)
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    role: str = Field(min_length=1, max_length=64)

    @field_validator("path")
    @classmethod
    def relative_path(cls, value):
        path = PurePosixPath(value)
        if "\\" in value or ":" in value or path.is_absolute() or ".." in path.parts or str(path) != value or value == ".":
            raise ValueError("path must be a normalized relative POSIX path")
        return value


class LogIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stream: str = Field(min_length=1, max_length=128)
    line_no: int = Field(ge=1)
    message: str = Field(max_length=16384)


class FileOut(FileIn):
    id: int


class LogOut(LogIn):
    id: int


class FilePage(BaseModel):
    items: list[FileOut]
    next_after_id: int | None


class LogPage(BaseModel):
    items: list[LogOut]
    next_after_id: int | None


def get_record(db, record_id):
    row = db.get(CatalogRecord, record_id)
    if row is None:
        raise HTTPException(404, "등록된 자료가 없습니다")
    return row


def record_out(db, row):
    parents = list(db.scalars(select(CatalogParent.parent_id).where(
        CatalogParent.record_id == row.record_id).order_by(CatalogParent.parent_id)))
    return {key: getattr(row, key) for key in RecordOut.model_fields if key != "parents"} | {"parents": parents}


def commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "동시 등록 충돌입니다. 같은 내용으로 다시 요청하세요") from exc


@router.post("/records", response_model=RecordOut)
def create_record(payload: RecordIn, db: Session = Depends(get_db)):
    body = payload.model_dump()
    body["parents"] = sorted(body["parents"])
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    old = db.get(CatalogRecord, payload.record_id)
    if old:
        if old.fingerprint != fingerprint:
            raise HTTPException(409, "같은 ID의 내용을 변경할 수 없습니다. 새 버전 ID로 등록하세요")
        return record_out(db, old)
    if payload.camera_id and db.get(Camera, payload.camera_id) is None:
        raise HTTPException(422, "먼저 /cameras에 카메라를 등록하세요")
    if payload.detection_run_id:
        run = db.get(Run, payload.detection_run_id)
        if run is None or payload.camera_id != run.camera_id:
            raise HTTPException(422, "검출 실행과 camera_id가 일치해야 합니다")
    for parent in payload.parents:
        if db.get(CatalogRecord, parent) is None:
            raise HTTPException(422, f"상위 자료를 먼저 등록하세요: {parent}")
    # Parents must exist and edges are immutable: cycles cannot be introduced.
    values = {key: value for key, value in body.items() if key != "parents"}
    row = CatalogRecord(**values, fingerprint=fingerprint)
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "동시 등록 충돌입니다. 다시 요청하세요") from exc
    for parent in payload.parents:
        db.add(CatalogParent(record_id=row.record_id, parent_id=parent))
    commit(db)
    return record_out(db, row)


@router.get("/records", response_model=RecordPage)
def list_records(kind: Kind | None = None, camera_id: str | None = None, owner: str | None = None,
                 data_origin: str | None = None, after_id: str = "",
                 limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    stmt = select(CatalogRecord).where(CatalogRecord.record_id > after_id)
    for name, value in (("kind", kind), ("camera_id", camera_id), ("owner", owner), ("data_origin", data_origin)):
        if value is not None:
            stmt = stmt.where(getattr(CatalogRecord, name) == value)
    rows = db.scalars(stmt.order_by(CatalogRecord.record_id).limit(limit + 1)).all()
    return {"items": [record_out(db, r) for r in rows[:limit]],
            "next_after_id": rows[limit - 1].record_id if len(rows) > limit else None}


@router.get("/records/{record_id}", response_model=RecordOut)
def read_record(record_id: str, db: Session = Depends(get_db)):
    return record_out(db, get_record(db, record_id))


@router.get("/records/{record_id}/lineage")
def lineage(record_id: str, direction: Literal["ancestors", "descendants"] = "ancestors",
            limit: int = Query(200, ge=1, le=1000), db: Session = Depends(get_db)):
    get_record(db, record_id)
    seen, pending, edges = {record_id}, [record_id], []
    truncated = False
    while pending:
        current = pending.pop(0)
        column = CatalogParent.record_id if direction == "ancestors" else CatalogParent.parent_id
        # Bound fanout as well as returned nodes.
        links = db.scalars(select(CatalogParent).where(column == current)
                           .order_by(CatalogParent.record_id, CatalogParent.parent_id).limit(limit + 1)).all()
        if len(links) > limit:
            truncated = True
        for link in links[:limit]:
            target = link.parent_id if direction == "ancestors" else link.record_id
            if target not in seen:
                if len(seen) >= limit:
                    truncated = True
                    continue
                seen.add(target)
                pending.append(target)
            edges.append({"record_id": link.record_id, "parent_id": link.parent_id})
    return {"records": [record_out(db, get_record(db, key)) for key in sorted(seen)],
            "edges": edges, "truncated": truncated}


def append_rows(db, record_id, payload, model, keys):
    get_record(db, record_id)
    saved = ignored = 0
    for item in payload:
        stmt = select(model).where(model.record_id == record_id)
        for key in keys:
            stmt = stmt.where(getattr(model, key) == getattr(item, key))
        old = db.scalar(stmt)
        values = item.model_dump()
        if old:
            if any(getattr(old, key) != value for key, value in values.items()):
                raise HTTPException(409, "동일 파일/로그 식별자의 내용이 다릅니다. 새 버전으로 등록하세요")
            ignored += 1
        else:
            db.add(model(record_id=record_id, **values))
            try:
                db.flush()
            except IntegrityError as exc:
                db.rollback()
                raise HTTPException(409, "동시 등록 충돌입니다. 다시 요청하세요") from exc
            saved += 1
    commit(db)
    return {"saved": saved, "ignored": ignored}


@router.post("/records/{record_id}/files")
def register_files(record_id: str, payload: Annotated[list[FileIn], Field(max_length=500)], db: Session = Depends(get_db)):
    return append_rows(db, record_id, payload, CatalogFile, ("path",))


@router.post("/records/{record_id}/logs")
def register_logs(record_id: str, payload: Annotated[list[LogIn], Field(max_length=500)], db: Session = Depends(get_db)):
    return append_rows(db, record_id, payload, CatalogLog, ("stream", "line_no"))


def page_rows(db, record_id, model, schema, after_id, limit, stream=None):
    get_record(db, record_id)
    stmt = select(model).where(model.record_id == record_id, model.id > after_id)
    if stream is not None:
        stmt = stmt.where(model.stream == stream)
    rows = db.scalars(stmt.order_by(model.id).limit(limit + 1)).all()
    return {"items": [{key: getattr(row, key) for key in schema.model_fields} for row in rows[:limit]],
            "next_after_id": rows[limit - 1].id if len(rows) > limit else None}


@router.get("/records/{record_id}/files", response_model=FilePage)
def list_files(record_id: str, after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    return page_rows(db, record_id, CatalogFile, FileOut, after_id, limit)


@router.get("/records/{record_id}/logs", response_model=LogPage)
def list_logs(record_id: str, after_id: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
              stream: str | None = None, db: Session = Depends(get_db)):
    return page_rows(db, record_id, CatalogLog, LogOut, after_id, limit, stream)
