"""입력은 모르는 필드를 버리고, 출력은 대시보드가 바로 쓸 형태로 맞춘다."""

from __future__ import annotations

import math
from datetime import datetime

from backend.app.models import as_utc
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

TimestampKind = Literal["simulation_seconds", "video_seconds", "unix_seconds", "unspecified"]
AlertStatus = Literal["unconfirmed", "confirmed", "dismissed"]
PatchStatus = Literal["confirmed", "dismissed"]


def utc_iso(value: datetime | None) -> str | None:
    """UTC aware datetime을 오프셋이 붙은 ISO8601 문자열로 만든다."""
    if value is None:
        return None
    return as_utc(value).isoformat()


def _finite_number(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{label}는 유한한 숫자여야 합니다")
    return value


class DetectionIn(BaseModel):
    """검출 항목. mapped_xz 계열은 매핑을 거친 뒤에만 붙는다."""

    model_config = ConfigDict(extra="ignore")

    class_name: str
    class_id: int
    category_id: int
    model_id: str
    bbox_xyxy: list[float]
    confidence: float
    track_id: int | None = None
    ground_point_px: list[float]
    mapped_xz: list[float] | None = None
    mapped_xz_corrected: list[float] | None = None

    @field_validator("confidence")
    @classmethod
    def confidence_finite(cls, value: float) -> float:
        return _finite_number(value, "confidence")

    @field_validator("bbox_xyxy")
    @classmethod
    def bbox_shape(cls, value: list[float]) -> list[float]:
        if len(value) != 4 or not all(math.isfinite(item) for item in value):
            raise ValueError("bbox_xyxy는 유한한 숫자 4개여야 합니다")
        return value

    @field_validator("ground_point_px")
    @classmethod
    def ground_shape(cls, value: list[float]) -> list[float]:
        if len(value) != 2 or not all(math.isfinite(item) for item in value):
            raise ValueError("ground_point_px는 유한한 숫자 2개여야 합니다")
        return value

    @field_validator("mapped_xz", "mapped_xz_corrected")
    @classmethod
    def mapped_shape(cls, value: list[float] | None) -> list[float] | None:
        if value is None:
            return None
        if len(value) != 2 or not all(math.isfinite(item) for item in value):
            raise ValueError("노면 좌표는 유한한 숫자 2개여야 합니다")
        return value


class FrameIn(BaseModel):
    """detections.jsonl 한 줄."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "camera_id": "utic-1294",
                "frame": 12,
                "timestamp": 1760688000.4,
                "timestamp_kind": "unix_seconds",
                "width": 720,
                "height": 480,
                "inference_ms": 12.5,
                "image": "frames/000012.jpg",
                "alert_ids": ["utic-1294:1"],
                "detections": [
                    {
                        "class_name": "car",
                        "class_id": 2,
                        "category_id": 1,
                        "model_id": "primary",
                        "bbox_xyxy": [310.0, 340.5, 335.1, 385.0],
                        "confidence": 0.87,
                        "track_id": 15,
                        "ground_point_px": [322.55, 385.0],
                        "mapped_xz": [3.42, 41.87],
                        "mapped_xz_corrected": [3.61, 44.15],
                    }
                ],
            }
        },
    )

    camera_id: str
    frame: int
    timestamp: float
    timestamp_kind: TimestampKind
    width: int
    height: int
    inference_ms: float
    detections: list[DetectionIn] = Field(default_factory=list)
    image: str | None = None
    alert_ids: list[str] | None = None

    @field_validator("timestamp", "inference_ms")
    @classmethod
    def finite_time(cls, value: float) -> float:
        return _finite_number(value, "숫자")

    @field_validator("camera_id")
    @classmethod
    def camera_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("camera_id가 비어 있습니다")
        return value


class EvidenceIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    class_name: str | None = None
    track_id: int | None = None
    model_id: str | None = None
    bbox_xyxy: list[float] | None = None
    confidence: float | None = None


class AlertIn(BaseModel):
    """alerts.jsonl 한 줄. alert_id는 이 실행 안에서만 번호가 유일하다."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "example": {
                "alert_id": "fixed-pothole-warning:1",
                "camera_id": "fixed-pothole-warning",
                "frame": 2,
                "timestamp": 15.491779327392578,
                "type": "road_damage",
                "severity": "warning",
                "status": "unconfirmed",
                "message": "Persistent pothole detected on the road",
                "evidence": [
                    {
                        "class_name": "pothole",
                        "track_id": 1,
                        "model_id": "road",
                        "bbox_xyxy": [516.065, 223.148, 554.186, 262.568],
                        "confidence": 0.595433,
                    }
                ],
                "basis": "visual_detections_and_motion",
            }
        },
    )

    alert_id: str
    camera_id: str
    frame: int
    timestamp: float
    type: str
    severity: str
    status: AlertStatus = "unconfirmed"
    message: str
    evidence: list[EvidenceIn] = Field(default_factory=list)
    basis: str

    @field_validator("timestamp")
    @classmethod
    def finite_timestamp(cls, value: float) -> float:
        return _finite_number(value, "timestamp")

    @field_validator("alert_id", "camera_id")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("비어 있는 값이 있습니다")
        return value


class AlertPatch(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: PatchStatus | None = None
    handled_by: str | None = None


class CameraIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    camera_id: str
    name: str | None = None
    source: str | None = None
    lat: float | None = None
    lon: float | None = None
    stream_url: str | None = None
    stream_fetched_at: datetime | None = None
    image_width: int | None = None
    image_height: int | None = None
    is_ptz: bool | None = None
    status: str | None = None

    @field_validator("camera_id")
    @classmethod
    def camera_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("camera_id가 비어 있습니다")
        return value


class StreamOut(BaseModel):
    camera_id: str
    stream_url: str
    stream_fetched_at: datetime | None = None
    refreshed: bool
    warning: str | None = None

    @field_serializer("stream_fetched_at", when_used="json")
    def _utc_fetched(self, value: datetime | None) -> str | None:
        return utc_iso(value)


class CameraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    camera_id: str
    name: str | None = None
    source: str
    lat: float | None = None
    lon: float | None = None
    stream_url: str | None = None
    stream_fetched_at: datetime | None = None
    image_width: int | None = None
    image_height: int | None = None
    is_ptz: bool
    status: str
    created_at: datetime

    @field_serializer("stream_fetched_at", "created_at", when_used="json")
    def _utc_times(self, value: datetime | None) -> str | None:
        return utc_iso(value)


class DetectionOut(BaseModel):
    class_name: str
    class_id: int
    category_id: int
    model_id: str
    bbox_xyxy: list[float]
    confidence: float
    track_id: int | None = None
    ground_point_px: list[float] | None = None
    mapped_xz: list[float] | None = None


class LatestFrameOut(BaseModel):
    camera_id: str
    run_id: str
    frame: int
    timestamp: float
    timestamp_kind: str
    width: int
    height: int
    image: str | None = None
    inference_ms: float
    detections: list[DetectionOut]


class AlertOut(BaseModel):
    id: int
    run_id: str
    alert_id: str
    camera_id: str
    frame: int
    timestamp: float
    type: str
    severity: str
    status: str
    message: str
    evidence: list[dict[str, Any]]
    basis: str
    created_at: datetime
    updated_at: datetime
    handled_by: str | None = None

    @field_serializer("created_at", "updated_at", when_used="json")
    def _utc_times(self, value: datetime) -> str:
        return utc_iso(value) or as_utc(value).isoformat()


class SavedFrame(BaseModel):
    run_id: str
    camera_id: str
    frame: int


class DetectionHistoryItem(BaseModel):
    """검출 상자 하나. 프레임 필드는 detections.jsonl 한 줄과 같다."""

    camera_id: str
    run_id: str
    frame: int
    timestamp: float
    timestamp_kind: str
    width: int
    height: int
    inference_ms: float
    image: str | None = None
    class_name: str
    class_id: int
    category_id: int
    model_id: str
    bbox_xyxy: list[float]
    confidence: float
    track_id: int | None = None
    ground_point_px: list[float] | None = None
    mapped_xz: list[float] | None = None


class DetectionListOut(BaseModel):
    total: int
    items: list[DetectionHistoryItem]


class ClassCount(BaseModel):
    class_name: str
    count: int


class HourCount(BaseModel):
    hour: str
    count: int


class DetectionStatsOut(BaseModel):
    by_class: list[ClassCount]
    by_hour: list[HourCount]


class IngestDetectionsResult(BaseModel):
    saved: list[SavedFrame]


class IngestAlertsResult(BaseModel):
    saved: list[AlertOut]
    ignored: list[str]


class ImportItsResult(BaseModel):
    imported: int
    camera_ids: list[str]


def preferred_mapped(detection: DetectionIn) -> tuple[float | None, float | None]:
    """보정 좌표가 있으면 그 값을, 없으면 보정 전 좌표를 고른다."""
    pair = detection.mapped_xz_corrected if detection.mapped_xz_corrected is not None else detection.mapped_xz
    if pair is None:
        return None, None
    return float(pair[0]), float(pair[1])


def to_alert_out(row) -> AlertOut:
    return AlertOut(
        id=row.id,
        run_id=row.run_id,
        alert_id=row.alert_id,
        camera_id=row.camera_id,
        frame=row.frame_no,
        timestamp=row.timestamp,
        type=row.type,
        severity=row.severity,
        status=row.status,
        message=row.message,
        evidence=list(row.evidence or []),
        basis=row.basis,
        created_at=row.created_at,
        updated_at=row.updated_at,
        handled_by=row.handled_by,
    )


def to_detection_out(row) -> DetectionOut:
    mapped = None
    if row.mapped_x is not None and row.mapped_z is not None:
        mapped = [row.mapped_x, row.mapped_z]
    ground = None
    if row.ground_px_u is not None and row.ground_px_v is not None:
        ground = [row.ground_px_u, row.ground_px_v]
    return DetectionOut(
        class_name=row.class_name,
        class_id=row.class_id,
        category_id=row.category_id,
        model_id=row.model_id,
        bbox_xyxy=[row.x1, row.y1, row.x2, row.y2],
        confidence=row.confidence,
        track_id=row.track_id,
        ground_point_px=ground,
        mapped_xz=mapped,
    )
