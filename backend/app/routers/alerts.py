"""저장된 경고 조회와 확인·기각."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Alert, utcnow
from backend.app.schemas import AlertOut, AlertPatch, to_alert_out
from backend.app.ws_manager import manager

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertOut])
def list_alerts(
    camera_id: str | None = None,
    run_id: str | None = None,
    alert_type: str | None = Query(None, alias="type"),
    status: str | None = None,
    from_ts: float | None = None,
    to_ts: float | None = None,
    limit: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """이벤트 시각(timestamp)이 최근인 경고부터 돌려준다."""
    stmt = select(Alert)
    if camera_id:
        stmt = stmt.where(Alert.camera_id == camera_id)
    if run_id:
        stmt = stmt.where(Alert.run_id == run_id)
    if alert_type:
        stmt = stmt.where(Alert.type == alert_type)
    if status:
        stmt = stmt.where(Alert.status == status)
    if from_ts is not None:
        stmt = stmt.where(Alert.timestamp >= from_ts)
    if to_ts is not None:
        stmt = stmt.where(Alert.timestamp <= to_ts)
    stmt = stmt.order_by(Alert.timestamp.desc(), Alert.id.desc()).limit(limit)
    return [to_alert_out(row) for row in db.scalars(stmt).all()]


@router.patch("/{id}", response_model=AlertOut)
async def patch_alert(id: int, payload: AlertPatch, db: Session = Depends(get_db)):
    """서버가 발급한 정수 id로 상태를 바꾼다. 경로의 id는 입력 alert_id가 아니다."""
    row = db.get(Alert, id)
    if row is None:
        raise HTTPException(status_code=404, detail="경고를 찾을 수 없습니다")
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] is not None:
        row.status = changes["status"]
    if "handled_by" in changes:
        row.handled_by = changes["handled_by"]
    if not changes:
        return to_alert_out(row)
    row.updated_at = utcnow()
    db.commit()
    body = to_alert_out(row)
    await manager.broadcast({"type": "alert_updated", "alert": body.model_dump(mode="json")})
    return body
