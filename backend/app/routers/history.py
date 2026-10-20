"""실행별 검출 이력과 지도 표시. 좌표계가 확인된 실행만 위경도로 변환한다."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db import get_db
from backend.app.models import Alert, Detection, DetectionCoordinates, Frame, MapReference, Run
from backend.app.schemas import AlertOut, DetectionOut, to_alert_out, to_detection_out

router = APIRouter(prefix="/runs", tags=["history-map"])


class ReferenceIn(BaseModel):
    coordinate_system: Literal["local_enu"]
    units: Literal["m"]
    origin_lat: float = Field(gt=-85, lt=85, allow_inf_nan=False)
    origin_lon: float = Field(ge=-180, le=180, allow_inf_nan=False)


class RunOut(BaseModel):
    run_id: str
    camera_id: str
    timestamp_kind: str | None
    started_at: datetime


class RunPage(BaseModel):
    items: list[RunOut]
    next_offset: int | None


class HistoricalDetection(DetectionOut):
    mapped_xz_raw: list[float] | None
    mapped_xz_corrected: list[float] | None
    coordinate_provenance: Literal["preserved", "legacy_preferred_only"]


class HistoricalFrame(BaseModel):
    camera_id: str
    run_id: str
    frame: int
    timestamp: float
    timestamp_kind: str
    received_at: datetime
    width: int
    height: int
    detections: list[HistoricalDetection]


class FramePage(BaseModel):
    items: list[HistoricalFrame]
    next_after_frame: int | None


class Location(BaseModel):
    xz: list[float] | None
    latlon: list[float] | None


class TrackPoint(Location):
    frame: int
    timestamp: float


class UntrackedPoint(TrackPoint):
    class_name: str


class TrackOut(BaseModel):
    model_id: str
    track_id: int
    class_name: str
    points: list[TrackPoint]


class RiskOut(BaseModel):
    alert: AlertOut
    locations: list[Location]
    location_basis: Literal["same_run_frame_model_track", "unlocated"]


class MapSnapshot(BaseModel):
    run_id: str
    camera_id: str
    timestamp_kind: str | None
    reference: ReferenceIn | None
    tracks: list[TrackOut]
    untracked: list[UntrackedPoint]
    risks: list[RiskOut]
    unmapped_detections: int
    frames_truncated: bool
    alerts_truncated: bool
    first_frame: int | None
    last_frame: int | None


def get_run(db: Session, run_id: str) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, "실행을 찾을 수 없습니다")
    return run


def reference_out(row: MapReference | None):
    if row is None:
        return None
    return {"coordinate_system": "local_enu", "units": "m",
            "origin_lat": row.origin_lat, "origin_lon": row.origin_lon}


def to_latlon(xz, reference: MapReference | None):
    """mapping.calibration.latlon_to_local_xz의 역변환. 근거리만 허용한다."""
    if reference is None or xz is None or math.hypot(*xz) > 5000:
        return None
    lat0 = math.radians(reference.origin_lat)
    e2 = (1 / 298.257223563) * (2 - 1 / 298.257223563)
    denom = 1 - e2 * math.sin(lat0) ** 2
    meridian = 6378137.0 * (1 - e2) / denom ** 1.5
    prime = 6378137.0 / math.sqrt(denom)
    lat = reference.origin_lat + math.degrees(xz[1] / meridian)
    lon = reference.origin_lon + math.degrees(xz[0] / (prime * math.cos(lat0)))
    return [lat, (lon + 180) % 360 - 180]


@router.get("", response_model=RunPage)
def list_runs(camera_id: str | None = None, offset: int = Query(0, ge=0),
              limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    stmt = select(Run)
    if camera_id is not None:
        stmt = stmt.where(Run.camera_id == camera_id)
    rows = db.scalars(stmt.order_by(Run.started_at.desc(), Run.run_id).offset(offset).limit(limit + 1)).all()
    return {"items": [{"run_id": r.run_id, "camera_id": r.camera_id,
                       "timestamp_kind": r.timestamp_kind, "started_at": r.started_at} for r in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None}


@router.put("/{run_id}/map-reference", response_model=ReferenceIn)
def set_reference(run_id: str, payload: ReferenceIn, db: Session = Depends(get_db)):
    get_run(db, run_id)
    old = db.get(MapReference, run_id)
    if old is not None:
        if old.origin_lat != payload.origin_lat or old.origin_lon != payload.origin_lon:
            raise HTTPException(409, "지도 기준은 변경할 수 없습니다. 새 run_id로 수집하세요")
        return reference_out(old)
    row = MapReference(run_id=run_id, origin_lat=payload.origin_lat, origin_lon=payload.origin_lon)
    db.add(row)
    db.commit()
    return reference_out(row)


def frame_records(db: Session, run: Run, frames: list[Frame]):
    by_frame = {f.id: [] for f in frames}
    if frames:
        rows = db.execute(select(Detection, DetectionCoordinates).outerjoin(
            DetectionCoordinates, DetectionCoordinates.detection_id == Detection.id
        ).where(Detection.frame_id.in_(by_frame)).order_by(Detection.id)).all()
        for detection, source in rows:
            body = to_detection_out(detection).model_dump()
            body.update({"mapped_xz_raw": source.raw_xz if source else None,
                         "mapped_xz_corrected": source.corrected_xz if source else None,
                         "coordinate_provenance": "preserved" if source else "legacy_preferred_only"})
            by_frame[detection.frame_id].append(body)
    return [{"camera_id": run.camera_id, "run_id": run.run_id, "frame": f.frame_no,
             "timestamp": f.timestamp, "timestamp_kind": f.timestamp_kind,
             "received_at": f.received_at, "width": f.width, "height": f.height,
             "detections": by_frame[f.id]} for f in frames]


@router.get("/{run_id}/frames", response_model=FramePage)
def frame_history(run_id: str, after_frame: int = Query(-1, ge=-1),
                  limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    frames = db.scalars(select(Frame).where(Frame.run_id == run_id, Frame.frame_no > after_frame)
                        .order_by(Frame.frame_no).limit(limit + 1)).all()
    return {"items": frame_records(db, run, frames[:limit]),
            "next_after_frame": frames[limit - 1].frame_no if len(frames) > limit else None}


@router.get("/{run_id}/map", response_model=MapSnapshot)
def map_snapshot(run_id: str, frame_limit: int = Query(200, ge=1, le=1000),
                 alert_limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)):
    run = get_run(db, run_id)
    reference = db.get(MapReference, run_id)
    frames = db.scalars(select(Frame).where(Frame.run_id == run_id)
                        .order_by(Frame.frame_no.desc()).limit(frame_limit + 1)).all()
    records = frame_records(db, run, list(reversed(frames[:frame_limit])))
    # Null track IDs are points, never one merged path. Model namespaces stay separate.
    tracks, untracked = {}, []
    unmapped = 0
    for frame in records:
        for detection in frame["detections"]:
            xz = detection["mapped_xz"]
            point = {"frame": frame["frame"], "timestamp": frame["timestamp"],
                     "xz": xz, "latlon": to_latlon(xz, reference)}
            unmapped += xz is None
            if detection["track_id"] is None:
                if xz is not None:
                    untracked.append({**point, "class_name": detection["class_name"]})
                continue
            key = (detection["model_id"], detection["track_id"])
            track = tracks.setdefault(key, {"model_id": key[0], "track_id": key[1],
                                           "class_name": detection["class_name"], "points": []})
            track["points"].append(point)
    alerts = db.scalars(select(Alert).where(Alert.run_id == run_id, Alert.camera_id == run.camera_id)
                        .order_by(Alert.timestamp.desc(), Alert.id.desc()).limit(alert_limit + 1)).all()
    # Fetch evidence frames independently: old alerts must not borrow current object positions.
    evidence_frames = db.scalars(select(Frame).where(
        Frame.run_id == run_id, Frame.frame_no.in_([a.frame_no for a in alerts[:alert_limit]])
    )).all()
    evidence_by_frame = {f["frame"]: f["detections"] for f in frame_records(db, run, evidence_frames)}
    risks = []
    for alert in alerts[:alert_limit]:
        locations = []
        for evidence in alert.evidence or []:
            # Missing track/model identifiers cannot establish a reliable correspondence.
            if evidence.get("track_id") is None or evidence.get("model_id") is None:
                continue
            matches = [d for d in evidence_by_frame.get(alert.frame_no, [])
                       if d["track_id"] == evidence["track_id"] and d["model_id"] == evidence["model_id"]
                       and (evidence.get("class_name") is None or d["class_name"] == evidence["class_name"])]
            if len(matches) == 1 and matches[0]["mapped_xz"] is not None:
                xz = matches[0]["mapped_xz"]
                point = {"xz": xz, "latlon": to_latlon(xz, reference)}
                if point not in locations:
                    locations.append(point)
        risks.append({"alert": to_alert_out(alert).model_dump(), "locations": locations,
                      "location_basis": "same_run_frame_model_track" if locations else "unlocated"})
    return {"run_id": run_id, "camera_id": run.camera_id, "timestamp_kind": run.timestamp_kind,
            "reference": reference_out(reference), "tracks": list(tracks.values()),
            "untracked": untracked, "risks": risks, "unmapped_detections": unmapped,
            "frames_truncated": len(frames) > frame_limit, "alerts_truncated": len(alerts) > alert_limit,
            "first_frame": records[0]["frame"] if records else None,
            "last_frame": records[-1]["frame"] if records else None}
