"""검출 프레임과 경고를 받아 저장하고 WebSocket으로 전달한다."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.db import ensure_run, get_db, resolve_run_id
from backend.app.models import Alert, Detection, DetectionCoordinates, Frame, utcnow
from backend.app.schemas import (
    AlertIn,
    AlertOut,
    FrameIn,
    IngestAlertsResult,
    IngestDetectionsResult,
    SavedFrame,
    preferred_mapped,
    to_alert_out,
)
from backend.app.ws_manager import manager

router = APIRouter(prefix="/ingest", tags=["ingest"])
logger = logging.getLogger(__name__)


def as_records(payload: list | object) -> list:
    return payload if isinstance(payload, list) else [payload]


def upsert_frame(db: Session, run_id: str, record: FrameIn) -> None:
    """같은 (run_id, frame_no)가 있으면 프레임과 상자를 통째로 갈아끼운다."""
    frame = db.scalar(select(Frame).where(Frame.run_id == run_id, Frame.frame_no == record.frame))
    now = utcnow()
    if frame is None:
        frame = Frame(
            run_id=run_id,
            frame_no=record.frame,
            timestamp=record.timestamp,
            timestamp_kind=record.timestamp_kind,
            received_at=now,
            width=record.width,
            height=record.height,
            image_path=record.image,
            inference_ms=record.inference_ms,
        )
        db.add(frame)
        db.flush()
    else:
        frame.timestamp = record.timestamp
        frame.timestamp_kind = record.timestamp_kind
        frame.received_at = now
        frame.width = record.width
        frame.height = record.height
        frame.image_path = record.image
        frame.inference_ms = record.inference_ms
        db.execute(delete(Detection).where(Detection.frame_id == frame.id))
        db.flush()

    for detection in record.detections:
        mapped_x, mapped_z = preferred_mapped(detection)
        x1, y1, x2, y2 = detection.bbox_xyxy
        row = Detection(
                frame_id=frame.id,
                class_name=detection.class_name,
                class_id=detection.class_id,
                category_id=detection.category_id,
                model_id=detection.model_id,
                track_id=detection.track_id,
                confidence=detection.confidence,
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
                ground_px_u=detection.ground_point_px[0],
                ground_px_v=detection.ground_point_px[1],
                mapped_x=mapped_x,
                mapped_z=mapped_z,
            )
        db.add(row)
        db.flush()
        db.add(DetectionCoordinates(detection_id=row.id, raw_xz=detection.mapped_xz,
                                    corrected_xz=detection.mapped_xz_corrected))
    db.flush()


@router.post("/detections", response_model=IngestDetectionsResult)
async def ingest_detections(
    payload: list[FrameIn] | FrameIn,
    run_id: str | None = None,
    db: Session = Depends(get_db),
):
    """프레임 레코드 하나 또는 배열을 저장한다. run_id가 없으면 '{camera_id}-default'."""
    saved: list[SavedFrame] = []
    events: list[dict] = []
    for record in as_records(payload):
        resolved = resolve_run_id(run_id, record.camera_id)
        ensure_run(db, resolved, record.camera_id, record.timestamp_kind)
        upsert_frame(db, resolved, record)
        saved.append(SavedFrame(run_id=resolved, camera_id=record.camera_id, frame=record.frame))
        events.append(
            {
                "type": "detections",
                "camera_id": record.camera_id,
                "run_id": resolved,
                "frame": record.model_dump(mode="json"),
            }
        )
    db.commit()
    for event in events:
        await manager.broadcast(event)
    return IngestDetectionsResult(saved=saved)


def insert_alert(db: Session, run_id: str, record: AlertIn) -> Alert | None:
    """같은 실행의 같은 alert_id는 무시한다. 다른 실행이면 새로 저장한다."""
    existing = db.scalar(select(Alert).where(Alert.run_id == run_id, Alert.alert_id == record.alert_id))
    if existing is not None:
        return None
    now = utcnow()
    alert = Alert(
        run_id=run_id,
        alert_id=record.alert_id,
        camera_id=record.camera_id,
        frame_no=record.frame,
        timestamp=record.timestamp,
        type=record.type,
        severity=record.severity,
        status=record.status,
        message=record.message,
        evidence=[item.model_dump() for item in record.evidence],
        basis=record.basis,
        created_at=now,
        updated_at=now,
    )
    try:
        with db.begin_nested():
            db.add(alert)
            db.flush()
    except IntegrityError:
        return None
    return alert


@router.post("/alerts", response_model=IngestAlertsResult)
async def ingest_alerts(
    payload: list[AlertIn] | AlertIn,
    run_id: str | None = None,
    db: Session = Depends(get_db),
):
    """경고 레코드 하나 또는 배열을 저장한다. 같은 실행의 중복 alert_id는 버린다."""
    saved: list[AlertOut] = []
    ignored: list[str] = []
    ignored_runs: list[str] = []
    events: list[dict] = []
    for record in as_records(payload):
        resolved = resolve_run_id(run_id, record.camera_id)
        ensure_run(db, resolved, record.camera_id, None)
        alert = insert_alert(db, resolved, record)
        if alert is None:
            ignored.append(record.alert_id)
            ignored_runs.append(resolved)
            continue
        body = to_alert_out(alert)
        saved.append(body)
        events.append({"type": "alert", "alert": body.model_dump(mode="json")})
    db.commit()
    if ignored:
        labels = ", ".join(dict.fromkeys(ignored_runs))
        logger.warning("run_id=%s 에서 이미 있는 alert_id %s건을 무시했습니다", labels, len(ignored))
    for event in events:
        await manager.broadcast(event)
    return IngestAlertsResult(saved=saved, ignored=ignored)
