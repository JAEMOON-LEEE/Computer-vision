"""실제 CCTV용 미터 단위 Homography 캘리브레이션.

화면에서 찍은 점(픽셀)과 그 점의 실제 좌표(미터, 또는 지도에서 읽은 위도·경도)로 Homography를 구하고,
점마다 "그 점을 빼고 구한 Homography로 그 점을 맞혔을 때의 오차"(leave-one-out)를 계산해 잘못 찍은 점을 찾는다.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .homography import fit_homography, pixels_to_ground

# WGS84 타원체
_WGS84_A = 6378137.0
_WGS84_F = 1 / 298.257223563
_WGS84_E2 = _WGS84_F * (2 - _WGS84_F)


def latlon_to_local_xz(lat, lon, origin: tuple[float, float]) -> np.ndarray:
    """위도·경도 → 기준점 기준 지역 평면 좌표 (x 동쪽, z 북쪽, 미터).

    기준점의 곡률 반경으로 펴는 근사라서 기준점에서 수백 m 안에서는 cm 수준까지 맞는다.
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    lat0, lon0 = origin
    sin0 = math.sin(math.radians(lat0))
    meridian = _WGS84_A * (1 - _WGS84_E2) / (1 - _WGS84_E2 * sin0 ** 2) ** 1.5
    prime_vertical = _WGS84_A / math.sqrt(1 - _WGS84_E2 * sin0 ** 2)
    x = np.radians(lon - lon0) * prime_vertical * math.cos(math.radians(lat0))
    z = np.radians(lat - lat0) * meridian
    return np.stack([x, z], axis=-1)


def leave_one_out_errors(pixels: np.ndarray, ground: np.ndarray) -> np.ndarray:
    """점마다 그 점을 빼고 구한 Homography로 그 점을 변환했을 때의 오차(m). 점이 5개 미만이면 nan."""
    pixels = np.asarray(pixels, dtype=float)
    ground = np.asarray(ground, dtype=float)
    errors = np.full(len(pixels), np.nan)
    if len(pixels) < 5:
        return errors
    for i in range(len(pixels)):
        keep = np.arange(len(pixels)) != i
        try:
            H = fit_homography(pixels[keep], ground[keep])
        except ValueError:
            continue
        errors[i] = np.linalg.norm(pixels_to_ground(H, pixels[i:i + 1])[0] - ground[i])
    return errors


def fit_calibration(pixels: np.ndarray, ground: np.ndarray) -> dict:
    """Homography와 점검용 오차를 함께 구한다."""
    H = fit_homography(pixels, ground)
    residuals = np.linalg.norm(pixels_to_ground(H, pixels) - ground, axis=1)
    return {
        "H": H,
        "residuals_m": residuals,
        "fit_rmse_m": float(np.sqrt(np.mean(residuals ** 2))),
        "loo_errors_m": leave_one_out_errors(pixels, ground),
    }


def suspicious_points(loo_errors: np.ndarray, min_error: float = 0.5, ratio: float = 3.0) -> np.ndarray:
    """leave-one-out 오차가 다른 점들보다 유난히 큰(중앙값의 ratio배 이상이고 min_error m 이상) 점의 인덱스."""
    finite = np.isfinite(loo_errors)
    if finite.sum() < 3:
        return np.empty(0, dtype=int)
    median = float(np.median(loo_errors[finite]))
    return np.flatnonzero(finite & (loo_errors >= max(min_error, ratio * median)))


def save_calibration(path: str | Path, *, camera_id: str, image_path: str | Path, image_size: tuple[int, int],
                     point_ids, pixels, ground, result: dict, coordinate_system: str,
                     origin_latlon: tuple[float, float] | None = None, latlon=None,
                     road_heading_deg: float | None = None) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    points = []
    for i, pid in enumerate(point_ids):
        point = {
            "id": int(pid),
            "pixel": [round(float(v), 2) for v in pixels[i]],
            "world_xz": [round(float(v), 4) for v in ground[i]],
            "residual_m": round(float(result["residuals_m"][i]), 4),
            "loo_error_m": None if not np.isfinite(result["loo_errors_m"][i])
            else round(float(result["loo_errors_m"][i]), 4),
        }
        if latlon is not None:
            point["latlon"] = [float(latlon[i][0]), float(latlon[i][1])]
        points.append(point)

    data = {
        "camera_id": camera_id,
        "image": str(image_path),
        "image_size": [int(image_size[0]), int(image_size[1])],
        "units": "m",
        "coordinate_system": coordinate_system,
        "origin_latlon": list(origin_latlon) if origin_latlon else None,
        "road_heading_deg": road_heading_deg,
        "homography_pixel_to_ground": np.asarray(result["H"]).tolist(),
        "fit_rmse_m": round(result["fit_rmse_m"], 4),
        "points": points,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_calibration(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    data["H"] = np.array(data["homography_pixel_to_ground"], dtype=float)
    return data


def birds_eye_view(image: np.ndarray, H: np.ndarray, ground: np.ndarray, *, labels=None,
                   max_size: int = 1200, margin_m: float = 5.0, grid_m: float = 5.0) -> np.ndarray:
    """기준점 주변을 위에서 내려다본 그림. 북쪽(z+)이 위. 기준점은 빨간 원, 격자는 grid_m 간격.

    차선이 평행하고 격자 간격이 고르게 보이면 캘리브레이션이 대체로 맞은 것이다.
    """
    ground = np.asarray(ground, dtype=float)
    x_min, z_min = ground.min(axis=0) - margin_m
    x_max, z_max = ground.max(axis=0) + margin_m
    scale = max_size / max(x_max - x_min, z_max - z_min)  # px / m
    width = int(math.ceil((x_max - x_min) * scale))
    height = int(math.ceil((z_max - z_min) * scale))

    # 노면 (x, z) → 그림 픽셀. 북쪽이 위가 되도록 z를 뒤집는다
    to_canvas = np.array([[scale, 0, -x_min * scale], [0, -scale, z_max * scale], [0, 0, 1]])
    M = to_canvas @ H
    canvas = cv2.warpPerspective(image, M, (width, height))

    # 카메라 뒤쪽(지평선 너머)에 해당하는 부분은 거울상으로 그려지므로 지운다
    xs, ys = np.meshgrid(np.arange(width), np.arange(height))
    inv = np.linalg.inv(M)
    w = inv[2, 0] * xs + inv[2, 1] * ys + inv[2, 2]
    canvas[w <= 0] = 0

    for gx in np.arange(math.ceil(x_min / grid_m) * grid_m, x_max, grid_m):
        u = int(round((gx - x_min) * scale))
        cv2.line(canvas, (u, 0), (u, height - 1), (90, 90, 90), 1)
    for gz in np.arange(math.ceil(z_min / grid_m) * grid_m, z_max, grid_m):
        v = int(round((z_max - gz) * scale))
        cv2.line(canvas, (0, v), (width - 1, v), (90, 90, 90), 1)

    for i, (gx, gz) in enumerate(ground):
        center = (int(round((gx - x_min) * scale)), int(round((z_max - gz) * scale)))
        cv2.circle(canvas, center, 6, (0, 0, 255), 2)
        label = str(labels[i]) if labels is not None else str(i + 1)
        cv2.putText(canvas, label, (center[0] + 8, center[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 0, 255), 2, cv2.LINE_AA)
    cv2.putText(canvas, f"grid {grid_m:g} m, N up", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                (255, 255, 255), 2, cv2.LINE_AA)
    return canvas


def read_image(path: str | Path) -> np.ndarray:
    """한글 경로도 읽히도록 imdecode를 쓴다."""
    data = np.fromfile(str(path), dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"이미지를 읽을 수 없습니다: {path}")
    return image


def write_image(path: str | Path, image: np.ndarray) -> None:
    ok, buffer = cv2.imencode(Path(path).suffix or ".png", image)
    if not ok:
        raise ValueError(f"이미지를 저장할 수 없습니다: {path}")
    buffer.tofile(str(path))
