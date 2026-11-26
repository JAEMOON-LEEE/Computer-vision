"""고정 CCTV 영상 한 편을 Unity에서 같은 구도로 재현할 재생 묶음을 만든다(위성지도 기준점 없이).

    python mapping/scripts/cctv_scene_replay.py --video frontend/public/demo-videos/pothole.mp4 \
        --tracks captures/yunggeon_tracks.jsonl --out simulation/TwinSightSim/RealCctv/yunggeon

1. 카메라: 노면 표시 선분(LSD)에서 서로 직각인 두 도로 방향의 소실점을 RANSAC으로 찾아 초점거리·기울기를 구한다.
   높이(축척)는 도로를 따라 달리는 승용차 박스 밑변을 차폭 1.85 m로 놓고 정한다(횡단보도 줄 간격으로 교차 확인).
2. 배경: 추적 박스로 가린 화소를 빼고 프레임 중앙값을 구해 차량 없는 배경을 만든다.
3. 노면 질감: 배경을 위에서 본 그림(정사영)으로 펴서 Unity 바닥에 깐다. 같은 자세의 카메라로 보면 원래 화면과 겹친다.
4. 차량: 추적 결과의 박스 밑변 가운데를 노면으로 옮기고, 카메라 반대쪽으로 차체 깊이 절반만큼 밀어 차량 중심을 잡은 뒤
   시간축으로 매끄럽게 하고 진행 방향을 계산한다.

좌표: 카메라 바로 아래 노면이 원점, right_m = 카메라 수평 오른쪽, fwd_m = 카메라 수평 앞쪽(미터).
결과는 정성 재현용이며 축척은 표준 차폭 가정에 따라 ±10 % 정도 틀릴 수 있다.
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import cv2
import numpy as np

CAR_WIDTH_M = 1.85
SIZES = {"car": (4.6, 1.85), "truck": (7.5, 2.4), "bus": (11.0, 2.5), "motorcycle": (2.0, 0.8), "bicycle": (1.8, 0.6), "person": (0.5, 0.5)}
CAPTION_BOXES: list[tuple[int, int, int, int]] = []   # --mask로 영상마다 화면 자막 영역을 준다


def load_tracks(path):
    rows = [json.loads(line) for line in open(path, encoding="utf8")]
    return rows


def background(video, rows, samples=80, start=0.0, end=None):
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); fps = cap.get(cv2.CAP_PROP_FPS)
    lo = int(start * fps); hi = min(n - 1, int(end * fps)) if end else n - 1
    by_frame = {r["frame"]: r["detections"] for r in rows}
    frames, masks = [], []
    for i in np.linspace(lo, hi, samples).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i)); ok, img = cap.read()
        if not ok:
            continue
        key = min(by_frame, key=lambda f: abs(f - i))
        m = np.zeros(img.shape[:2], np.uint8)
        for d in by_frame[key]:
            x1, y1, x2, y2 = [int(v) for v in d["bbox_xyxy"]]
            pad = int(0.15 * (x2 - x1)) + 4
            m[max(0, y1 - pad):y2 + pad, max(0, x1 - pad):x2 + pad] = 1
        frames.append(img); masks.append(m)
    stack = np.stack(frames); mask = np.stack(masks).astype(bool)
    out = np.median(stack, axis=0).astype(np.uint8)            # 가려지지 않은 화소가 없을 때의 대체값
    for y0 in range(0, stack.shape[1], 90):                      # 메모리 절약: 행 단위로 가린 화소를 빼고 중앙값
        chunk = stack[:, y0:y0 + 90].astype(np.float32)
        chunk[np.repeat(mask[:, y0:y0 + 90, :, None], 3, axis=3)] = np.nan
        med = np.nanmedian(chunk, axis=0)
        good = ~np.isnan(med)
        out[y0:y0 + 90][good] = med[good].astype(np.uint8)
    return out


def vanishing_points(bg, seed=0, use_crosswalk=True):
    gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    th = cv2.morphologyEx(gray, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31)))
    mask = (th > 25).astype(np.uint8) * 255
    h = bg.shape[0]
    mask[: int(h * 0.52)] = 0                                    # 하늘·건물(노면은 화면 아래쪽)
    for x0, y0, x1, y1 in CAPTION_BOXES:
        mask[y0:y1, x0:x1] = 0
    segs = cv2.createLineSegmentDetector().detect(cv2.GaussianBlur(mask, (3, 3), 0))[0].reshape(-1, 4)
    length = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    segs, length = segs[length > 25], length[length > 25]
    p1 = np.c_[segs[:, :2], np.ones(len(segs))]; p2 = np.c_[segs[:, 2:], np.ones(len(segs))]
    lines = np.cross(p1, p2); lines /= np.linalg.norm(lines[:, :2], axis=1, keepdims=True)
    mid = (segs[:, :2] + segs[:, 2:]) / 2; direction = (segs[:, 2:] - segs[:, :2]) / length[:, None]
    rng = np.random.default_rng(seed)

    def consistent(vp, tol=1.5):
        v = vp[:2] - mid * vp[2]; v /= np.linalg.norm(v, axis=1, keepdims=True) + 1e-12
        return np.degrees(np.arccos(np.clip(np.abs((v * direction).sum(1)), -1, 1))) < tol

    def ransac(active):
        idx = np.flatnonzero(active); best, best_vp = -1, None
        for _ in range(4000):
            i, j = rng.choice(idx, 2, replace=False)
            vp = np.cross(lines[i], lines[j])
            if np.abs(vp).max() < 1e-12:
                continue
            score = length[consistent(vp) & active].sum()
            if score > best:
                best, best_vp = score, vp
        inl = consistent(best_vp) & active
        vp = np.linalg.svd(lines[inl] * length[inl, None])[2][-1]
        return vp / vp[2], consistent(vp) & active

    active = np.ones(len(segs), bool)
    a, inl_a = ransac(active)
    b, inl_b = ransac(active & ~inl_a)
    # 기준: 화면 안쪽에 가까운 소실점(멀리 뻗은 도로 방향). 여러 시드에서 가장 안정적이다.
    w = bg.shape[1]
    first, inl = (a, inl_a) if abs(a[0] - w / 2) < abs(b[0] - w / 2) else (b, inl_b)
    active &= ~inl
    band = crosswalk_band_vp(bg, first[1]) if use_crosswalk else None
    if band is not None:
        # 가까운 횡단보도: 줄무늬(첫 소실점 방향)와 띠 가장자리는 서로 직각이다. 띠 가장자리 직선이 화면 폭 전체에
        # 걸쳐 있어 멀리 있는 두 번째 소실점을 가장 안정적으로 정한다.
        second = np.array([band, first[1]])
        return [second, first[:2]] if abs(first[0] - w / 2) < abs(second[0] - w / 2) else [first[:2], second]
    # 고정 CCTV는 수평으로 설치한다고 보고(roll ≈ 0) 두 번째 소실점을 첫 소실점과 같은 높이의 수평선 위에서 찾는다.
    # 교차로 안쪽의 곡선 유도선 같은 선분이 두 번째 소실점을 끌어당기는 것을 막는다.
    w = bg.shape[1]
    candidates = np.r_[-np.geomspace(w, 40 * w, 400), w + np.geomspace(w, 40 * w, 400)]
    scores = [length[consistent(np.array([x, first[1], 1.0])) & active].sum() for x in candidates]
    best = candidates[int(np.argmax(scores))]
    fine = np.linspace(best * 0.9, best * 1.1, 200)
    scores = [length[consistent(np.array([x, first[1], 1.0])) & active].sum() for x in fine]
    second = np.array([fine[int(np.argmax(scores))], first[1]])
    return [second, first[:2]] if abs(first[0] - w / 2) < abs(second[0] - w / 2) else [first[:2], second]


def crosswalk_band_vp(bg, horizon_y, min_stripes=8):
    """화면 아래쪽 횡단보도 줄무늬 끝점들로 띠 가장자리 직선을 맞추고 수평선과 만나는 x를 돌려준다(없으면 None)."""
    g = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)
    h = g.shape[0]
    th = cv2.morphologyEx(g, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (41, 41)))
    mask = ((th > 30) & (np.arange(h)[:, None] > int(h * 0.74))).astype(np.uint8)
    for x0, y0, x1, y1 in CAPTION_BOXES:
        mask[y0:y1, x0:x1] = 0
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
    edges = {"top": [], "bottom": []}
    for i in range(1, n):
        x, y, ww, hh, area = stats[i]
        if area < 400 or hh < 30:
            continue
        ys, xs = np.nonzero(lab[y:y + hh, x:x + ww] == i)
        edges["top"].append((x + xs[ys == ys.min()].mean(), y + ys.min()))
        if y + ys.max() < h - 3:
            edges["bottom"].append((x + xs[ys == ys.max()].mean(), y + ys.max()))
    rng = np.random.default_rng(0)
    crossings = []
    for pts in edges.values():
        pts = np.asarray(pts, float)
        if len(pts) < min_stripes:
            continue
        best = None
        for _ in range(2000):
            i, j = rng.choice(len(pts), 2, replace=False)
            d = pts[j] - pts[i]; nrm = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-9)
            inl = np.abs((pts - pts[i]) @ nrm) < 4
            if best is None or inl.sum() > best.sum():
                best = inl
        if best.sum() < min_stripes:
            continue
        vx, vy, x0, y0 = cv2.fitLine(pts[best].astype(np.float32), cv2.DIST_L2, 0, 0.01, 0.01).ravel()
        if abs(vy) < 1e-6:
            continue
        crossings.append(x0 + (horizon_y - y0) / vy * vx)
    return float(np.mean(crossings)) if crossings else None


class Camera:
    def __init__(self, vps, size, focal=None):
        """vps: 서로 직각인 두 도로 방향 소실점. focal을 주면 첫 소실점(도로 방향)과 그 초점거리만 쓴다(수평 설치 가정)."""
        w, h = size
        c = np.array([w / 2, h / 2]); v1, v2 = vps
        if focal is None:
            f2 = -np.dot(v1 - c, v2 - c)
            if f2 <= 0:
                raise ValueError("두 소실점이 직각인 도로 방향이 아닙니다(초점거리를 구할 수 없음)")
            focal = float(np.sqrt(f2))
            if focal < 0.3 * w or focal > 4 * w:
                raise ValueError(f"초점거리 {focal:.0f}px가 비현실적입니다")
        else:
            # 같은 수평선 위에 도로 방향과 직각인 가상의 소실점을 만든다(roll 0): (v1-c)·(v2-c) = -f²
            dx = v1[0] - c[0]; dy = v1[1] - c[1]
            v2 = np.array([c[0] - (focal ** 2 + dy * dy) / (dx if abs(dx) > 1e-6 else 1e-6), v1[1]])
        self.f = float(focal); self.size = size
        self.K = np.array([[self.f, 0, c[0]], [0, self.f, c[1]], [0, 0, 1]]); self.Ki = np.linalg.inv(self.K)
        d1 = self.Ki @ np.r_[v1, 1]; d2 = self.Ki @ np.r_[v2, 1]
        d1 /= np.linalg.norm(d1); d2 -= d1 * (d1 @ d2); d2 /= np.linalg.norm(d2)
        up = np.cross(d1, d2); up /= np.linalg.norm(up)
        if (self.Ki @ np.array([c[0], h - 1, 1.0])) @ up > 0:
            up = -up                                           # 화면 아래쪽 광선이 노면(아래)을 향하게
        self.up = up
        z = np.array([0, 0, 1.0]); x = np.array([1.0, 0, 0])
        fwd = z - (z @ up) * up; self.fwd = fwd / np.linalg.norm(fwd)
        right = x - (x @ up) * up - (x @ self.fwd) * self.fwd; self.right = right / np.linalg.norm(right)
        self.height = 1.0
        self.pitch = float(np.degrees(np.arcsin(-(z @ up))))     # 광축이 수평 아래로 내려간 각도
        self.roll = float(np.degrees(np.arctan2(-(x @ up), (np.array([0, -1.0, 0]) @ up))))

    def ground(self, u, v):
        r = self.Ki @ np.array([u, v, 1.0])
        t = -self.height / (r @ self.up)
        if t <= 0:
            return None
        p = t * r
        return np.array([p @ self.right, p @ self.fwd])

    def pixel(self, right_m, fwd_m):
        p = right_m * self.right + fwd_m * self.fwd - self.height * self.up
        q = self.K @ p
        return q[:2] / q[2]


def scale_from_cars(cam, rows):
    tracks = collections.defaultdict(list)
    for r in rows:
        for d in r["detections"]:
            if d["class_name"] == "car":
                tracks[d["track_id"]].append(d["bbox_xyxy"])
    widths = []
    w, h = cam.size
    for boxes in tracks.values():
        if len(boxes) < 15:
            continue
        a = cam.ground((boxes[0][0] + boxes[0][2]) / 2, boxes[0][3]); b = cam.ground((boxes[-1][0] + boxes[-1][2]) / 2, boxes[-1][3])
        if a is None or b is None or np.linalg.norm(b - a) < 5:
            continue
        move = (b - a) / np.linalg.norm(b - a)
        for x1, y1, x2, y2 in boxes:
            if y2 > h - 10 or x1 < 3 or x2 > w - 3:
                continue
            left, right = cam.ground(x1, y2), cam.ground(x2, y2)
            if left is None or right is None:
                continue
            ray = (left + right) / 2; ray /= np.linalg.norm(ray) + 1e-9
            # 카메라 쪽으로 오가는 차(진행 방향 ≈ 시선 방향)만: 박스 밑변의 진행 방향 직각 성분 ≈ 차폭
            if abs(ray @ move) > 0.85:
                span = right - left
                widths.append(abs(span[0] * move[1] - span[1] * move[0]))
    if len(widths) < 30:
        raise ValueError(f"축척을 정할 차량 관측이 부족합니다({len(widths)}개)")
    return CAR_WIDTH_M / float(np.median(widths)), len(widths)


def scale_from_box_sizes(cam, rows, candidates=np.geomspace(2.0, 40.0, 120)):
    """표준 크기 차량(SIZES)을 화면에 투영한 상자 크기가 실제 검출 상자와 가장 잘 맞는 카메라 높이를 고른다."""
    tracks = collections.defaultdict(list)
    for r in rows:
        for d in r["detections"]:
            if d["class_name"] in ("car", "truck", "bus"):
                tracks[d["track_id"]].append((d["class_name"], d["bbox_xyxy"]))
    w, h = cam.size
    samples = []
    for obs in tracks.values():
        if len(obs) < 6:
            continue
        for cls, (x1, y1, x2, y2) in obs[:: max(1, len(obs) // 8)]:
            if y2 > h - 6 or x1 < 3 or x2 > w - 3 or y1 < 3:
                continue
            samples.append((cls, (x1, y1, x2, y2), obs))
    if len(samples) < 10:
        return None
    best, best_err = None, np.inf
    original = cam.height
    for hh in candidates:
        cam.height = float(hh)
        errs = []
        for cls, (x1, y1, x2, y2), obs in samples:
            g = cam.ground((x1 + x2) / 2, y2)
            first, last = obs[0][1], obs[-1][1]
            a = cam.ground((first[0] + first[2]) / 2, first[3]); b = cam.ground((last[0] + last[2]) / 2, last[3])
            if g is None or a is None or b is None:
                continue
            mv = b - a; heading = np.arctan2(mv[0], mv[1]) if np.linalg.norm(mv) > 1e-3 else 0.0
            L, W = SIZES.get(cls, SIZES["car"]); Hh = {"car": 1.5, "truck": 2.8, "bus": 3.2}.get(cls, 1.5)
            fw = np.array([np.sin(heading), np.cos(heading)]); rt = np.array([np.cos(heading), -np.sin(heading)])
            ray = g / (np.linalg.norm(g) + 1e-9)
            centre = g + ray * 0.5 * (abs(ray @ fw) * L + abs(ray[0] * fw[1] - ray[1] * fw[0]) * W)
            pts = []
            for sl in (-1, 1):
                for sw in (-1, 1):
                    base = centre + fw * sl * L / 2 + rt * sw * W / 2
                    for z in (0.0, Hh):
                        P = base[0] * cam.right + base[1] * cam.fwd + (z - cam.height) * cam.up
                        q = cam.K @ P
                        if q[2] <= 0:
                            break
                        pts.append(q[:2] / q[2])
            if len(pts) < 8:
                continue
            pts = np.array(pts); pw, ph = np.ptp(pts[:, 0]), np.ptp(pts[:, 1])
            errs.append(abs(np.log(max(pw, 1) / max(x2 - x1, 1))) + abs(np.log(max(ph, 1) / max(y2 - y1, 1))))
        if len(errs) >= 10 and np.median(errs) < best_err:
            best, best_err = float(hh), float(np.median(errs))
    cam.height = original
    return best


def smooth_track(times, pts, window=7):
    order = np.argsort(times); times, pts = np.asarray(times)[order], np.asarray(pts)[order]
    # 튀는 점 제거: 이웃 중앙값에서 3 m 넘게 벗어난 관측
    keep = np.ones(len(pts), bool)
    for i in range(len(pts)):
        lo, hi = max(0, i - 3), min(len(pts), i + 4)
        if np.linalg.norm(pts[i] - np.median(pts[lo:hi], axis=0)) > 3.0:
            keep[i] = False
    times, pts = times[keep], pts[keep]
    if len(pts) < 5:
        return None
    kernel = np.ones(window) / window
    pad = window // 2
    sm = np.stack([np.convolve(np.pad(pts[:, k], pad, mode="edge"), kernel, mode="valid") for k in range(2)], axis=1)
    return times, sm


def build(args):
    rows = [r for r in load_tracks(args.tracks) if r["t"] >= args.start and (args.end is None or r["t"] <= args.end)]
    cap = cv2.VideoCapture(str(args.video)); fps = cap.get(cv2.CAP_PROP_FPS)
    duration = args.end or cap.get(cv2.CAP_PROP_FRAME_COUNT) / fps
    size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    bg = background(args.video, rows, start=args.start, end=args.end)
    try:
        cam = Camera(vanishing_points(bg), size)
        calib_method = "two orthogonal vanishing points (lane/crosswalk markings) + median car width 1.85 m"
    except ValueError as exc:
        # 횡단보도·교차 도로가 없는 고속도로: 도로 방향 소실점 + 가정한 세로 화각(수평 설치)
        print("두 번째 소실점 실패:", exc, "→ 세로 화각", args.assume_vfov, "도 가정", flush=True)
        vps = vanishing_points(bg, use_crosswalk=False)
        road = min(vps, key=lambda v: abs(v[0] - size[0] / 2))
        cam = Camera([road, road], size, focal=size[1] / 2 / np.tan(np.radians(args.assume_vfov) / 2))
        calib_method = f"road-direction vanishing point + assumed vertical FOV {args.assume_vfov} deg (roll 0) + median car width 1.85 m"
    def try_scale(c):
        try:
            k, n = scale_from_cars(c, rows)
            return (k, n) if 2.0 <= k <= 40.0 else (None, n)
        except ValueError:
            return None, 0
    k, n_width = try_scale(cam)
    if k is None and "assumed" not in calib_method:
        # 두 소실점 카메라로 축척이 안 나오면(고속도로 등) 도로 방향 소실점 + 가정 화각으로 다시
        vps = vanishing_points(bg, use_crosswalk=False)
        road = min(vps, key=lambda v: abs(v[0] - size[0] / 2))
        cam = Camera([road, road], size, focal=size[1] / 2 / np.tan(np.radians(args.assume_vfov) / 2))
        calib_method = f"road-direction vanishing point + assumed vertical FOV {args.assume_vfov} deg (roll 0)"
        k, n_width = try_scale(cam)
        if k is not None:
            calib_method += " + median car width 1.85 m"
    if k is None:
        k = scale_from_box_sizes(cam, rows)
        if k is not None:
            calib_method += f" + height fitted to detected vehicle box sizes"
    if k is None:
        k = args.default_height                                    # 축척을 못 정하면 기본 높이(화면 위치는 그대로 맞고 3D 크기만 달라진다)
        calib_method += f" + default camera height {k} m (scale not measurable)"
    cam.height = k                                               # 높이 1 단위 = k m
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out / "background.jpg"), bg, [cv2.IMWRITE_JPEG_QUALITY, 92])

    # 노면 정사영: 화면 아래 절반 노면이 보이는 범위
    corners = [cam.ground(u, v) for u, v in [(0, size[1] - 1), (size[0] - 1, size[1] - 1), (0, size[1] * 0.56), (size[0] - 1, size[1] * 0.56)]]
    corners = np.array([c for c in corners if c is not None])
    r0, r1 = float(np.floor(corners[:, 0].min())), float(np.ceil(corners[:, 0].max()))
    f0, f1 = float(np.floor(corners[:, 1].min())), float(min(np.ceil(corners[:, 1].max()), args.max_forward))
    ppm = args.pixels_per_metre
    W, H = int((r1 - r0) * ppm), int((f1 - f0) * ppm)
    # 정사영 화소(i, j) → 노면(right, fwd) → 원본 화소
    jj, ii = np.meshgrid(np.arange(W), np.arange(H))
    right = r0 + (jj + 0.5) / ppm; fwd = f1 - (ii + 0.5) / ppm
    P = right[..., None] * cam.right + fwd[..., None] * cam.fwd - cam.height * cam.up
    Q = P @ cam.K.T
    mapx = (Q[..., 0] / Q[..., 2]).astype(np.float32); mapy = (Q[..., 1] / Q[..., 2]).astype(np.float32)
    ortho = cv2.remap(bg, mapx, mapy, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=(96, 96, 96))
    for x0, y0, x1, y1 in CAPTION_BOXES:                          # 자막이 노면에 찍히지 않게 주변 노면으로 메운다
        inside = (mapx >= x0) & (mapx <= x1) & (mapy >= y0) & (mapy <= y1)
        if inside.any():
            ortho = cv2.inpaint(ortho, inside.astype(np.uint8) * 255, 5, cv2.INPAINT_TELEA)
    cv2.imwrite(str(out / "ground.jpg"), ortho, [cv2.IMWRITE_JPEG_QUALITY, 90])

    # 차량 궤적
    tracks = collections.defaultdict(lambda: {"t": [], "p": [], "cls": collections.Counter()})
    for r in rows:
        for d in r["detections"]:
            x1, y1, x2, y2 = d["bbox_xyxy"]
            g = cam.ground((x1 + x2) / 2, y2)
            if g is None or np.linalg.norm(g) > 120:
                continue
            tr = tracks[d["track_id"]]; tr["t"].append(r["t"]); tr["p"].append(g); tr["cls"][d["class_name"]] += 1
    vehicles = []
    for tid, tr in tracks.items():
        if len(tr["t"]) < args.min_observations:
            continue
        cls = tr["cls"].most_common(1)[0][0]
        sm = smooth_track(tr["t"], tr["p"])
        if sm is None:
            continue
        times, pts = sm
        if np.linalg.norm(pts.max(0) - pts.min(0)) < args.min_motion:
            continue                                               # 움직이지 않는 것(주차 차량·화물·표지)은 배경 화면에 이미 있다
        vel = np.gradient(pts, times, axis=0)
        speed = np.linalg.norm(vel, axis=1)
        heading = np.degrees(np.arctan2(vel[:, 0], vel[:, 1]))
        moving = speed > 0.8
        if moving.any():                                          # 멈춘 동안은 마지막으로 움직일 때의 방향을 유지
            last = heading[np.flatnonzero(moving)[0]]
            for i in range(len(heading)):
                if moving[i]: last = heading[i]
                else: heading[i] = last
        else:
            heading[:] = 0.0
        length, width = SIZES.get(cls, SIZES["car"])
        centres = []
        for p, hd in zip(pts, heading):
            ray = p / (np.linalg.norm(p) + 1e-9)                  # 카메라 발밑 → 차
            body = np.array([np.sin(np.radians(hd)), np.cos(np.radians(hd))])
            depth = 0.5 * (abs(ray @ body) * length + abs(ray[0] * body[1] - ray[1] * body[0]) * width)
            centres.append(p + ray * depth)                        # 박스 밑변(가까운 쪽) → 차체 중심
        centres = np.array(centres)
        vehicles.append({"id": int(tid), "class_name": cls,
                         "samples": [[round(float(t), 3), round(float(c[0]), 2), round(float(c[1]), 2), round(float(h), 1)]
                                     for t, c, h in zip(times, centres, heading)]})
    hazards = []
    for spec in args.hazard:
        kind, _, rest = spec.partition(":"); label, _, xy = rest.rpartition("@") if "@" in rest else ("", "", rest)
        u, v = [float(t) for t in xy.split(",")]
        g = cam.ground(u, v)
        if g is not None:
            hazards.append({"type": kind, "pixel": [u, v], "right_m": round(float(g[0]), 2), "fwd_m": round(float(g[1]), 2),
                            "label": label or kind})
    replay = {
        "source": Path(args.video).name, "duration_s": round(duration, 3), "fps": fps, "image_size": list(size),
        "units": "m", "coordinates": "카메라 바로 아래 노면이 원점. right_m = 카메라 수평 오른쪽, fwd_m = 수평 앞쪽",
        "camera": {"height_m": round(cam.height, 3), "pitch_deg": round(cam.pitch, 3), "roll_deg": round(cam.roll, 3),
                   "vertical_fov_deg": round(float(np.degrees(2 * np.arctan(size[1] / 2 / cam.f))), 3), "focal_px": round(cam.f, 1)},
        "calibration": {"method": calib_method,
                        "width_observations": n_width},
        "ground": {"image": "ground.jpg", "right_m": [r0, r1], "fwd_m": [f0, f1], "pixels_per_metre": ppm},
        "backdrop": {"image": "background.jpg", "distance_m": args.backdrop_distance},
        "vehicles": vehicles,
        "hazards": hazards,
        "note": "정성 재현용. 축척은 표준 차폭 가정에 따른다. 가려진 차·화면 밖 구간은 끊기거나 보간된다.",
    }
    (out / "replay.json").write_text(json.dumps(replay, ensure_ascii=False), encoding="utf8")
    # 검산: 노면 → 화소 → 노면 왕복
    err = max(np.linalg.norm(cam.ground(*cam.pixel(rm, fm)) - [rm, fm]) for rm, fm in [(0, 15), (-8, 30), (10, 25)])
    print(f"camera height {cam.height:.2f} m, pitch {cam.pitch:.2f} deg, roll {cam.roll:.2f} deg, vFOV {replay['camera']['vertical_fov_deg']:.1f} deg, "
          f"width obs {n_width}, ground {W}x{H}px, vehicles {len(vehicles)}, roundtrip err {err:.2e} m")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--tracks", type=Path, required=True, help="프레임별 track_id·class_name·bbox_xyxy JSONL")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pixels-per-metre", type=float, default=12)
    ap.add_argument("--max-forward", type=float, default=70, help="노면 질감을 만들 최대 앞쪽 거리(m)")
    ap.add_argument("--backdrop-distance", type=float, default=150)
    ap.add_argument("--min-observations", type=int, default=12)
    ap.add_argument("--start", type=float, default=0.0, help="이 시각(초)부터만 쓴다(카메라가 바뀌는 영상)")
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--assume-vfov", type=float, default=45.0, help="두 번째 소실점을 못 찾을 때 가정할 세로 화각(도)")
    ap.add_argument("--min-motion", type=float, default=2.0, help="이보다 덜 움직인 궤적(m)은 배경에 있으므로 재현에서 뺀다")
    ap.add_argument("--default-height", type=float, default=8.0, help="차폭으로 축척을 못 정할 때 쓸 카메라 높이(m)")
    ap.add_argument("--mask", action="append", default=[], help="검출·선분에서 뺄 화면 자막 영역 x0,y0,x1,y1(여러 번)")
    ap.add_argument("--hazard", action="append", default=[],
                    help='영상 화소로 위험물 위치 지정. 예: "pothole:물보라 지점(추정)@850,660"')
    args = ap.parse_args()
    CAPTION_BOXES.extend(tuple(int(v) for v in m.split(",")) for m in args.mask)
    build(args)
