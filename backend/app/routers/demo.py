"""발표 시연 화면(/demo)의 실시간 검출 API. 브라우저의 Unity 화면 프레임만 받는다."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.app.demo_service import real_service, service, twin_service
from backend.app.lab_service import decode_frame

router = APIRouter(prefix="/demo", tags=["presentation-demo"])


class FrameIn(BaseModel):
    image_b64: str = Field(max_length=4_500_000)
    timestamp: float = Field(ge=0, allow_inf_nan=False)
    source: Literal["sim", "real", "twin"] = "sim"   # sim: City Lab 화면, real: 실제 CCTV 영상, twin: 영상 재현(Unity) 화면


@router.get("/status")
def status():
    return {**service.status(), "real": real_service.status(), "twin": twin_service.status()}


@router.post("/reset")
def reset(source: Literal["sim", "real", "twin", "all"] = "all"):
    if source in ("sim", "all"):
        service.reset()
    if source in ("real", "all"):
        real_service.reset()
    if source in ("twin", "all"):
        twin_service.reset()
    return {"status": "reset"}


@router.post("/detect")
def detect(frame: FrameIn):
    image = decode_frame(frame.image_b64)
    try:
        target = {"real": real_service, "twin": twin_service}.get(frame.source, service)
        return target.infer(image, frame.timestamp)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(503, str(exc)) from exc
