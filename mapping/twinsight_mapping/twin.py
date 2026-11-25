"""실제 CCTV 인식 결과(차량 검출·차선)를 도로 기준 좌표로 바꿔 가상환경(디지털 트윈)에 옮긴다.

검출 박스 → (캘리브레이션 Homography + 박스 아래 가운데 편향 보정) 실제 노면 좌표(m)
         → 도로 중앙선 기준 좌표: along(카메라에서 도로 앞쪽으로 잰 거리, m), lateral(중앙선 오른쪽 +, m)
Unity(City Lab)는 VirtualCCTV 위치를 기준으로 X = 카메라 X + along / 1단위, Z = 중앙선 Z - lateral / 1단위로 놓는다.
도로 중앙선은 road_relative_pose.py가 만든 <카메라ID>.road_pose.json의 road_line(위도·경도 두 점)이다.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .calibration import latlon_to_local_xz
from .correction import DEFAULT_DIMENSIONS, correct_bottom_center, touches_border

VEHICLES = {"car", "truck", "bus", "motorcycle", "bicycle"}


@dataclass
class RoadAxes:
    """캘리브레이션 노면 좌표(m) 위의 도로 중앙선 좌표계."""

    start: np.ndarray     # 중앙선 첫 점
    forward: np.ndarray   # 도로 앞쪽(카메라가 보는 쪽) 단위벡터
    right: np.ndarray     # 앞쪽을 볼 때 오른쪽

    @classmethod
    def from_road_pose(cls, road_pose: dict, origin_latlon) -> "RoadAxes":
        """origin_latlon: 캘리브레이션의 노면 좌표 원점(위도·경도)."""
        a, b = (np.asarray(latlon_to_local_xz(p[0], p[1], tuple(origin_latlon)), float) for p in road_pose["road_line"])
        f = (b - a) / np.linalg.norm(b - a)
        return cls(a, f, np.array([f[1], -f[0]]))

    def to_road(self, xz) -> np.ndarray:
        d = np.atleast_2d(np.asarray(xz, float)) - self.start
        return np.c_[d @ self.forward, d @ self.right]


def inside(point, polygon) -> bool:
    """detection/warnings.py와 같은 점-다각형 판정(0~1 이미지 좌표)."""
    x, y = point
    result, previous = False, polygon[-1]
    for current in polygon:
        (ax, ay), (bx, by) = previous, current
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            result = not result
        previous = current
    return result


def detection_to_twin(det: dict, H: np.ndarray, axes: RoadAxes, camera_along: float, image_size,
                      dimensions=None, road_polygon=None) -> dict | None:
    """검출 하나 → 도로 기준 좌표. 차량이 아니거나 노면으로 옮길 수 없으면 None.

    차량은 도로를 따라 움직인다고 보고 진행 방향을 도로 방향으로 두어 편향 보정한다.
    direction: 중앙선 오른쪽 = away(카메라에서 멀어짐), 왼쪽 = toward(다가옴). 우측 통행 기준.
    """
    name = det.get("class_name")
    if name not in VEHICLES:
        return None
    w, h = image_size
    box = det["bbox_xyxy"]
    raw, corrected = correct_bottom_center(H, box, name, axes.forward, dimensions or DEFAULT_DIMENSIONS)
    if not np.all(np.isfinite(corrected)):
        return None
    along, lateral = axes.to_road(corrected)[0]
    raw_along, raw_lateral = axes.to_road(raw)[0]
    pixel = ((box[0] + box[2]) / 2.0, box[3])
    return {
        "id": det.get("track_id"),
        "class_name": name,
        "confidence": float(det.get("confidence", 0.0)),
        "bbox_xyxy": [float(v) for v in box],
        "pixel": [float(pixel[0]), float(pixel[1])],
        "ground_xz": [float(v) for v in corrected],
        "along_m": float(along - camera_along),
        "lateral_m": float(lateral),
        "raw_along_m": float(raw_along - camera_along),
        "raw_lateral_m": float(raw_lateral),
        "direction": "away" if lateral >= 0 else "toward",
        "truncated": bool(touches_border(box, w, h)),
        "in_road": bool(inside((pixel[0] / w, pixel[1] / h), road_polygon)) if road_polygon else None,
    }


def _iou(a, b) -> float:
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def merge_duplicates(objects: list[dict], iou_threshold: float = 0.7) -> list[dict]:
    """같은 차량을 car·truck·bus로 겹쳐 검출한 박스(클래스별 NMS라 남는다)를 신뢰도 높은 하나로 합친다."""
    kept = []
    for obj in sorted(objects, key=lambda o: -o.get("confidence", 0.0)):
        if all(_iou(obj["bbox_xyxy"], k["bbox_xyxy"]) <= iou_threshold for k in kept):
            kept.append(obj)
    return kept


def lanes_to_twin(context: dict, axes: RoadAxes, camera_along: float) -> list[dict]:
    """road-context.json의 차선(자체 도로 좌표)을 중앙선 기준 좌표로 바꾼다."""
    frame = context.get("road_frame")
    if not frame:
        return []
    origin, f = np.asarray(frame["origin_ground"], float), np.asarray(frame["forward_ground"], float)
    r, m = np.array([f[1], -f[0]]), float(frame.get("meters_per_unit", 1.0))
    out = []
    for lane in context.get("lanes", []):
        a0, a1 = lane["along_m"]
        ends = np.array([origin + (a * f + lane["lateral_m"] * r) / m for a in (a0, a1)])
        road = axes.to_road(ends)
        out.append({"color": lane["color"], "kind": lane["kind"],
                    "along_m": [float(road[0, 0] - camera_along), float(road[1, 0] - camera_along)],
                    "lateral_m": [float(road[0, 1]), float(road[1, 1])]})
    return out
