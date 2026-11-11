"""Explicit, immutable experiment/calibration metadata; never infer a camera match."""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.catalog_models import CalibrationVersion, CatalogLog, CatalogRecord, ExperimentBinding
from backend.app.db import get_db

router = APIRouter(prefix="/database", tags=["database"])


class CalibrationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    calibration_id: str = Field(min_length=1, max_length=128)
    camera_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    image_width: int = Field(gt=0, le=32768, strict=True)
    image_height: int = Field(gt=0, le=32768, strict=True)
    coordinate_system: Literal["unity_xz_m", "local_east_north_m"]
    parameters: dict
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("parameters")
    @classmethod
    def valid_parameters(cls, value):
        if len(json.dumps(value, allow_nan=False).encode("utf-8")) > 65536:
            raise ValueError("보정 파라미터는 64KB 이하여야 합니다")
        return value


class BindingIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_id: str = Field(min_length=1, max_length=128)
    stream: str = Field(min_length=1, max_length=128)
    experiment_id: str = Field(min_length=1, max_length=128)
    camera_id: str = Field(min_length=1, max_length=128)
    image_width: int = Field(gt=0, le=32768, strict=True)
    image_height: int = Field(gt=0, le=32768, strict=True)
    calibration_id: str | None = Field(None, min_length=1, max_length=128)


@router.post("/calibrations", status_code=201)
def register_calibration(payload: CalibrationIn, db: Session = Depends(get_db)):
    db.add(CalibrationVersion(**payload.model_dump()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "보정 ID 또는 카메라·버전이 이미 등록되었습니다")
    return {"calibration_id": payload.calibration_id}


@router.post("/experiment-bindings", status_code=201)
def register_binding(payload: BindingIn, db: Session = Depends(get_db)):
    if db.scalar(select(CatalogRecord.record_id).where(CatalogRecord.record_id == payload.experiment_id)) is None:
        raise HTTPException(404, "연결할 실험 산출물을 찾을 수 없습니다")
    if db.get(ExperimentBinding, (payload.record_id, payload.stream)):
        raise HTTPException(409, "이미 연결된 로그입니다. 기존 연결을 덮어쓸 수 없습니다")
    found = False
    for message in db.scalars(select(CatalogLog.message).where(
            CatalogLog.record_id == payload.record_id, CatalogLog.stream == payload.stream)
            .execution_options(yield_per=100)):
        found = True
        try:
            frame = json.loads(message)
            if (not isinstance(frame, dict) or frame.get("camera_id") != payload.camera_id
                    or type(frame.get("width")) is not int or type(frame.get("height")) is not int
                    or frame["width"] != payload.image_width or frame["height"] != payload.image_height):
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(422, "로그의 카메라·해상도가 일치하지 않거나 형식이 잘못되었습니다")
    if not found:
        raise HTTPException(404, "해당 산출물의 로그 스트림을 찾을 수 없습니다")
    if payload.calibration_id:
        c = db.get(CalibrationVersion, payload.calibration_id)
        if c is None or (c.camera_id, c.image_width, c.image_height) != (payload.camera_id, payload.image_width, payload.image_height):
            raise HTTPException(422, "보정 버전의 카메라·해상도가 일치하지 않습니다")
    db.add(ExperimentBinding(**payload.model_dump()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "연결 정보가 중복되거나 검증 중 원본 데이터가 변경되었습니다")
    return payload
