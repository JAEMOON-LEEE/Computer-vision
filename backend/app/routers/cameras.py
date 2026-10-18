"""카메라 등록·조회와 ITS 후보 가져오기."""

from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app import config
from backend.app.db import get_db
from backend.app.models import Camera, Detection, Frame, Run, utcnow
from backend.app.schemas import (
    CameraIn,
    CameraOut,
    ImportItsResult,
    LatestFrameOut,
    to_detection_out,
)

router = APIRouter(prefix="/cameras", tags=["cameras"])

_CAMERA_FIELDS = (
    "name",
    "source",
    "lat",
    "lon",
    "stream_url",
    "stream_fetched_at",
    "image_width",
    "image_height",
    "is_ptz",
    "status",
)


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _as_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


def upsert_camera(db: Session, camera_id: str, values: dict) -> Camera:
    """보낸 필드만 갱신한다. 새로 만들 때 빠진 값은 기본값을 쓴다."""
    camera = db.get(Camera, camera_id)
    if camera is None:
        camera = Camera(
            camera_id=camera_id,
            name=values.get("name", camera_id),
            source=values.get("source") or "unknown",
            lat=values.get("lat"),
            lon=values.get("lon"),
            stream_url=values.get("stream_url"),
            stream_fetched_at=values.get("stream_fetched_at"),
            image_width=values.get("image_width"),
            image_height=values.get("image_height"),
            is_ptz=bool(values.get("is_ptz", False)),
            status=values.get("status") or "unknown",
            created_at=utcnow(),
        )
        db.add(camera)
        return camera
    for key, value in values.items():
        if key in _CAMERA_FIELDS:
            setattr(camera, key, value)
    return camera


@router.get("", response_model=list[CameraOut])
def list_cameras(db: Session = Depends(get_db)):
    return db.scalars(select(Camera).order_by(Camera.camera_id)).all()


@router.post("/import-its", response_model=ImportItsResult)
def import_its(db: Session = Depends(get_db)):
    """ITS 교차로 후보를 읽어 카메라를 upsert한다.

    road_type은 임시 스키마에 없어 버린다. stream_fetched_at에는 fetched_at을 넣는다.
    """
    path = config.CANDIDATES_ITS_PATH
    if not path.is_file():
        raise HTTPException(status_code=404, detail="fetch_its_cctv.py를 먼저 실행하세요")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="candidates_its.json을 해석할 수 없습니다") from exc
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail="candidates_its.json은 배열이어야 합니다")

    camera_ids: list[str] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("camera_id"):
            raise HTTPException(status_code=400, detail="candidates 항목에 camera_id가 없습니다")
        try:
            fetched_at = _as_datetime(item.get("fetched_at"))
            lat = _as_float(item.get("lat"))
            lon = _as_float(item.get("lon"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"후보 값 해석 실패: {exc}") from exc
        camera_id = str(item["camera_id"])
        upsert_camera(
            db,
            camera_id,
            {
                "name": item.get("name"),
                "source": item.get("source") or "ITS",
                "lat": lat,
                "lon": lon,
                "stream_url": item.get("stream_url") or None,
                "stream_fetched_at": fetched_at,
            },
        )
        camera_ids.append(camera_id)
    db.commit()
    return ImportItsResult(imported=len(camera_ids), camera_ids=camera_ids)


@router.get("/{camera_id}", response_model=CameraOut)
def get_camera(camera_id: str, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="카메라를 찾을 수 없습니다")
    return camera


@router.post("", response_model=CameraOut)
def upsert_camera_route(payload: CameraIn, db: Session = Depends(get_db)):
    values = payload.model_dump(exclude_unset=True)
    values.pop("camera_id", None)
    camera = upsert_camera(db, payload.camera_id, values)
    db.commit()
    return camera


@router.get("/{camera_id}/detections/latest", response_model=LatestFrameOut)
def latest_detections(camera_id: str, db: Session = Depends(get_db)):
    """대시보드 오버레이용. 서버가 가장 최근에 받은 프레임과 상자를 돌려준다."""
    if db.get(Camera, camera_id) is None:
        raise HTTPException(status_code=404, detail="카메라를 찾을 수 없습니다")
    frame = db.scalar(
        select(Frame)
        .join(Run, Frame.run_id == Run.run_id)
        .where(Run.camera_id == camera_id)
        .order_by(Frame.received_at.desc(), Frame.id.desc())
        .limit(1)
    )
    if frame is None:
        raise HTTPException(status_code=404, detail="해당 카메라의 검출 프레임이 없습니다")
    detections = db.scalars(
        select(Detection).where(Detection.frame_id == frame.id).order_by(Detection.id)
    ).all()
    return LatestFrameOut(
        camera_id=camera_id,
        run_id=frame.run_id,
        frame=frame.frame_no,
        timestamp=frame.timestamp,
        timestamp_kind=frame.timestamp_kind,
        width=frame.width,
        height=frame.height,
        image=frame.image_path,
        inference_ms=frame.inference_ms,
        detections=[to_detection_out(row) for row in detections],
    )
