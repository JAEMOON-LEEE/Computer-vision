"""Manual media validation API. Never fetch a user-provided video URL."""
from typing import Literal
import math

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator, model_validator

from backend.app.lab_service import service

router = APIRouter(prefix="/lab", tags=["manual-validation"])


@router.get("/health")
def health():
    return {"status": "ok", "service": "manual-validation", "storage": str(service.storage.resolve()), "model_loading": "manual",
            "collision_v2_ready": service.collision_v2_ready(),
            "real_traffic_ready":service.real_traffic_ready(),"real_coco_ready":service.real_coco_ready(),
            "real_incident_ready":service.real_incident_ready()}


class SessionIn(BaseModel):
    model: Literal["day-night", "day", "collision-v2", "real-traffic", "real-coco"] = "day-night"
    simulation_collision_policy: bool = False
    real_incident_scene: bool = False
    source_kind: Literal["image", "video", "screen"]
    source_label: str = Field(default="", max_length=300)
    reference_url: str = Field(default="", max_length=500)
    confidence: float = Field(default=.25, ge=.05, le=.95, allow_inf_nan=False)
    fixed_camera: bool = False
    client_id: str = Field(default="", max_length=64, pattern=r"^[a-zA-Z0-9-]*$")
    sampling_fps: Literal[2, 5, 8] = 5
    sampling_mode: Literal["single", "source_clock_steps", "realtime"] = "realtime"
    crop_percent: list[float] = Field(default_factory=lambda: [0, 0, 100, 100], min_length=4, max_length=4)

    @model_validator(mode="after")
    def valid_simulation_policy(self):
        if self.simulation_collision_policy and (self.model!="collision-v2" or self.source_kind=="image"
                or not self.fixed_camera or self.sampling_fps<5):
            raise ValueError("가상 충돌 판정은 재학습 모델·고정 카메라 연속 영상·초당5/8장으로 사용해 주세요.")
        if self.real_incident_scene and (self.model not in ("real-traffic","real-coco") or self.source_kind=="image"
                or not self.fixed_camera or self.sampling_fps<5 or self.simulation_collision_policy):
            raise ValueError("실제 사고 장면 판정은 실제 영상용 모델·고정 카메라 연속 영상·초당5/8장으로 사용해 주세요.")
        return self

    @field_validator("crop_percent")
    @classmethod
    def valid_crop(cls, values):
        x, y, w, h = values
        if not all(math.isfinite(v) for v in values) or min(x, y) < 0 or min(w, h) <= 0 or x+w > 100 or y+h > 100:
            raise ValueError("분석 영역은 영상 안의 유효한 백분율 사각형이어야 합니다.")
        return values


class FrameIn(BaseModel):
    image_b64: str = Field(min_length=16, max_length=4_200_000)
    timestamp: float = Field(ge=0, le=1e9, allow_inf_nan=False)
    request_id: str = Field(default="", max_length=80)


class ReviewIn(BaseModel):
    expected_case: Literal["unspecified", "normal", "pothole", "debris", "rear_end", "structure_impact"] = "unspecified"
    judgment: Literal["unreviewed", "detected", "missed", "false_alarm", "normal"] = "unreviewed"
    notes: str = Field(default="", max_length=3000)


@router.post("/sessions")
def start(body: SessionIn):
    return service.create(body)


@router.post("/sessions/{session_id}/frames")
def frame(session_id: str, body: FrameIn):
    return service.infer(session_id, body)


@router.post("/sessions/{session_id}/reset")
def reset(session_id: str):
    return service.reset(session_id)


@router.post("/sessions/{session_id}/stop")
def stop(session_id: str):
    return service.stop(session_id)


@router.post("/sessions/{session_id}/report")
def report(session_id: str, body: ReviewIn):
    return service.save_report(session_id, body)
