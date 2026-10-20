"""저장된 검출 조회. 시각 필터는 Unix timestamp와 비교한다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Detection, Frame, Run
from backend.app.schemas import (
    ClassCount,
    DetectionHistoryItem,
    DetectionListOut,
    DetectionStatsOut,
    HourCount,
    to_detection_out,
)

router = APIRouter(tags=["detections"])
KST = timezone(timedelta(hours=9))
KST_SHIFT = 9 * 3600


def parse_bound(value: str | None, label: str) -> float | None:
    if value is None or value == "":
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label}을 ISO8601로 해석할 수 없습니다") from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=400, detail=f"{label}에는 시간대 오프셋이 있어야 합니다")
    return parsed.timestamp()


def apply_filters(stmt, camera_id: str | None, class_names: list[str] | None, start: float | None, end: float | None):
    if camera_id:
        stmt = stmt.where(Run.camera_id == camera_id)
    if class_names:
        stmt = stmt.where(Detection.class_name.in_(class_names))
    if start is not None:
        stmt = stmt.where(Frame.timestamp >= start)
    if end is not None:
        stmt = stmt.where(Frame.timestamp <= end)
    return stmt


def bounds(from_text: str | None, to_text: str | None) -> tuple[float | None, float | None]:
    start = parse_bound(from_text, "from")
    end = parse_bound(to_text, "to")
    if start is not None and end is not None and start > end:
        raise HTTPException(status_code=400, detail="from이 to보다 늦습니다")
    return start, end


def base_query():
    return select(Detection, Frame, Run).join(Frame, Detection.frame_id == Frame.id).join(Run, Frame.run_id == Run.run_id)


def to_item(detection: Detection, frame: Frame, run: Run) -> DetectionHistoryItem:
    box = to_detection_out(detection)
    return DetectionHistoryItem(
        camera_id=run.camera_id,
        run_id=run.run_id,
        frame=frame.frame_no,
        timestamp=frame.timestamp,
        timestamp_kind=frame.timestamp_kind,
        width=frame.width,
        height=frame.height,
        inference_ms=frame.inference_ms,
        image=frame.image_path,
        **box.model_dump(),
    )


def hour_label(bucket: int) -> str:
    start = datetime.fromtimestamp(bucket * 3600 - KST_SHIFT, tz=KST)
    return start.isoformat(timespec="seconds")


@router.get("/detections/stats", response_model=DetectionStatsOut)
def detection_stats(
    camera_id: str | None = None,
    class_name: list[str] | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """같은 필터로 클래스별 개수와 KST 1시간 단위 개수를 돌려준다."""
    start, end = bounds(from_, to)
    joined = (
        select(Detection.class_name, func.count())
        .join(Frame, Detection.frame_id == Frame.id)
        .join(Run, Frame.run_id == Run.run_id)
    )
    class_rows = db.execute(
        apply_filters(joined, camera_id, class_name, start, end)
        .group_by(Detection.class_name)
        .order_by(func.count().desc(), Detection.class_name)
    ).all()
    bucket = cast((Frame.timestamp + KST_SHIFT) / 3600, Integer)
    hour_query = (
        select(bucket, func.count())
        .select_from(Detection)
        .join(Frame, Detection.frame_id == Frame.id)
        .join(Run, Frame.run_id == Run.run_id)
        .where(Frame.timestamp_kind == "unix_seconds")
    )
    hour_rows = db.execute(
        apply_filters(hour_query, camera_id, class_name, start, end).group_by(bucket).order_by(bucket)
    ).all()
    return DetectionStatsOut(
        by_class=[ClassCount(class_name=name, count=count) for name, count in class_rows],
        by_hour=[HourCount(hour=hour_label(int(key)), count=count) for key, count in hour_rows],
    )


@router.get("/detections", response_model=DetectionListOut)
def list_detections(
    camera_id: str | None = None,
    class_name: list[str] | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """검출 상자를 최신 timestamp 순으로 돌려준다. total은 필터에 맞는 전체 개수다."""
    start, end = bounds(from_, to)
    filtered = apply_filters(base_query(), camera_id, class_name, start, end)
    total = db.scalar(select(func.count()).select_from(filtered.order_by(None).subquery())) or 0
    rows = db.execute(
        filtered.order_by(Frame.timestamp.desc(), Detection.id.desc()).limit(limit).offset(offset)
    ).all()
    return DetectionListOut(total=total, items=[to_item(detection, frame, run) for detection, frame, run in rows])
