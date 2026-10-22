"""OpenCV 도로·차선·정지선 인식 → 팀 경고 엔진 형식(road-context.json).

고정 CCTV의 여러 프레임 중앙값(움직이는 차량 제거) → 캘리브레이션으로 노면을 위에서 본 그림 →
흰색(주변보다 밝은 가는 선)·노란색 도색 → 도로 방향 → 세로 선(차선·가장자리선·중앙선)과
가로 표시(정지선·횡단보도) → 도로 영역과 정지 대기 영역.

- 직선 도로 구간을 가정한다. 곡선 도로나 교차로 전체 모양은 아직 다루지 않는다.
- 도로 좌표: along(카메라에서 멀어지는 도로 방향, m), lateral(그 방향을 볼 때 오른쪽 +, m).
- 우측 통행 기준: 중앙선 오른쪽 차로는 카메라에서 멀어지는 방향, 왼쪽 차로는 다가오는 방향이다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy.signal import find_peaks


@dataclass
class GroundPlane:
    """화면 픽셀 ↔ 노면 좌표. meters_per_unit은 노면 좌표 1단위가 몇 m인지(실제 CCTV 1, City Lab 약 2.92)."""

    H_pixel_to_ground: np.ndarray
    image_size: tuple[int, int]
    meters_per_unit: float = 1.0

    @property
    def H_ground_to_pixel(self) -> np.ndarray:
        return np.linalg.inv(self.H_pixel_to_ground)

    @property
    def front_sign(self) -> float:
        """Homography의 배율 부호는 정해져 있지 않으므로, 화면 맨 아래 가운데(확실히 카메라 앞)의 부호를 기준으로 쓴다."""
        w, h = self.image_size
        g = self.to_ground([(w / 2, h - 1)])[0]
        return float(np.sign((self.H_ground_to_pixel @ [g[0], g[1], 1.0])[2]) or 1.0)

    def to_ground(self, uv) -> np.ndarray:
        uv = np.atleast_2d(np.asarray(uv, float))
        p = np.c_[uv, np.ones(len(uv))] @ self.H_pixel_to_ground.T
        return p[:, :2] / p[:, 2:3]

    def to_pixel(self, xz) -> tuple[np.ndarray, np.ndarray]:
        """반환: (픽셀, 카메라 앞인지)"""
        xz = np.atleast_2d(np.asarray(xz, float))
        p = np.c_[xz, np.ones(len(xz))] @ self.H_ground_to_pixel.T
        return p[:, :2] / p[:, 2:3], p[:, 2] * self.front_sign > 0

    @classmethod
    def from_camera(cls, K, Rt, image_size, ground_y: float, meters_per_unit: float = 1.0) -> "GroundPlane":
        """Unity 내보내기 camera.json(K, 월드→카메라 OpenCV 축)과 노면 높이 y로 만든다. 노면 좌표는 월드 (x, z)."""
        K, Rt = np.asarray(K, float), np.asarray(Rt, float)
        R, t = Rt[:, :3], Rt[:, 3]
        H_ground_to_pixel = K @ np.column_stack([R[:, 0], R[:, 2], R[:, 1] * ground_y + t])
        return cls(np.linalg.inv(H_ground_to_pixel), tuple(image_size), meters_per_unit)


@dataclass
class RoadFrame:
    """노면 좌표 위의 도로 정렬 좌표계(m). origin·forward·right는 노면 좌표(단위) 기준."""

    origin: np.ndarray
    forward: np.ndarray
    right: np.ndarray
    meters_per_unit: float

    def to_road(self, xz) -> np.ndarray:
        d = (np.atleast_2d(xz) - self.origin) * self.meters_per_unit
        return np.c_[d @ self.forward, d @ self.right]

    def to_ground(self, al) -> np.ndarray:
        al = np.atleast_2d(np.asarray(al, float))
        return self.origin + (al[:, :1] * self.forward + al[:, 1:2] * self.right) / self.meters_per_unit


@dataclass
class TopView:
    image: np.ndarray            # BGR, 행 = along(위가 먼 쪽), 열 = lateral(오른쪽 +)
    valid: np.ndarray            # 화면 안에 들어오는 칸
    ppm: float
    along_range: tuple[float, float]
    lateral_half: float

    def col(self, lateral):
        return (np.asarray(lateral) + self.lateral_half) * self.ppm

    def row(self, along):
        return (self.along_range[1] - np.asarray(along)) * self.ppm

    def lateral(self, col):
        return np.asarray(col) / self.ppm - self.lateral_half

    def along(self, row):
        return self.along_range[1] - np.asarray(row) / self.ppm


@dataclass
class LaneLine:
    lateral_m: float
    color: str                    # white / yellow
    kind: str                     # solid / dashed / barrier
    coverage: float
    width_m: float
    along_extent_m: tuple[float, float]
    dash_period_m: float | None = None
    dash_length_m: float | None = None


@dataclass
class Transverse:
    kind: str                     # stop_line / crosswalk
    along_m: tuple[float, float]  # (가까운 쪽, 먼 쪽)
    lateral_m: tuple[float, float]


@dataclass
class RoadScene:
    frame: RoadFrame
    top: TopView
    paint: np.ndarray
    yellow: np.ndarray
    lines: list[LaneLine] = field(default_factory=list)
    transverse: list[Transverse] = field(default_factory=list)
    road_lateral: tuple[float, float] | None = None
    road_along: tuple[float, float] | None = None
    centre_lateral: float | None = None
    band: tuple[float, float] | None = None   # 노면 색이 이어지는 가로 범위(m)


def median_background(frames) -> np.ndarray:
    """고정 CCTV 프레임들의 픽셀별 중앙값. 지나가는 차량이 지워진 노면 그림이 된다."""
    stack = np.stack([np.asarray(f) for f in frames])
    return np.median(stack, axis=0).astype(np.uint8)


def _initial_frame(plane: GroundPlane) -> RoadFrame:
    w, h = plane.image_size
    near, mid = plane.to_ground([(w / 2, h - 1), (w / 2, h * 0.55)])
    f = (mid - near) * plane.meters_per_unit
    f = f / np.linalg.norm(f)
    return RoadFrame(near, f, np.array([f[1], -f[0]]), plane.meters_per_unit)


def _rotated(frame: RoadFrame, angle: float) -> RoadFrame:
    """forward를 오른쪽으로 angle(rad)만큼 돌린 좌표계."""
    c, s = math.cos(angle), math.sin(angle)
    f = c * frame.forward + s * frame.right
    return RoadFrame(frame.origin, f, np.array([f[1], -f[0]]), frame.meters_per_unit)


def make_top_view(image, plane: GroundPlane, frame: RoadFrame, ppm: float = 20.0,
                  along_range=(-5.0, 100.0), lateral_half: float = 25.0, ignore=None) -> TopView:
    """ignore: 화면 크기 bool 마스크. 참인 곳(CCTV 화면 글자 등)은 노면 분석에서 뺀다."""
    a0, a1 = along_range
    width, height = int(round(2 * lateral_half * ppm)), int(round((a1 - a0) * ppm))
    # 위에서 본 그림 픽셀 → 도로 좌표(m) → 노면 좌표 → 화면 픽셀
    T_top_to_road = np.array([[0.0, -1.0 / ppm, a1], [1.0 / ppm, 0.0, -lateral_half], [0.0, 0.0, 1.0]])
    m = frame.meters_per_unit
    T_road_to_ground = np.array([[frame.forward[0] / m, frame.right[0] / m, frame.origin[0]],
                                 [frame.forward[1] / m, frame.right[1] / m, frame.origin[1]], [0.0, 0.0, 1.0]])
    H = plane.H_ground_to_pixel @ T_road_to_ground @ T_top_to_road
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    top = cv2.warpPerspective(image, H, (width, height), flags=flags, borderMode=cv2.BORDER_CONSTANT)
    ones = np.full(image.shape[:2], 255, np.uint8)
    if ignore is not None:
        ones[np.asarray(ignore, bool)] = 0
    valid = cv2.warpPerspective(ones, H, (width, height), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP) > 0
    # 카메라 뒤(지평선 너머)로 투영되는 칸은 버린다
    rows, cols = np.mgrid[0:height:8, 0:width:8]
    pts = np.c_[cols.ravel(), rows.ravel(), np.ones(rows.size)] @ H.T
    behind = (pts[:, 2] * plane.front_sign <= 0).reshape(rows.shape)
    if behind.any():
        valid &= ~cv2.resize(behind.astype(np.uint8), (width, height), interpolation=cv2.INTER_NEAREST).astype(bool)
    return TopView(top, valid, ppm, (a0, a1), lateral_half)


def paint_masks(top: TopView, line_width_m: float = 0.15, region=None) -> tuple[np.ndarray, np.ndarray]:
    """흰 도색과 노란 도색 마스크. 둘 다 '주변 노면보다 밝은 가는 부분'(명도 top-hat)이어야 한다.
    노란색은 색만 보면 마른 풀·흙과 겹치므로(금촌 CCTV: 도색 명도 166~246, 마른 풀 62~104) 밝기 조건이 꼭 필요하다.
    region: 기준값(문턱)을 잴 영역. 노면 띠로 주면 건물 벽·보도 무늬 때문에 문턱이 올라가지 않는다."""
    hsv = cv2.cvtColor(top.image, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    k = max(3, int(round(4 * line_width_m * top.ppm)) | 1)
    tophat = cv2.morphologyEx(v, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    values = tophat[top.valid if region is None else (region & top.valid)]
    if values.size == 0:
        z = np.zeros(v.shape, bool)
        return z, z
    med = float(np.median(values))
    mad = float(np.median(np.abs(values - med))) + 1e-6
    thr = max(12.0, med + 8.0 * mad)
    white = (tophat > thr) & (s < 80) & top.valid
    yellow = (h >= 8) & (h <= 32) & (s > 60) & (v > 130) & (tophat > 0.5 * thr) & top.valid
    open_k = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    white = cv2.morphologyEx(white.astype(np.uint8), cv2.MORPH_OPEN, open_k).astype(bool)
    yellow = cv2.morphologyEx(yellow.astype(np.uint8), cv2.MORPH_OPEN, open_k).astype(bool)
    return white | yellow, yellow


def asphalt_mask(top: TopView, seed_lateral=(-10.0, 10.0), seed_along=(3.0, 40.0)) -> np.ndarray:
    """카메라 앞 넓은 범위에서 가장 흔한 저채도 색을 노면 색으로 보고, 같은 노면인 칸을 고른다.
    (화면 아래 가운데만 보면 중앙분리대·도색 위일 수 있어 가장 흔한 색을 쓴다.)
    그늘진 노면은 어두워도 채도·색상이 같으므로 포함하고, 보도(더 밝음)·풀·흙(채도·색상이 다름)은 뺀다.
    금촌 CCTV 노면: 색상 114, 채도 52, 명도 158 / City Lab 노면: 채도 10, 명도 132, 보도 명도 196."""
    hsv = cv2.cvtColor(top.image, cv2.COLOR_BGR2HSV)
    h, s, v = (hsv[..., i].astype(np.int16) for i in range(3))
    r0, r1 = (int(np.clip(top.row(a), 0, top.valid.shape[0])) for a in (seed_along[1], seed_along[0]))
    c0, c1 = (int(np.clip(top.col(l), 0, top.valid.shape[1])) for l in seed_lateral)
    seed = np.zeros_like(top.valid)
    seed[r0:r1, c0:c1] = True
    seed &= top.valid & (s < 90)
    if seed.sum() < 50:
        return (s < 65) & (v > 70) & top.valid
    hist, ve, se = np.histogram2d(v[seed], s[seed], bins=(32, 12), range=((0, 256), (0, 96)))
    iv, is_ = np.unravel_index(np.argmax(cv2.GaussianBlur(hist.astype(np.float32), (3, 3), 0)), hist.shape)
    near = seed & (np.abs(v - (ve[iv] + 4)) <= 12) & (np.abs(s - (se[is_] + 4)) <= 10)
    v0, s0 = float(np.median(v[near])), float(np.median(s[near]))
    # 양방향 차로의 포장 색이 조금씩 다를 수 있어 넉넉히 잡고, 풀·흙·마른 풀 색(주황~초록, 채도 있음)만 뺀다
    earth = (h >= 10) & (h <= 55) & (s > 40)
    return top.valid & (v < v0 + max(40.0, 0.3 * v0)) & (v > 0.4 * v0) & (s < s0 + 30) & ~earth


def road_band(top: TopView, asphalt: np.ndarray, min_fraction: float = 0.4, centre_m: float = 0.0,
              max_gap_m: float = 1.5) -> tuple[float, float] | None:
    """도로 방향으로 노면이 이어지는 가로 범위(m). centre_m(보통 화면 아래 가운데 = 0)을 포함하는 띠를 고른다.
    중앙분리대·차선처럼 좁게 끊긴 곳(max_gap_m 이하)은 이어 붙인다."""
    valid = top.valid.sum(axis=0)
    frac = np.where(valid > 5 * top.ppm, asphalt.sum(axis=0) / np.maximum(valid, 1), 0.0)
    good = cv2.morphologyEx((frac >= min_fraction).astype(np.uint8).reshape(1, -1), cv2.MORPH_CLOSE,
                            np.ones((1, max(1, int(max_gap_m * top.ppm)) | 1), np.uint8)).ravel() > 0
    runs = [(a, b) for a, b in _runs(good) if b - a >= 3 * top.ppm]
    if not runs:
        return None
    c = top.col(centre_m)
    best = min(runs, key=lambda r: 0 if r[0] <= c < r[1] else min(abs(c - r[0]), abs(c - r[1])))
    return float(top.lateral(best[0])), float(top.lateral(best[1] - 1))


def dominant_angle(paint: np.ndarray, ppm: float, max_angle_deg: float = 35.0) -> float | None:
    """위에서 본 그림에서 세로(도로 방향)에 가까운 선분들의 길이 가중 중앙값 각도(rad, 오른쪽으로 기울면 +)."""
    seg = cv2.HoughLinesP(paint.astype(np.uint8) * 255, 1, np.pi / 360, threshold=40,
                          minLineLength=int(4 * ppm), maxLineGap=int(2.5 * ppm))
    if seg is None:
        return None
    angles, weights = [], []
    for x1, y1, x2, y2 in np.asarray(seg).reshape(-1, 4):  # OpenCV 4는 (N,1,4), 5는 (N,4)
        if y2 > y1:
            x1, y1, x2, y2 = x2, y2, x1, y1
        a = math.atan2(x2 - x1, y1 - y2)  # 위(먼 쪽)로 갈수록 오른쪽이면 +
        if abs(math.degrees(a)) <= max_angle_deg:
            angles.append(a); weights.append(math.hypot(x2 - x1, y2 - y1))
    if not angles:
        return None
    order = np.argsort(angles)
    cum = np.cumsum(np.asarray(weights)[order])
    return float(np.asarray(angles)[order][np.searchsorted(cum, cum[-1] / 2)])


def _runs(mask_1d: np.ndarray) -> list[tuple[int, int]]:
    m = np.r_[False, mask_1d.astype(bool), False]
    d = np.flatnonzero(np.diff(m.astype(int)))
    return list(zip(d[::2], d[1::2]))


def find_longitudinal_lines(top: TopView, paint, yellow, min_coverage: float = 0.12, skip_rows=None) -> list[LaneLine]:
    """세로(도로 방향) 선. skip_rows: 횡단보도처럼 세로 줄무늬가 있는 행(bool, 행 수 길이)은 빼고 센다."""
    ppm = top.ppm
    valid = top.valid.copy()
    if skip_rows is not None:
        valid[np.asarray(skip_rows, bool)] = False
    top = TopView(top.image, valid, top.ppm, top.along_range, top.lateral_half)
    valid_rows = top.valid.sum(axis=0).astype(float)
    cov = np.where(valid_rows > ppm * 5, (paint & top.valid).sum(axis=0) / np.maximum(valid_rows, 1), 0.0)
    smooth = cv2.GaussianBlur(cov.reshape(1, -1).astype(np.float32), (0, 0), sigmaX=max(1.0, 0.08 * ppm)).ravel()
    peaks, props = find_peaks(smooth, height=min_coverage * 0.6, distance=int(0.8 * ppm), prominence=0.04)
    lines = []
    for p in peaks:
        half = max(2, int(0.2 * ppm))
        band = slice(max(0, p - half), p + half + 1)
        rows_valid = top.valid[:, band].any(axis=1)
        on = (paint[:, band] & top.valid[:, band]).any(axis=1)
        if rows_valid.sum() < 5 * ppm:
            continue
        sig = on[rows_valid]
        coverage = float(sig.mean())
        if coverage < min_coverage:
            continue
        # 선 폭: 가로 단면의 반값 폭
        level = smooth[p] / 2
        left = p
        while left > 0 and smooth[left - 1] > level:
            left -= 1
        right = p
        while right < len(smooth) - 1 and smooth[right + 1] > level:
            right += 1
        width_m = (right - left + 1) / ppm
        core = slice(max(0, p - 1), p + 2)  # 선 가운데 칸으로 색을 정한다(가장자리는 흰색으로 잡히기 쉽다)
        ys = (yellow[:, core] & top.valid[:, core]).sum()
        ps = (paint[:, core] & top.valid[:, core]).sum()
        color = "yellow" if ps and ys / ps > 0.4 else "white"
        rows_on = np.flatnonzero(on)
        extent = (float(top.along(rows_on.max())), float(top.along(rows_on.min()))) if rows_on.size else (0.0, 0.0)
        period = length = None
        kind = "solid"
        if width_m > 0.6 and color == "white":
            kind = "barrier"   # 넓고 밝은 것: 중앙분리대·연석·보도 턱 (노란 복선 중앙선은 넓어도 선으로 둔다)
        elif coverage < 0.6:
            s = sig.astype(float) - sig.mean()
            ac = np.correlate(s, s, "full")[len(s) - 1:]
            ac = ac / ac[0] if ac[0] > 0 else ac
            lo, hi = int(3 * ppm), min(len(ac) - 1, int(30 * ppm))
            if hi > lo:
                pk, pp = find_peaks(ac[lo:hi], prominence=0.08)
                if len(pk):
                    best = pk[np.argmax(ac[lo:hi][pk])]
                    if ac[lo + best] > 0.15:
                        period = (lo + best) / ppm
            runs = [b - a for a, b in _runs(sig) if b - a >= 0.5 * ppm]
            if period is None or not runs:
                continue  # 화살표·글자처럼 반복되지 않는 표시
            length = float(np.median(runs)) / ppm
            # 차선 점선다운 반복: 간격 3~25 m, 점선이 간격의 20~65 %, 0.8 m 이상.
            # 실제 국도는 8 m·15 m 간격, City Lab 도시 모델은 약 4.3 m 간격(축척 2.92 m/단위 기준)이다
            if not (3.0 <= period <= 25.0 and 0.2 <= length / period <= 0.65 and length >= 0.8):
                continue
            kind = "dashed"
        lines.append(LaneLine(float(top.lateral(p)), color, kind, coverage, width_m, extent,
                              float(period) if period else None, length))
    return lines


def crosswalk_rows(top: TopView, paint, lateral_range) -> np.ndarray:
    """횡단보도 줄무늬가 있는 행(bool). 세로 선을 셀 때 빼려고 먼저 찾는다."""
    rows = np.zeros(paint.shape[0], bool)
    for t in find_transverse(top, paint, lateral_range, None, stop_lines=False):
        r0, r1 = (int(np.clip(top.row(a), 0, len(rows))) for a in (t.along_m[1] + 0.5, t.along_m[0] - 0.5))
        rows[r0:r1] = True
    return rows


def find_transverse(top: TopView, paint, lateral_range, centre: float | None, stop_lines: bool = True) -> list[Transverse]:
    """도로 폭 안의 가로 표시: 정지선(얇은 띠)과 횡단보도(세로 줄무늬가 이어진 넓은 띠)."""
    ppm = top.ppm
    c0, c1 = (int(max(0, round(v))) for v in top.col(np.asarray(lateral_range)))
    c1 = min(c1, paint.shape[1] - 1)
    if c1 - c0 < 2 * ppm:
        return []
    out = []
    region = paint[:, c0:c1 + 1] & top.valid[:, c0:c1 + 1]
    valid = top.valid[:, c0:c1 + 1]
    # 횡단보도: 한 행에 폭과 간격이 고른 세로 줄무늬가 4개 이상(글자·무늬는 고르지 않다)
    def regular_stripes(row) -> bool:
        runs = [r for r in _runs(row) if 0.25 * ppm <= r[1] - r[0] <= 1.2 * ppm]
        if len(runs) < 4:
            return False
        widths = np.array([b - a for a, b in runs], float)
        gaps = np.array([runs[i + 1][0] - runs[i][1] for i in range(len(runs) - 1)], float)
        return widths.std() / widths.mean() < 0.4 and gaps.std() / max(gaps.mean(), 1e-6) < 0.5
    stripes = np.array([regular_stripes(region[i]) for i in range(region.shape[0])])
    frac = region.sum(axis=1) / np.maximum(valid.sum(axis=1), 1)
    cw = stripes & (frac > 0.2) & (frac < 0.8)
    cw = cv2.morphologyEx(cw.astype(np.uint8).reshape(-1, 1), cv2.MORPH_CLOSE, np.ones((int(0.6 * ppm) | 1, 1), np.uint8)).ravel() > 0
    cw_rows = np.zeros(len(cw), bool)
    for a, b in _runs(cw):
        if 1.8 * ppm <= b - a <= 8 * ppm:
            out.append(Transverse("crosswalk", (float(top.along(b - 1)), float(top.along(a))), tuple(map(float, lateral_range))))
            cw_rows[max(0, a - int(0.3 * ppm)):b + int(0.3 * ppm)] = True
    if not stop_lines:
        return out
    # 정지선: 반쪽 도로(중앙선 기준) 폭의 대부분을 덮는 얇은 밝은 띠. 앞뒤 노면이 둘 다 더 어둡고 서로 비슷해야 한다
    # (건물 그림자 경계는 한쪽만 어두워서 여기서 걸러진다)
    value = cv2.cvtColor(top.image, cv2.COLOR_BGR2HSV)[..., 2].astype(float)
    mid = centre if centre is not None else (lateral_range[0] + lateral_range[1]) / 2
    k0, k1 = int(0.3 * ppm), int(1.0 * ppm)
    for lo, hi in ((lateral_range[0], mid), (mid, lateral_range[1])):
        a0, a1 = (int(max(0, round(v))) for v in top.col(np.asarray([lo, hi])))
        if a1 - a0 < 2 * ppm:
            continue
        sub = paint[:, a0:a1] & top.valid[:, a0:a1]
        f = sub.sum(axis=1) / np.maximum(top.valid[:, a0:a1].sum(axis=1), 1)
        rows = (f > 0.55) & ~cw_rows & (top.valid[:, a0:a1].mean(axis=1) > 0.6)
        for a, b in _runs(rows):
            # 정지선 폭은 0.3~0.6 m지만 먼 곳은 위에서 본 그림에서 번져 두꺼워지므로 1.5 m까지 받는다
            if not (0.15 * ppm <= b - a <= 1.5 * ppm) or a - k1 < 0 or b + k1 > value.shape[0]:
                continue
            band_v = value[a:b, a0:a1].mean()
            before, after = value[a - k1:a - k0, a0:a1].mean(), value[b + k0:b + k1, a0:a1].mean()
            contrast = band_v - max(before, after)
            if contrast < 25 or abs(before - after) > 0.5 * (band_v - min(before, after)):
                continue
            out.append(Transverse("stop_line", (float(top.along(b - 1)), float(top.along(a))), (float(lo), float(hi))))
    return out


def _road_edges(lines: list[LaneLine], centre: float, max_gap_m: float) -> tuple[float, float] | None:
    """중앙에서 바깥으로 차로 폭(max_gap_m 이하) 간격으로 이어지는 도색 선을 따라가 양쪽 도로 끝(m)을 찾는다.
    점선은 차로와 차로 사이에만 있으므로, 끝 선이 점선이면 한 차로 더 바깥(그 근처 선이나 연석, 없으면 차로 폭만큼)을 끝으로 본다."""
    paint = sorted((l for l in lines if l.kind in ("solid", "dashed")), key=lambda l: l.lateral_m)
    if len(paint) < 2:
        return None
    chains = []
    for side in (-1, 1):
        chain = sorted((l for l in paint if (l.lateral_m - centre) * side >= -0.05), key=lambda l: (l.lateral_m - centre) * side)
        kept, pos = [], centre
        for line in chain:
            if abs(line.lateral_m - pos) > max_gap_m:
                break
            kept.append(line); pos = line.lateral_m
        chains.append(kept)
    if not chains[0] or not chains[1] or chains[0][-1] is chains[1][-1]:
        return None
    lats = sorted({centre, *(l.lateral_m for c in chains for l in c)})
    gaps = [b - a for a, b in zip(lats, lats[1:]) if b - a >= 2.0]
    lane = float(np.median(gaps)) if gaps else 3.5
    edges = []
    for side, chain in zip((-1, 1), chains):
        last = chain[-1]
        edge = last.lateral_m
        if last.kind == "dashed":
            beyond = [l for l in lines if 0.5 * lane <= (l.lateral_m - edge) * side <= 1.6 * lane]
            edge = min(beyond, key=lambda l: abs(abs(l.lateral_m - edge) - lane)).lateral_m if beyond else edge + side * lane
        edges.append(edge)
    return edges[0], edges[1]


def analyse_road(image, plane: GroundPlane, *, ppm: float = 20.0, max_distance_m: float = 100.0,
                 lateral_half_m: float = 25.0, band_margin_m: float = 1.0, max_lane_gap_m: float = 5.0,
                 ignore=None) -> RoadScene:
    """배경 그림 한 장에서 도로 방향·세로 선·가로 표시를 찾는다. ignore: 분석에서 뺄 화면 영역(bool 마스크)."""
    along = (-5.0, max_distance_m)

    def prepare(frame):
        top = make_top_view(image, plane, frame, ppm=ppm, along_range=along, lateral_half=lateral_half_m, ignore=ignore)
        band = road_band(top, asphalt_mask(top))
        region = None
        if band:
            region = np.zeros_like(top.valid)
            c0, c1 = (int(np.clip(top.col(v), 0, region.shape[1])) for v in (band[0] - band_margin_m, band[1] + band_margin_m))
            region[:, c0:c1] = True
        paint, yellow = paint_masks(top, region=region)
        if region is not None:  # 노면 띠 밖의 도색 후보(건물 벽·간판·풀)는 처음부터 뺀다
            paint, yellow = paint & region, yellow & region
        return top, band, paint, yellow

    frame = _initial_frame(plane)
    top, band, paint, yellow = prepare(frame)
    for _ in range(2):  # 도로 방향으로 다시 맞춘다
        angle = dominant_angle(paint, ppm)
        if angle is None or abs(angle) < math.radians(0.2):
            break
        frame = _rotated(frame, angle)
        top, band, paint, yellow = prepare(frame)
    scene = RoadScene(frame, top, paint, yellow)
    scene.band = band
    skip = None
    if band:
        skip = crosswalk_rows(top, paint, band)
        # 앞쪽 첫 횡단보도(= 교차로) 너머는 차로 구성이 바뀔 수 있어 세로 선을 셀 때 뺀다
        ahead = [t for t in find_transverse(top, paint, band, None, stop_lines=False) if t.along_m[0] > 10.0]
        if ahead:
            limit = min(t.along_m[0] for t in ahead)
            skip = skip | (top.along(np.arange(len(skip))) > limit)
    lines = find_longitudinal_lines(top, paint, yellow, skip_rows=skip)
    if scene.band:  # 노면 띠 밖(풀·건물·주차장)의 선은 버린다
        lines = [l for l in lines if scene.band[0] - band_margin_m <= l.lateral_m <= scene.band[1] + band_margin_m]
    scene.lines = lines
    # 중앙: 노란 중앙선. 가장자리에도 노란 선(주정차 금지)이 있을 수 있어, 복선(넓은 노란 선)을 먼저,
    # 없으면 노면 띠 가운데에 가장 가까운 노란 선을 고른다. 노란 선이 없으면 띠 가운데에 가장 가까운 선
    yellows = [l for l in lines if l.color == "yellow" and l.kind != "barrier"]
    paint_lines = [l for l in lines if l.kind in ("solid", "dashed")]
    mid = sum(scene.band) / 2 if scene.band else 0.0
    if scene.band:  # 노면 띠 가장자리 쪽 노란 선은 주정차 금지 가장자리선이다. 가운데 60 % 안의 것만 중앙선 후보
        half = 0.3 * (scene.band[1] - scene.band[0])
        yellows = [l for l in yellows if abs(l.lateral_m - mid) <= half]
    if yellows:
        doubles = [l for l in yellows if l.width_m >= 0.5]
        pick = max(doubles, key=lambda l: l.width_m) if doubles else min(yellows, key=lambda l: abs(l.lateral_m - mid))
        scene.centre_lateral = pick.lateral_m
        start = scene.centre_lateral
    else:
        start = min((l.lateral_m for l in paint_lines), key=lambda x: abs(x - mid), default=mid)
    edges = _road_edges(lines, start, max_lane_gap_m)
    if edges:
        scene.road_lateral = edges
        used = [l for l in paint_lines if edges[0] <= l.lateral_m <= edges[1]]
        scene.road_along = (min(l.along_extent_m[0] for l in used), max(l.along_extent_m[1] for l in used))
    elif scene.band:
        scene.road_lateral = scene.band
        scene.road_along = (along[0], along[1])
    if scene.road_lateral:
        scene.transverse = find_transverse(top, paint, scene.road_lateral, scene.centre_lateral)
    return scene


def _clip_unit(poly: np.ndarray) -> np.ndarray:
    """다각형을 [0,1]x[0,1] 상자로 자른다(Sutherland–Hodgman)."""
    def clip(pts, inside, cross):
        out = []
        for i in range(len(pts)):
            a, b = pts[i - 1], pts[i]
            if inside(b):
                if not inside(a):
                    out.append(cross(a, b))
                out.append(b)
            elif inside(a):
                out.append(cross(a, b))
        return out
    pts = [tuple(p) for p in poly]
    for axis, bound, keep_greater in ((0, 0.0, True), (0, 1.0, False), (1, 0.0, True), (1, 1.0, False)):
        if not pts:
            break
        def inside(p, axis=axis, bound=bound, g=keep_greater):
            return p[axis] >= bound if g else p[axis] <= bound
        def cross(a, b, axis=axis, bound=bound):
            t = (bound - a[axis]) / (b[axis] - a[axis])
            return (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        pts = clip(pts, inside, cross)
    return np.array(pts, float).reshape(-1, 2)


def road_polygon_pixels(plane: GroundPlane, frame: RoadFrame, along, lateral, samples: int = 8) -> np.ndarray:
    """도로 좌표 사각형 → 화면 픽셀 다각형(카메라 앞 부분만)."""
    a0, a1 = along
    l0, l1 = lateral
    edge = []
    for t in np.linspace(0, 1, samples):
        edge.append((a0 + t * (a1 - a0), l0))
    for t in np.linspace(0, 1, samples):
        edge.append((a1, l0 + t * (l1 - l0)))
    for t in np.linspace(0, 1, samples):
        edge.append((a1 - t * (a1 - a0), l1))
    for t in np.linspace(0, 1, samples):
        edge.append((a0, l1 - t * (l1 - l0)))
    uv, front = plane.to_pixel(frame.to_ground(np.array(edge)))
    return uv[front]


def build_context(scene: RoadScene, plane: GroundPlane, *, shoulder_m: float = 0.6, stop_zone_length_m: float = 15.0,
                  polygon_far_m: float | None = None, camera_id: str | None = None) -> dict:
    """팀 경고 엔진 형식(road_polygon, stop_zones)과 참고용 차선·정지선 정보.
    polygon_far_m: 도로 영역을 선이 확인된 곳보다 먼 곳까지 곧게 늘릴 거리(m). 직선 구간에서만 쓴다."""
    w, h = plane.image_size
    norm = lambda uv: _clip_unit(np.asarray(uv, float) / [w, h])  # noqa: E731
    ctx = {"camera_id": camera_id, "image_size": [w, h], "coordinates": "image_normalized_xy (0~1, 왼쪽 위 원점)",
           "road_polygon": [], "stop_zones": [], "lanes": [], "stop_lines": [], "crosswalks": [],
           "method": "opencv_topview_paint", "road_frame": {
               "origin_ground": scene.frame.origin.tolist(), "forward_ground": scene.frame.forward.tolist(),
               "meters_per_unit": scene.frame.meters_per_unit}}
    if scene.road_lateral is None:
        ctx["warning"] = "도로 양쪽 선을 찾지 못해 도로 영역을 만들지 못했습니다"
        return ctx
    # 화면 맨 아래보다 조금 더 가까운 곳부터 선이 보이는 가장 먼 곳까지
    bottom = scene.frame.to_road(plane.to_ground([(0, h - 1), (w / 2, h - 1), (w - 1, h - 1)]))[:, 0]
    a0 = float(min(bottom.min(), scene.road_along[0])) - 2.0
    # 횡단보도가 보이면 도로가 그 너머까지 이어지므로, 가장 먼 횡단보도 너머 2 m까지는 도로로 본다
    far_cross = max((t.along_m[1] + 2.0 for t in scene.transverse if t.kind == "crosswalk"), default=0.0)
    a1 = float(max(scene.road_along[1], polygon_far_m or 0.0, far_cross))
    lat = (scene.road_lateral[0] - shoulder_m, scene.road_lateral[1] + shoulder_m)
    poly = norm(road_polygon_pixels(plane, scene.frame, (a0, a1), lat))
    if len(poly) >= 3:
        ctx["road_polygon"] = [[round(float(x), 5), round(float(y), 5)] for x, y in poly]
    ctx["road_lateral_m"] = list(map(float, lat))
    ctx["road_along_m"] = [a0, a1]
    ctx["centre_lateral_m"] = scene.centre_lateral
    for line in scene.lines:
        uv, front = plane.to_pixel(scene.frame.to_ground([(max(a0, line.along_extent_m[0]), line.lateral_m),
                                                          (line.along_extent_m[1], line.lateral_m)]))
        ctx["lanes"].append({"lateral_m": round(line.lateral_m, 3), "color": line.color, "kind": line.kind,
                             "coverage": round(line.coverage, 3), "width_m": round(line.width_m, 3),
                             "along_m": [round(v, 2) for v in line.along_extent_m],
                             "dash_period_m": line.dash_period_m and round(line.dash_period_m, 2),
                             "dash_length_m": line.dash_length_m and round(line.dash_length_m, 2),
                             "image_xy": [[round(float(x) / w, 5), round(float(y) / h, 5)] for x, y in uv[front]]})
    mid = scene.centre_lateral if scene.centre_lateral is not None else sum(scene.road_lateral) / 2
    crosswalks = [t for t in scene.transverse if t.kind == "crosswalk"]
    stops = [t for t in scene.transverse if t.kind == "stop_line"]
    for t in crosswalks:
        ctx["crosswalks"].append({"along_m": [round(v, 2) for v in t.along_m], "lateral_m": [round(v, 2) for v in t.lateral_m]})
    # 정지 위치: 칠해진 정지선, 그 방향에 정지선이 없는 횡단보도는 횡단보도 1 m 앞.
    # 우측 통행: 중앙선 오른쪽(멀어지는 차로)은 정지 위치 앞(카메라 쪽), 왼쪽(다가오는 차로)은 뒤(먼 쪽)에서 기다린다.
    positions = []  # (오른쪽인가, 정지 위치 along, 근거)
    for t in stops:
        right_side = (t.lateral_m[0] + t.lateral_m[1]) / 2 > mid
        positions.append((right_side, t.along_m[0] if right_side else t.along_m[1], "stop_line"))
        ctx["stop_lines"].append({"along_m": [round(v, 2) for v in t.along_m], "lateral_m": [round(v, 2) for v in t.lateral_m],
                                  "side": "away" if right_side else "toward"})
    for c in crosswalks:
        for right_side in (True, False):
            s = c.along_m[0] - 1.0 if right_side else c.along_m[1] + 1.0
            if not any(p[0] == right_side and abs(p[1] - s) < 6.0 for p in positions):
                positions.append((right_side, s, "crosswalk"))
    for right_side, s, basis in positions:
        if right_side:   # 카메라 쪽으로 늘리되, 뒤쪽 횡단보도(교차로)에 닿기 전에서 멈춘다
            behind = [c.along_m[1] + 1.0 for c in crosswalks if c.along_m[1] < s - 0.5]
            zone_along = (max([s - stop_zone_length_m, *behind]), s)
        else:
            ahead = [c.along_m[0] - 1.0 for c in crosswalks if c.along_m[0] > s + 0.5]
            zone_along = (s, min([s + stop_zone_length_m, *ahead]))
        if zone_along[1] - zone_along[0] < 3.0:
            continue
        zone_lat = (mid, lat[1]) if right_side else (lat[0], mid)
        zone = norm(road_polygon_pixels(plane, scene.frame, zone_along, zone_lat))
        if len(zone) >= 3:
            ctx["stop_zones"].append([[round(float(x), 5), round(float(y), 5)] for x, y in zone])
            ctx.setdefault("stop_zone_basis", []).append({"side": "away" if right_side else "toward", "basis": basis,
                                                         "along_m": [round(v, 2) for v in zone_along]})
    return ctx


def draw_context(image, ctx: dict) -> np.ndarray:
    """확인용 그림: 도로 영역(초록), 정지 대기 영역(빨강), 차선(노랑·흰색·회색)."""
    h, w = image.shape[:2]
    out = image.copy()
    over = image.copy()
    if ctx.get("road_polygon"):
        cv2.fillPoly(over, [np.int32(np.array(ctx["road_polygon"]) * [w, h])], (60, 200, 60))
    for zone in ctx.get("stop_zones", []):
        cv2.fillPoly(over, [np.int32(np.array(zone) * [w, h])], (40, 40, 230))
    out = cv2.addWeighted(over, 0.35, out, 0.65, 0)
    if ctx.get("road_polygon"):
        cv2.polylines(out, [np.int32(np.array(ctx["road_polygon"]) * [w, h])], True, (60, 220, 60), 2)
    colors = {"yellow": (0, 220, 255), "white": (255, 255, 255)}
    for lane in ctx.get("lanes", []):
        pts = np.int32(np.array(lane["image_xy"]) * [w, h])
        if len(pts) == 2:
            color = (150, 150, 150) if lane["kind"] == "barrier" else colors[lane["color"]]
            thick = 1 if lane["kind"] == "dashed" else 2
            cv2.line(out, tuple(pts[0]), tuple(pts[1]), color, thick, cv2.LINE_AA)
    return out
