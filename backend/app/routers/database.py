"""Authenticated dashboard data management; table names come only from ORM metadata."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import String, cast, func, literal, or_, select, union_all
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Base, Camera, MapReference, Run

router = APIRouter(prefix="/database", tags=["database"])
LABELS = {
    "cameras": "CCTV", "runs": "분석 실행", "frames": "프레임",
    "detections": "검출 객체", "detection_coordinates": "객체 좌표",
    "map_references": "지도 기준점", "alerts": "위험 경고", "alert_history": "경고 처리 이력",
    "catalog_records": "산출물", "catalog_files": "산출물 파일",
    "catalog_logs": "산출물 로그", "catalog_parents": "산출물 관계",
}


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    queries = [select(literal(name).label("name"), literal(label).label("label"),
                      func.count().label("count")).select_from(Base.metadata.tables[name])
               for name, label in LABELS.items()]
    counts = [dict(row) for row in db.execute(union_all(*queries)).mappings()]
    engine = db.get_bind()
    return {"connected": True, "engine": engine.dialect.name,
            "schema": engine.get_execution_options().get("schema_translate_map", {}).get(None),
            "tables": counts}


@router.get("/tables/{name}")
def rows(name: str, q: str = Query("", max_length=200),
         limit: int = Query(25, ge=1, le=100), offset: int = Query(0, ge=0),
         db: Session = Depends(get_db)):
    if name not in LABELS:
        raise HTTPException(404, "조회할 수 없는 테이블입니다")
    table = Base.metadata.tables[name]
    stmt = select(table)
    if q.strip():
        # Literal substring search across IDs, not caller-provided SQL/column names.
        keys = [c for c in table.columns if c.primary_key or c.name.endswith("_id")]
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(or_(*(cast(c, String).ilike("%" + escaped + "%", escape="\\") for c in keys)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    result = db.execute(stmt.order_by(*(c.desc() for c in table.primary_key.columns))
                        .limit(limit).offset(offset)).mappings().all()
    return {"columns": [c.name for c in table.columns], "items": [dict(r) for r in result],
            "total": total, "limit": limit, "offset": offset}


class CameraMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    name: str = Field(min_length=1, max_length=256)
    lat: float | None = Field(None, ge=-90, le=90, allow_inf_nan=False)
    lon: float | None = Field(None, ge=-180, le=180, allow_inf_nan=False)
    status: str = Field("unknown", min_length=1, max_length=32)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if (self.lat is None) != (self.lon is None):
            raise ValueError("위도와 경도는 함께 입력하거나 모두 비워주세요")
        return self


@router.post("/cameras", status_code=201)
def create_camera(payload: CameraMetadata, db: Session = Depends(get_db)):
    if db.get(Camera, payload.camera_id):
        raise HTTPException(409, "이미 등록된 CCTV ID입니다. 목록에서 수정하세요")
    row = Camera(**payload.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "이미 등록된 CCTV ID입니다")
    return {"camera_id": row.camera_id}


@router.put("/cameras/{camera_id}")
def update_camera(camera_id: str, payload: CameraMetadata, db: Session = Depends(get_db)):
    if camera_id != payload.camera_id:
        raise HTTPException(422, "CCTV ID는 변경할 수 없습니다")
    row = db.get(Camera, camera_id)
    if not row:
        raise HTTPException(404, "CCTV를 찾을 수 없습니다")
    for key, value in payload.model_dump(exclude={"camera_id"}).items():
        setattr(row, key, value)
    db.commit()
    return {"camera_id": row.camera_id}


class ReferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(min_length=1, max_length=128)
    origin_lat: float = Field(gt=-85, lt=85, allow_inf_nan=False)
    origin_lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


@router.get("/map-reference", response_model=ReferenceIn | None)
def get_reference(run_id: str, db: Session = Depends(get_db)):
    row = db.get(MapReference, run_id)
    if row is None:
        return None
    return ReferenceIn(run_id=row.run_id, origin_lat=row.origin_lat, origin_lon=row.origin_lon)


@router.post("/map-references", status_code=201)
def create_reference(payload: ReferenceIn, db: Session = Depends(get_db)):
    if not db.get(Run, payload.run_id):
        raise HTTPException(404, "먼저 검출 수집으로 분석 실행을 등록하세요")
    if db.get(MapReference, payload.run_id):
        raise HTTPException(409, "이미 기준점이 있습니다. 새 분석 실행에 등록하세요")
    db.add(MapReference(**payload.model_dump()))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "기준점이 이미 등록되었거나 실행이 변경되었습니다")
    return payload
