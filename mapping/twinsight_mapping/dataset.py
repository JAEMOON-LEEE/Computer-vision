"""docs/data_format.md 형식의 내보내기 폴더를 읽는다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class Camera:
    camera_id: str
    width: int
    height: int
    K: np.ndarray  # 3x3 내부 파라미터
    Rt: np.ndarray | None  # 3x4 월드 → 카메라(OpenCV 축)
    position: np.ndarray  # (3,) 월드 좌표

    @property
    def ground_xz(self) -> np.ndarray:
        return self.position[[0, 2]]

    def project(self, world: np.ndarray) -> np.ndarray:
        """(N, 3) 월드 점 → (N, 2) 픽셀. 카메라 뒤의 점은 nan."""
        if self.Rt is None:
            raise ValueError("camera.json에 world_to_camera_cv가 없습니다")
        world = np.atleast_2d(np.asarray(world, dtype=float))
        cam = world @ self.Rt[:, :3].T + self.Rt[:, 3]
        pix = cam @ self.K.T
        with np.errstate(divide="ignore", invalid="ignore"):
            uv = pix[:, :2] / pix[:, 2:3]
        uv[cam[:, 2] <= 1e-9] = np.nan
        return uv


@dataclass
class ControlPoints:
    ids: np.ndarray  # (N,)
    world: np.ndarray  # (N, 3)
    pixel: np.ndarray  # (N, 2), 투영할 수 없으면 nan
    in_frame: np.ndarray  # (N,) bool

    @property
    def ground(self) -> np.ndarray:
        """노면 좌표 (x, z)."""
        return self.world[:, [0, 2]]


@dataclass
class Export:
    root: Path
    camera: Camera
    control_points: ControlPoints
    frames: list[dict]  # ground_truth.jsonl 한 줄씩


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_camera(path: Path) -> Camera:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    K = np.array([[raw["fx"], 0.0, raw["cx"]], [0.0, raw["fy"], raw["cy"]], [0.0, 0.0, 1.0]])
    rt = raw.get("world_to_camera_cv")
    return Camera(
        camera_id=raw["camera_id"],
        width=int(raw["image_width"]),
        height=int(raw["image_height"]),
        K=K,
        Rt=np.array(rt, dtype=float).reshape(3, 4) if rt else None,
        position=np.array(raw["position"], dtype=float),
    )


def load_control_points(path: Path) -> ControlPoints:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    points = raw["points"]
    pixel = np.full((len(points), 2), np.nan)
    for i, p in enumerate(points):
        if len(p.get("pixel") or []) == 2:
            pixel[i] = p["pixel"]
    return ControlPoints(
        ids=np.array([p["id"] for p in points], dtype=int),
        world=np.array([p["world"] for p in points], dtype=float).reshape(-1, 3),
        pixel=pixel,
        in_frame=np.array([bool(p.get("in_frame")) for p in points], dtype=bool),
    )


def load_export(root: str | Path) -> Export:
    root = Path(root)
    gt_path = root / "ground_truth.jsonl"
    return Export(
        root=root,
        camera=load_camera(root / "camera.json"),
        control_points=load_control_points(root / "control_points.json"),
        frames=read_jsonl(gt_path) if gt_path.exists() else [],
    )


def load_detections(path: str | Path) -> dict[int, list[dict]]:
    """detections.jsonl → {frame: [검출, ...]}."""
    return {rec["frame"]: rec.get("detections", []) for rec in read_jsonl(Path(path))}
