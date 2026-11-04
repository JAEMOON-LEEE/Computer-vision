"""Read-only catalog playback. Never promote archived experiments to live events."""
import json
import math
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from backend.app.catalog_models import CatalogLog, CatalogRecord
from backend.app.db import get_db
from backend.app.models import Camera

router = APIRouter(prefix="/database/saved-results", tags=["database"])


@router.get("")
def list_results(db: Session = Depends(get_db)):
    source = case((CatalogLog.stream.like("ground_truth.jsonl%"), "ground_truth"), else_="detections")
    counts = (select(CatalogLog.record_id, source.label("source"), func.count().label("frames"))
              .where(or_(CatalogLog.stream.like("detections.jsonl%"), CatalogLog.stream.like("ground_truth.jsonl%")))
              .group_by(CatalogLog.record_id, source).subquery())
    rows = db.execute(select(CatalogRecord, counts.c.frames, counts.c.source).join(
        counts, counts.c.record_id == CatalogRecord.record_id)
        .order_by(CatalogRecord.created_at.desc(), CatalogRecord.record_id)).all()
    return [{"record_id": r.record_id, "title": r.title, "kind": r.kind,
             "origin": r.data_origin, "status": r.status, "created_at": r.created_at,
             "source": source, "frames": count, "summary": r.details} for r, count, source in rows]


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@router.get("/frame")
def saved_frame(record_id: str, offset: int = Query(0, ge=0), db: Session = Depends(get_db),
                source: Literal["detections", "ground_truth"] = "detections"):
    if not db.get(CatalogRecord, record_id):
        raise HTTPException(404, "저장 결과를 찾을 수 없습니다")
    log = db.scalar(select(CatalogLog).where(
        CatalogLog.record_id == record_id, CatalogLog.stream.like(source + ".jsonl%"))
        .order_by(CatalogLog.stream, CatalogLog.line_no, CatalogLog.id).offset(offset).limit(1))
    if log is None:
        raise HTTPException(404, "저장된 프레임이 없습니다")
    try:
        frame = json.loads(log.message)
        objects_key = "objects" if source == "ground_truth" else "detections"
        if not isinstance(frame, dict) or not isinstance(frame.get(objects_key), list):
            raise ValueError()
        if not all(finite(frame.get(k)) and 0 < frame[k] <= 32768 for k in ("width", "height")):
            raise ValueError()
        clean = []
        for detection in frame[objects_key]:
            if not isinstance(detection, dict):
                continue
            box = detection.get("bbox_xyxy")
            if not isinstance(box, list) or len(box) != 4 or not all(finite(v) for v in box):
                continue
            if box[2] < box[0] or box[3] < box[1]:
                continue
            world = detection.get("ground_point_world") if source == "ground_truth" else None
            world_xz = [world[0], world[2]] if isinstance(world, list) and len(world) == 3 and all(finite(v) for v in world) else None
            clean.append({"world_xz": world_xz, "class_name": str(detection.get("class_name", "unknown")),
                          "bbox_xyxy": box, "confidence": detection.get("confidence") if finite(detection.get("confidence")) else None})
    except (ValueError, TypeError):
        raise HTTPException(422, "이 프레임은 지원하지 않는 로그 형식입니다. 다음 프레임을 선택하세요")
    camera_id = frame.get("camera_id")
    camera = db.get(Camera, camera_id) if isinstance(camera_id, str) else None
    location = None
    if camera and finite(camera.lat) and finite(camera.lon) and abs(camera.lat) < 85 and abs(camera.lon) <= 180:
        location = {"lat": camera.lat, "lon": camera.lon}
    return {"source": source, "stream": log.stream, "line_no": log.line_no, "camera_id": camera_id,
            "frame": frame.get("frame"), "timestamp": frame.get("timestamp") if finite(frame.get("timestamp")) else None,
            "width": frame["width"], "height": frame["height"], "detections": clean,
            "camera_location": location,
            "map_notice": "검출 객체의 지리 좌표가 없습니다. 영상 좌표를 표시합니다. 실제 지도 배치에는 카메라 보정 정보가 필요합니다."}
