"""Unity 없이 같은 형식의 내보내기 폴더를 만드는 간이 시뮬레이터.

Unity 예제 씬(DemoSceneBuilder)과 같은 도로·카메라 배치를 핀홀 카메라로 계산한다.
평가 코드를 시험하거나, 카메라 높이·각도를 바꿨을 때의 경향을 빨리 볼 때 쓴다.
이미지는 만들지 않고 camera.json, control_points.json, ground_truth.jsonl(필요하면 detections.jsonl)만 쓴다.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

LANE_WIDTH = 3.5
ROAD_START_Z, ROAD_END_Z = -20.0, 200.0
VEHICLES = {  # 클래스: (폭, 높이, 길이) m
    "car": (1.8, 1.5, 4.5),
    "truck": (2.5, 3.2, 8.0),
}
POTHOLES = [(1.2, 25.0), (-4.6, 48.0), (5.0, 70.0)]


@dataclass
class SceneConfig:
    camera_id: str = "synthetic-cam-01"
    image_size: tuple[int, int] = (1920, 1080)
    vertical_fov_deg: float = 45.0
    camera_position: tuple[float, float, float] = (8.5, 8.0, -10.0)
    pitch_deg: float = 15.0  # 아래로 숙인 각도
    yaw_deg: float = -8.0  # Unity y축 회전(양수면 오른쪽)
    fps: float = 10.0
    frames: int = 200
    warmup_seconds: float = 15.0
    seed: int = 0
    # 노면 높이 y = road_y + sag * max(0, z - sag_start)^2. sag가 0이면 평평한 도로
    road_y: float = 0.0  # 노면 기준 높이(Unity y). City Lab 도로는 약 0.507
    sag: float = 0.0
    sag_start: float = 40.0
    grid_x: tuple[float, float] = (-6.0, 6.0)
    grid_z: tuple[float, float] = (0.0, 150.0)
    grid_spacing: float = 3.0
    # 가짜 검출: 정답 박스에 흔들림을 주고 일부를 놓친다
    fake_detections: bool = False
    det_jitter_px: float = 2.0
    det_miss_rate: float = 0.05
    det_min_height_px: float = 8.0
    # 차량마다 길이·폭을 이 비율(표준편차)만큼 다르게 한다. 실제 차종별 크기 차이를 흉내 낸다
    size_jitter: float = 0.0
    lanes: list[tuple[float, int]] = field(default_factory=lambda: [
        (0.5 * LANE_WIDTH, +1), (1.5 * LANE_WIDTH, +1), (-0.5 * LANE_WIDTH, -1), (-1.5 * LANE_WIDTH, -1)])


class PinholeCamera:
    """Unity 카메라와 같은 규칙: 오일러 (pitch, yaw, 0), 세로 화각, 픽셀 왼쪽 위 원점."""

    def __init__(self, cfg: SceneConfig):
        w, h = cfg.image_size
        pitch, yaw = math.radians(cfg.pitch_deg), math.radians(cfg.yaw_deg)
        forward = np.array([math.sin(yaw) * math.cos(pitch), -math.sin(pitch), math.cos(yaw) * math.cos(pitch)])
        right = np.array([math.cos(yaw), 0.0, -math.sin(yaw)])
        down = np.cross(right, forward)
        self.R = np.vstack([right, down, forward])  # 월드 → OpenCV 카메라 축
        self.C = np.array(cfg.camera_position, dtype=float)
        self.t = -self.R @ self.C
        f = (h / 2.0) / math.tan(math.radians(cfg.vertical_fov_deg) / 2.0)
        self.K = np.array([[f, 0.0, w / 2.0], [0.0, f, h / 2.0], [0.0, 0.0, 1.0]])
        self.width, self.height = w, h
        self.forward = forward

    def project(self, world: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """(N, 3) → (픽셀 (N, 2), 깊이 (N,))"""
        cam = np.atleast_2d(world) @ self.R.T + self.t
        pix = cam @ self.K.T
        with np.errstate(divide="ignore", invalid="ignore"):
            return pix[:, :2] / pix[:, 2:3], cam[:, 2]

    def in_frame(self, uv: np.ndarray) -> np.ndarray:
        return (uv[:, 0] >= 0) & (uv[:, 0] < self.width) & (uv[:, 1] >= 0) & (uv[:, 1] < self.height)


def road_height(cfg: SceneConfig, z):
    return cfg.road_y + cfg.sag * np.maximum(0.0, np.asarray(z, dtype=float) - cfg.sag_start) ** 2


def _box_corners(x: float, y: float, z: float, size: tuple[float, float, float]) -> np.ndarray:
    w, h, l = size  # 차로 방향(z)으로 놓인 상자, 바닥 중심이 (x, y, z)
    return np.array([[x + sx * w / 2, y + sy * h, z + sz * l / 2]
                     for sx in (-1, 1) for sy in (0, 1) for sz in (-1, 1)])


def _schedule_traffic(cfg: SceneConfig, rng: np.random.Generator, until: float) -> list[dict]:
    """차로마다 같은 속도로 일정 간격 출발하는 차량 목록."""
    vehicles, next_id = [], 1
    for lane_x, direction in cfg.lanes:
        speed = rng.uniform(10.0, 16.0)
        t = 0.0
        while t < until:
            cls = "car" if rng.random() < 0.8 else "truck"
            width, height, length = VEHICLES[cls]
            if cfg.size_jitter > 0:
                width *= float(np.clip(rng.normal(1.0, cfg.size_jitter), 0.7, 1.3))
                length *= float(np.clip(rng.normal(1.0, cfg.size_jitter), 0.7, 1.3))
            vehicles.append({"id": next_id, "class": cls, "x": lane_x, "dir": direction, "speed": speed, "t0": t,
                             "size": (width, height, length)})
            next_id += 1
            # 앞차와 최소 14 m 떨어지도록
            t += max(rng.uniform(2.0, 5.0), 14.0 / speed)
    for i, (x, z) in enumerate(POTHOLES):
        vehicles.append({"id": next_id + i, "class": "pothole", "x": x, "z": z})
    return vehicles


def _object_record(cfg: SceneConfig, cam: PinholeCamera, track_id: int, cls: str,
                   x: float, z: float, size: tuple[float, float, float]) -> dict | None:
    y = float(road_height(cfg, z))
    uv, depth = cam.project(_box_corners(x, y, z, size))
    if (depth <= 1e-3).any():
        return None
    x1, y1 = uv.min(axis=0)
    x2, y2 = uv.max(axis=0)
    if x2 <= 0 or y2 <= 0 or x1 >= cam.width or y1 >= cam.height:
        return None
    box = [float(np.clip(x1, 0, cam.width)), float(np.clip(y1, 0, cam.height)),
           float(np.clip(x2, 0, cam.width)), float(np.clip(y2, 0, cam.height))]
    if box[2] - box[0] < 2 or box[3] - box[1] < 2:
        return None

    ground = np.array([x, y, z])
    gp, gdepth = cam.project(ground)
    return {
        "track_id": track_id,
        "class_name": cls,
        "bbox_xyxy": box,
        "truncated": box != [float(x1), float(y1), float(x2), float(y2)],
        "ground_point_world": ground.tolist(),
        "ground_point_pixel": gp[0].tolist() if gdepth[0] > 0 else [],
        "ground_point_in_frame": bool(gdepth[0] > 0 and cam.in_frame(gp)[0]),
    }


def generate(cfg: SceneConfig, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(cfg.seed)
    cam = PinholeCamera(cfg)
    w, h = cfg.image_size

    camera = {
        "camera_id": cfg.camera_id,
        "scene": "synthetic",
        "image_width": w,
        "image_height": h,
        "vertical_fov_deg": cfg.vertical_fov_deg,
        "capture_fps": cfg.fps,
        "fx": cam.K[0, 0], "fy": cam.K[1, 1], "cx": cam.K[0, 2], "cy": cam.K[1, 2],
        "position": list(cfg.camera_position),
        "rotation_euler_deg": [cfg.pitch_deg, cfg.yaw_deg % 360.0, 0.0],
        "forward": cam.forward.tolist(),
        "world_to_camera_cv": np.hstack([cam.R, cam.t[:, None]]).ravel().tolist(),
        "coordinate_system": "world: Unity meters (x right, y up, z forward); image: pixels, origin top-left",
    }
    (out / "camera.json").write_text(json.dumps(camera, indent=2), encoding="utf-8")

    xs = np.arange(cfg.grid_x[0], cfg.grid_x[1] + 1e-6, cfg.grid_spacing)
    zs = np.arange(cfg.grid_z[0], cfg.grid_z[1] + 1e-6, cfg.grid_spacing)
    world = np.array([[x, float(road_height(cfg, z)), z] for z in zs for x in xs])
    uv, depth = cam.project(world)
    visible = (depth > 0) & cam.in_frame(uv)
    points = [{"id": i, "world": world[i].tolist(), "pixel": uv[i].tolist() if depth[i] > 0 else [],
               "in_frame": bool(visible[i])} for i in range(len(world))]
    (out / "control_points.json").write_text(
        json.dumps({"camera_id": cfg.camera_id, "points": points}, indent=2), encoding="utf-8")

    end_time = cfg.warmup_seconds + cfg.frames / cfg.fps
    traffic = _schedule_traffic(cfg, rng, end_time)
    gt_lines, det_lines = [], []
    for frame in range(cfg.frames):
        t = cfg.warmup_seconds + frame / cfg.fps
        objects = []
        for v in traffic:
            if v["class"] == "pothole":
                rec = _object_record(cfg, cam, v["id"], "pothole", v["x"], v["z"], (0.8, 0.02, 0.6))
            else:
                if t < v["t0"]:
                    continue
                start = ROAD_START_Z + 2 if v["dir"] > 0 else ROAD_END_Z - 2
                z = start + v["dir"] * v["speed"] * (t - v["t0"])
                if not (ROAD_START_Z + 2 <= z <= ROAD_END_Z - 2):
                    continue
                rec = _object_record(cfg, cam, v["id"], v["class"], v["x"], z, v["size"])
            if rec:
                objects.append(rec)

        base = {"camera_id": cfg.camera_id, "frame": frame, "timestamp": round(t, 4), "width": w, "height": h}
        gt_lines.append({**base, "image": "", "objects": objects})
        if cfg.fake_detections:
            det_lines.append({**base, "detections": _fake_detections(cfg, rng, objects)})

    _write_jsonl(out / "ground_truth.jsonl", gt_lines)
    if cfg.fake_detections:
        _write_jsonl(out / "detections.jsonl", det_lines)
    return out


def _fake_detections(cfg: SceneConfig, rng: np.random.Generator, objects: list[dict]) -> list[dict]:
    dets = []
    for obj in objects:
        x1, y1, x2, y2 = obj["bbox_xyxy"]
        if obj["class_name"] not in VEHICLES or y2 - y1 < cfg.det_min_height_px or rng.random() < cfg.det_miss_rate:
            continue
        box = np.array(obj["bbox_xyxy"]) + rng.normal(0.0, cfg.det_jitter_px, 4)
        dets.append({
            "class_name": obj["class_name"],
            "bbox_xyxy": box.round(2).tolist(),
            "confidence": round(float(rng.uniform(0.5, 0.95)), 3),
            "track_id": None,
        })
    return dets


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
