"""노면 기준점으로 CCTV 카메라의 위치·높이·방향·내려다보는 각도·화각을 구한다.

입력은 캘리브레이션과 같은 노면 기준점(픽셀 ↔ 노면 좌표 x 동쪽, z 북쪽)이다.
1. 노면 → 화면 Homography에서 초점거리를 구한다(렌즈 중심은 화면 가운데, 정사각 픽셀, 왜곡 없음 가정).
   H = K [r1 r2 t] 에서 r1 ⟂ r2, |r1| = |r2| 두 조건이 초점거리 하나를 정한다(Zhang 방식).
2. 같은 H를 분해해 회전 R과 위치 t의 초기값을 얻는다.
3. 초점거리·회전·위치를 함께 다듬어 기준점 재투영 오차를 줄인다. 잘못 찍은 점 하나에 끌려가지 않도록
   이상치에 강한 손실(soft L1)을 쓴다.

좌표는 동(x)·북(z)·위(높이)의 오른손 좌표계이고, Unity로 옮길 때는 x→x, 위→y, z→z로 그대로 쓴다.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
from scipy.optimize import least_squares


def intrinsic_matrix(focal: float, image_size: tuple[int, int]) -> np.ndarray:
    w, h = image_size
    return np.array([[focal, 0.0, w / 2.0], [0.0, focal, h / 2.0], [0.0, 0.0, 1.0]])


def focal_from_homography(H_ground_to_image: np.ndarray, image_size: tuple[int, int]) -> float | None:
    """노면 → 화면 Homography에서 초점거리(px)를 구한다. 카메라가 거의 수직으로 내려다보면 None."""
    w, h = image_size
    G = np.array([[1.0, 0.0, -w / 2.0], [0.0, 1.0, -h / 2.0], [0.0, 0.0, 1.0]]) @ np.asarray(H_ground_to_image, float)
    h1, h2 = G[:, 0], G[:, 1]
    # r1·r2 = 0, |r1|² = |r2|² 를 1/f² 에 대한 일차식 a·s + b = 0 으로 놓고 최소제곱으로 푼다
    a = np.array([h1[0] * h2[0] + h1[1] * h2[1], h1[0] ** 2 + h1[1] ** 2 - h2[0] ** 2 - h2[1] ** 2])
    b = np.array([h1[2] * h2[2], h1[2] ** 2 - h2[2] ** 2])
    denom = float(a @ a)
    if denom < 1e-18:
        return None
    s = -float(a @ b) / denom
    return 1.0 / math.sqrt(s) if s > 0 else None


def pose_from_homography(H_ground_to_image: np.ndarray, K: np.ndarray, ground: np.ndarray):
    """H = K [r1 r2 t] 분해. 기준점이 카메라 앞에 오도록 부호를 고른다. 반환: (R, t)"""
    G = np.linalg.inv(K) @ np.asarray(H_ground_to_image, float)
    scale = 1.0 / np.linalg.norm(G[:, 0])
    r1, r2, t = scale * G[:, 0], scale * G[:, 1], scale * G[:, 2]
    R = np.column_stack([r1, r2, np.cross(r1, r2)])
    U, _, Vt = np.linalg.svd(R)
    R = U @ Vt
    depth = (np.c_[ground, np.zeros(len(ground))] @ R.T + t)[:, 2]
    if np.median(depth) < 0:
        R = R @ np.diag([-1.0, -1.0, 1.0])
        t = -t
    return R, t


def _project(params, ground3, image_size):
    f = math.exp(params[0])
    R = cv2.Rodrigues(params[1:4])[0]
    cam = ground3 @ R.T + params[4:7]
    w, h = image_size
    return f * cam[:, :2] / cam[:, 2:3] + np.array([w / 2.0, h / 2.0])


def estimate_camera_pose(pixels, ground, image_size: tuple[int, int], focal: float | None = None,
                         robust_px: float = 2.0) -> dict:
    """기준점(픽셀, 노면 x·z)으로 카메라 자세를 구한다. focal을 주면 초점거리를 고정한다.

    반환: {"focal", "R", "t", "center", "residuals_px", "rmse_px", "focal_fixed"}
    center는 카메라 위치 (동, 북, 높이)이다.
    """
    pixels = np.asarray(pixels, float)
    ground = np.asarray(ground, float)
    if len(pixels) < 4:
        raise ValueError("카메라 자세에는 노면 기준점이 4개 이상 필요합니다(6개 이상 권장)")

    H, _ = cv2.findHomography(ground, pixels, method=0)
    if H is None:
        raise ValueError("기준점으로 Homography를 구하지 못했습니다. 점이 한 직선에 몰려 있지 않은지 확인하세요")
    f0 = focal or focal_from_homography(H, image_size)
    if f0 is None or not np.isfinite(f0):
        f0 = image_size[0] / (2.0 * math.tan(math.radians(30.0)))  # 가로 화각 60°로 시작
    R0, t0 = pose_from_homography(H, intrinsic_matrix(f0, image_size), ground)

    ground3 = np.c_[ground, np.zeros(len(ground))]
    x0 = np.r_[math.log(f0), cv2.Rodrigues(R0)[0].ravel(), t0]

    if focal is None:
        def residuals(p):
            return (_project(p, ground3, image_size) - pixels).ravel()
        result = least_squares(residuals, x0, loss="soft_l1", f_scale=robust_px)
        params = result.x
    else:
        def residuals(p):
            return (_project(np.r_[x0[0], p], ground3, image_size) - pixels).ravel()
        result = least_squares(residuals, x0[1:], loss="soft_l1", f_scale=robust_px)
        params = np.r_[x0[0], result.x]

    R = cv2.Rodrigues(params[1:4])[0]
    t = params[4:7]
    residual = np.linalg.norm(_project(params, ground3, image_size) - pixels, axis=1)
    return {
        "focal": math.exp(params[0]),
        "R": R,
        "t": t,
        "center": -R.T @ t,
        "residuals_px": residual,
        "rmse_px": float(np.sqrt(np.mean(residual ** 2))),
        "focal_fixed": focal is not None,
    }


def describe_pose(pose: dict, image_size: tuple[int, int]) -> dict:
    """카메라 자세를 사람이 읽고 가상 CCTV에 넣을 수 있는 값으로 바꾼다.

    heading: 북(+z)에서 동(+x) 쪽으로 잰 방위각, pitch: 아래로 숙인 각도(양수), roll: 좌우 기울기.
    unity: Unity 카메라의 position, eulerAngles(x=pitch, y=heading, z=roll), fieldOfView(세로 화각).
    """
    R, focal = pose["R"], pose["focal"]
    east, north, up = pose["center"]
    forward, right = R[2], R[0]  # 카메라 앞·오른쪽 축의 (동, 북, 위) 성분
    pitch = math.degrees(math.asin(float(np.clip(-forward[2], -1.0, 1.0))))
    heading = math.degrees(math.atan2(forward[0], forward[1])) % 360.0
    cos_pitch = max(math.cos(math.radians(pitch)), 1e-9)
    roll = math.degrees(math.asin(float(np.clip(right[2] / cos_pitch, -1.0, 1.0))))
    w, h = image_size
    vfov = math.degrees(2.0 * math.atan(h / 2.0 / focal))
    hfov = math.degrees(2.0 * math.atan(w / 2.0 / focal))
    return {
        "position_m": {"x_east": float(east), "z_north": float(north), "height": float(up)},
        "heading_deg": heading,
        "pitch_deg": pitch,
        "roll_deg": roll,
        "vertical_fov_deg": vfov,
        "horizontal_fov_deg": hfov,
        "focal_px": float(focal),
        "image_size": [int(w), int(h)],
        "unity": {
            "position": [float(east), float(up), float(north)],
            "euler_deg": [pitch, heading, roll % 360.0],
            "field_of_view": vfov,
        },
    }


def leave_one_out_spread(pixels, ground, image_size, focal: float | None = None) -> dict | None:
    """점을 하나씩 빼고 다시 구했을 때 값이 얼마나 흔들리는지(표준편차). 점이 6개 미만이면 None."""
    pixels = np.asarray(pixels, float)
    ground = np.asarray(ground, float)
    if len(pixels) < 6:
        return None
    rows = []
    for i in range(len(pixels)):
        keep = np.arange(len(pixels)) != i
        try:
            d = describe_pose(estimate_camera_pose(pixels[keep], ground[keep], image_size, focal), image_size)
        except ValueError:
            continue
        p = d["position_m"]
        heading = d["heading_deg"]
        rows.append([p["x_east"], p["z_north"], p["height"], heading, d["pitch_deg"], d["roll_deg"],
                     d["vertical_fov_deg"]])
    if len(rows) < 3:
        return None
    rows = np.array(rows)
    # 방위각은 0/360 경계를 넘을 수 있어 첫 값 기준으로 펼친 뒤 계산한다
    rows[:, 3] = rows[0, 3] + (rows[:, 3] - rows[0, 3] + 180.0) % 360.0 - 180.0
    std = rows.std(axis=0)
    names = ["x_east", "z_north", "height", "heading_deg", "pitch_deg", "roll_deg", "vertical_fov_deg"]
    return {name: float(v) for name, v in zip(names, std)}


def pose_report(pixels, ground, image_size, *, camera_id: str | None = None, origin_latlon=None,
                meters_per_unit: float = 1.0, focal: float | None = None) -> dict:
    """가상 CCTV 배치에 쓸 카메라 자세 보고서(JSON으로 저장할 dict).

    origin_latlon을 주면(위도·경도로 캘리브레이션한 경우) 카메라의 위도·경도도 넣는다.
    meters_per_unit은 가상환경의 1단위가 몇 m인지다(Unity 값만 이 비율로 나눈다).
    """
    from .calibration import local_xz_to_latlon

    pose = estimate_camera_pose(pixels, ground, image_size, focal)
    report = describe_pose(pose, image_size)
    report["unity"]["position"] = [v / meters_per_unit for v in report["unity"]["position"]]
    report["unity"]["meters_per_unit"] = meters_per_unit
    position = report["position_m"]
    report.update({
        "camera_id": camera_id,
        "origin_latlon": list(origin_latlon) if origin_latlon else None,
        "position_latlon": list(local_xz_to_latlon(position["x_east"], position["z_north"], origin_latlon))
        if origin_latlon else None,
        "points": int(len(pixels)),
        "rmse_px": pose["rmse_px"],
        "residuals_px": [round(float(v), 3) for v in pose["residuals_px"]],
        "focal_fixed": pose["focal_fixed"],
        "leave_one_out_std": leave_one_out_spread(pixels, ground, image_size, focal),
        "assumptions": "렌즈 중심은 화면 가운데, 정사각 픽셀, 렌즈 왜곡 없음, 기준점은 같은 평면(노면) 위",
    })
    return report
