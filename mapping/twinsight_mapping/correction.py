"""박스 아래 가운데 점의 '카메라 쪽 편향' 보정.

검출 박스의 아래 가장자리는 차체 중심이 아니라 카메라에서 가장 가까운 바닥 모서리에 해당한다.
그래서 박스 아래 가운데를 Homography로 바꾼 점은 실제 차량 중심보다 카메라 쪽에 놓인다.

보정 원리 (지면이 평면이고 카메라가 좌우로 기울지 않았다고 가정)
- 화면의 한 행(v가 같은 줄)은 노면에서 카메라 앞 방향(깊이 방향)에 수직인 직선이다.
  박스 아래 가장자리 행은 가장 가까운 바닥 모서리의 깊이에 해당하므로, 차량 중심은 그보다
  '바닥면이 깊이 방향으로 차지하는 반폭' s 만큼 더 깊다.
    s = (길이/2)·|cos φ| + (폭/2)·|sin φ|     (φ: 차량 진행 방향과 깊이 방향 사이 각)
- 화면의 한 열(u가 같은 줄)은 노면에서 한 점 O를 지나는 직선이다(O = H·[0, 1, 0]).
  박스 가운데 열은 차량 중심을 지나는 열과 거의 같으므로, 차량 중심은 O에서 추정점 쪽으로
  뻗은 직선 위에 있다.
- 따라서 추정점을 O에서 멀어지는 방향으로, 깊이가 s만큼 늘어날 때까지 민다.

차량 진행 방향은 (1) 추적 ID로 구한 이동 방향, (2) 도로 방향, (3) 둘 다 없으면 깊이 방향과 같다고
가정(s = 길이/2)하는 순서로 쓴다.

여기서 '길이'는 차체 길이가 아니라 박스 아래 가장자리를 만드는 **유효 길이**다. 실제 차는 범퍼가 아니라
바퀴가 바닥에 닿아 차체 길이보다 짧게 잡힌다. 가상환경 정답으로 클래스별 유효 길이를 학습해 쓴다
(fit_effective_dimensions, scripts/calibrate_correction.py).
검출기가 같은 차에 프레임마다 다른 클래스를 붙이면 보정 크기도 흔들리므로, 추적 ID별 다수결(TrackClassVoter)로
클래스를 정한다.
"""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict, deque
from pathlib import Path

import numpy as np

from .homography import pixels_to_ground

# 클래스별 대표 바닥면 크기 (길이, 폭) m. 국내 차량 대표값이며 차종마다 다르다.
DEFAULT_DIMENSIONS: dict[str, tuple[float, float]] = {
    "car": (4.6, 1.85),
    "truck": (7.0, 2.5),
    "bus": (11.0, 2.5),
    "motorcycle": (2.1, 0.8),
    "person": (0.5, 0.5),
}


def parse_dimensions(text: str | None) -> dict[str, tuple[float, float]]:
    """'car=4.5x1.8,truck=8x2.5' → 기본값에 덮어쓴 크기표."""
    dims = dict(DEFAULT_DIMENSIONS)
    if not text:
        return dims
    for item in text.split(","):
        name, size = item.split("=")
        length, width = size.lower().split("x")
        dims[name.strip()] = (float(length), float(width))
    return dims


def load_dimensions_file(path: str | Path) -> dict[str, tuple[float, float]]:
    """calibrate_correction.py가 만든 JSON의 클래스별 유효 크기를 기본값에 덮어쓴다."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    dims = dict(DEFAULT_DIMENSIONS)
    for name, size in data["dimensions"].items():
        dims[name] = (float(size[0]), float(size[1]))
    return dims


def bearing_to_vector(bearing_deg: float) -> np.ndarray:
    """방위각(도, +z에서 +x 쪽으로 잰 각. 위도·경도 좌표계면 북쪽 0°, 동쪽 90°) → 노면 단위벡터 (x, z)."""
    rad = math.radians(bearing_deg)
    return np.array([math.sin(rad), math.cos(rad)])


def column_convergence_point(H: np.ndarray) -> np.ndarray | None:
    """화면의 세로줄(u가 같은 픽셀들)이 노면에서 모두 지나는 점 O. 카메라가 수직으로 내려다보면 None."""
    p = np.asarray(H, dtype=float) @ np.array([0.0, 1.0, 0.0])
    if abs(p[2]) < 1e-12:
        return None
    return p[:2] / p[2]


def depth_direction(H: np.ndarray, pixel, origin: np.ndarray, ground: np.ndarray) -> np.ndarray | None:
    """pixel이 놓인 화면 행에 수직인 노면 방향(카메라 앞쪽 = O에서 멀어지는 쪽) 단위벡터."""
    u, v = pixel
    left, right = pixels_to_ground(H, np.array([[u - 1.0, v], [u + 1.0, v]]))
    row = right - left
    norm = np.linalg.norm(row)
    if not np.isfinite(norm) or norm < 1e-12:
        return None
    direction = np.array([-row[1], row[0]]) / norm
    if direction @ (ground - origin) < 0:
        direction = -direction
    return direction


def footprint_support(length: float, width: float, heading: np.ndarray, direction: np.ndarray) -> float:
    """길이×폭 직사각형(진행 방향 heading)이 direction 방향으로 중심에서 뻗은 길이."""
    side = np.array([-heading[1], heading[0]])
    return 0.5 * length * abs(float(heading @ direction)) + 0.5 * width * abs(float(side @ direction))


def correct_bottom_center(H: np.ndarray, bbox_xyxy, class_name: str, heading: np.ndarray | None = None,
                          dimensions: dict[str, tuple[float, float]] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """박스 아래 가운데를 노면 좌표로 바꾸고 편향을 보정한다.

    반환: (보정 전 좌표, 보정 후 좌표). 크기를 모르는 클래스나 보정할 수 없는 경우 둘은 같다.
    """
    x1, _, x2, y2 = bbox_xyxy
    pixel = ((x1 + x2) / 2.0, y2)
    raw = pixels_to_ground(H, np.array([pixel]))[0]
    dims = (dimensions or DEFAULT_DIMENSIONS).get(class_name)
    if dims is None or not np.all(np.isfinite(raw)):
        return raw, raw.copy()

    origin = column_convergence_point(H)
    if origin is None:
        return raw, raw.copy()
    direction = depth_direction(H, pixel, origin, raw)
    if direction is None:
        return raw, raw.copy()

    ray = raw - origin
    depth = float(ray @ direction)
    if depth <= 1e-6:
        return raw, raw.copy()
    support = footprint_support(dims[0], dims[1], direction if heading is None else heading, direction)
    return raw, raw + ray * (support / depth)


def touches_border(bbox_xyxy, width: int, height: int, margin: float = 2.0) -> bool:
    """박스가 화면 가장자리에 닿았는지. 닿은 박스는 잘렸을 수 있어 아래 가장자리 위치를 믿기 어렵다."""
    x1, y1, x2, y2 = bbox_xyxy
    return x1 <= margin or y1 <= margin or x2 >= width - margin or y2 >= height - margin


class TrackHeadings:
    """추적 ID별 최근 위치로 진행 방향을 구한다. 충분히(min_distance m) 움직이기 전에는 None."""

    def __init__(self, min_distance: float = 2.0, history: int = 15):
        self.min_distance = min_distance
        self.history = history
        self._points: dict[object, deque] = {}
        self._heading: dict[object, np.ndarray] = {}

    def update(self, track_id, position) -> np.ndarray | None:
        if track_id is None or not np.all(np.isfinite(position)):
            return self._heading.get(track_id)
        points = self._points.setdefault(track_id, deque(maxlen=self.history))
        points.append(np.asarray(position, dtype=float))
        motion = points[-1] - points[0]
        distance = float(np.linalg.norm(motion))
        if distance >= self.min_distance:
            self._heading[track_id] = motion / distance
        return self._heading.get(track_id)

    def get(self, track_id) -> np.ndarray | None:
        """위치를 기록하지 않고 마지막으로 구한 진행 방향만 돌려준다."""
        return self._heading.get(track_id)


class TrackClassVoter:
    """추적 ID별로 지금까지 받은 클래스를 신뢰도 가중 다수결로 정한다(지난 프레임까지만 쓰므로 실시간에도 쓸 수 있다).
    추적 ID가 없으면 받은 클래스를 그대로 돌려준다."""

    def __init__(self):
        self._votes: dict[object, Counter] = defaultdict(Counter)

    def update(self, track_id, class_name: str | None, confidence: float = 1.0) -> str | None:
        if track_id is None or class_name is None:
            return class_name
        votes = self._votes[track_id]
        votes[class_name] += max(float(confidence), 1e-3)
        return max(votes, key=votes.get)


def required_support(H: np.ndarray, bbox_xyxy, gt_xz) -> tuple[float, np.ndarray] | None:
    """박스 아래 가운데를 정답 위치로 옮기려면 필요한 깊이 방향 반폭 s와, 그때의 깊이 방향.

    보정은 추정점을 O에서 뻗은 직선 방향으로 s / cos(α)만큼 민다(α: 그 직선과 깊이 방향 사이 각).
    정답까지의 변위를 그 직선에 투영해 최소제곱으로 s를 구한다. 계산할 수 없으면 None.
    """
    x1, _, x2, y2 = bbox_xyxy
    pixel = ((x1 + x2) / 2.0, y2)
    raw = pixels_to_ground(H, np.array([pixel]))[0]
    origin = column_convergence_point(H)
    if origin is None or not np.all(np.isfinite(raw)):
        return None
    direction = depth_direction(H, pixel, origin, raw)
    if direction is None:
        return None
    ray = raw - origin
    norm = float(np.linalg.norm(ray))
    if norm < 1e-6 or float(ray @ direction) <= 1e-6:
        return None
    unit = ray / norm
    return float((np.asarray(gt_xz, dtype=float) - raw) @ unit) * float(unit @ direction), direction


def fit_effective_dimensions(samples, base_dimensions: dict[str, tuple[float, float]] | None = None,
                             min_samples: int = 20, min_alignment: float = 0.5) -> dict[str, dict]:
    """클래스별 유효 길이를 구한다. 폭은 기본값으로 두고 길이만 맞춘다.

    samples: (클래스, 필요한 반폭 s, 깊이 방향, 진행 방향 또는 None) 목록.
    s = 길이/2·|h·f| + 폭/2·|h⊥·f| 에서 관측마다 길이를 거꾸로 구하고, 이상치에 강하도록 중앙값을 쓴다.
    차량이 깊이 방향과 거의 수직(|h·f| < min_alignment)이면 길이가 잘 드러나지 않아 뺀다.
    반환: {클래스: {"length", "width", "n", "iqr"}}. 표본이 min_samples보다 적은 클래스는 빠진다.
    """
    base = base_dimensions or DEFAULT_DIMENSIONS
    lengths: dict[str, list[float]] = defaultdict(list)
    for class_name, support, direction, heading in samples:
        if class_name not in base:
            continue
        h = direction if heading is None else np.asarray(heading, dtype=float)
        along = abs(float(h @ direction))
        if along < min_alignment:
            continue
        across = abs(float(np.array([-h[1], h[0]]) @ direction))
        width = base[class_name][1]
        lengths[class_name].append(2.0 * (support - 0.5 * width * across) / along)

    result = {}
    for class_name, values in lengths.items():
        if len(values) < min_samples:
            continue
        q1, median, q3 = np.percentile(values, [25, 50, 75])
        result[class_name] = {
            "length": float(median),
            "width": float(base[class_name][1]),
            "n": len(values),
            "iqr": float(q3 - q1),
        }
    return result
