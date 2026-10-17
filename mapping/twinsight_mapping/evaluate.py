"""가상환경 정답으로 공간 매핑 오차를 잰다.

객체 위치 오차는 세 가지 방식으로 구한다.
- ground_pixel: 정답 바닥점의 픽셀을 그대로 변환. Homography 자체(평면 가정·기준점)의 오차만 남는다.
- bbox_bottom: 정답 박스의 아래 가운데 점을 변환. 검출이 완벽해도 생기는 기준점 위치 오차가 더해진다.
- detection: YOLO 검출 박스의 아래 가운데 점을 변환. 검출 오차까지 포함한 실제 파이프라인의 오차.

bbox_bottom, detection에는 카메라 쪽 편향을 보정한 결과(correction.py)도 함께 낸다.
- +view: 차량이 카메라 깊이 방향을 향한다고 가정(진행 방향 정보 없음)
- +track: 추적 ID로 구한 이동 방향 사용(아직 충분히 움직이지 않았으면 +view와 같음)
- +road: 주어진 도로 방향 사용
"""

from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from .correction import TrackHeadings, correct_bottom_center, touches_border
from .dataset import ControlPoints, Export
from .homography import fit_homography, pixels_to_ground, select_spread_points

DISTANCE_BINS = (0.0, 20.0, 40.0, 60.0, 80.0, math.inf)
CORRECTIONS = ("view", "track", "road")
MODES = ("ground_pixel",
         "bbox_bottom", *(f"bbox_bottom+{c}" for c in CORRECTIONS),
         "detection", *(f"detection+{c}" for c in CORRECTIONS))


def summarize(errors) -> dict:
    errors = np.asarray([e for e in errors if np.isfinite(e)], dtype=float)
    if errors.size == 0:
        return {"n": 0}
    return {
        "n": int(errors.size),
        "mean": float(errors.mean()),
        "median": float(np.median(errors)),
        "p90": float(np.percentile(errors, 90)),
        "p95": float(np.percentile(errors, 95)),
        "max": float(errors.max()),
    }


def check_camera_consistency(export: Export) -> float | None:
    """camera.json으로 기준점을 다시 투영했을 때 내보낸 픽셀과의 최대 차이(px)."""
    cp = export.control_points
    if export.camera.Rt is None or not cp.in_frame.any():
        return None
    projected = export.camera.project(cp.world[cp.in_frame])
    return float(np.nanmax(np.linalg.norm(projected - cp.pixel[cp.in_frame], axis=1)))


def usable_control_points(export: Export, max_distance: float | None = None) -> np.ndarray:
    """화면 안에 있고, 카메라에서 max_distance(m) 안에 있는 기준점 마스크."""
    cp = export.control_points
    usable = cp.in_frame.copy()
    if max_distance is not None:
        usable &= np.linalg.norm(cp.ground - export.camera.ground_xz, axis=1) <= max_distance
    return usable


def fit_from_control_points(cp: ControlPoints, n_fit: int, pixel_noise: float = 0.0,
                            rng: np.random.Generator | None = None,
                            usable: np.ndarray | None = None) -> tuple[np.ndarray, np.ndarray]:
    """쓸 수 있는 기준점(기본: 화면 안 전부) 중 고르게 퍼진 n_fit개로 Homography를 구한다.

    pixel_noise(px)는 사람이 화면에서 점을 찍을 때의 오차를 흉내 낸다.
    반환: (H, 사용한 기준점 인덱스)
    """
    candidates = np.flatnonzero(cp.in_frame if usable is None else usable)
    fit_idx = candidates[select_spread_points(cp.pixel[candidates], n_fit)]
    pixels = cp.pixel[fit_idx].copy()
    if pixel_noise > 0:
        rng = rng or np.random.default_rng()
        pixels += rng.normal(0.0, pixel_noise, pixels.shape)
    return fit_homography(pixels, cp.ground[fit_idx]), fit_idx


def control_point_errors(cp: ControlPoints, H: np.ndarray, fit_idx: np.ndarray,
                         usable: np.ndarray | None = None) -> np.ndarray:
    """Homography에 쓰지 않은 기준점(기본: 화면 안 전부)의 노면 오차(m)."""
    held_out = np.setdiff1d(np.flatnonzero(cp.in_frame if usable is None else usable), fit_idx)
    if held_out.size == 0:
        return np.empty(0)
    estimated = pixels_to_ground(H, cp.pixel[held_out])
    return np.linalg.norm(estimated - cp.ground[held_out], axis=1)


def bottom_center(bbox) -> tuple[float, float]:
    x1, _, x2, y2 = bbox
    return (x1 + x2) / 2.0, y2


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float).reshape(-1, 4)
    b = np.asarray(b, dtype=float).reshape(-1, 4)
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(union > 0, inter / union, 0.0)


def greedy_match(gt_boxes, det_boxes, threshold: float) -> list[tuple[int, int, float]]:
    """IoU가 큰 쌍부터 하나씩 짝짓는다. 반환: [(정답 인덱스, 검출 인덱스, IoU)]"""
    if len(gt_boxes) == 0 or len(det_boxes) == 0:
        return []
    ious = iou_matrix(gt_boxes, det_boxes)
    pairs = []
    used_gt, used_det = set(), set()
    for flat in np.argsort(-ious, axis=None):
        g, d = np.unravel_index(flat, ious.shape)
        if ious[g, d] < threshold:
            break
        if g in used_gt or d in used_det:
            continue
        used_gt.add(g)
        used_det.add(d)
        pairs.append((int(g), int(d), float(ious[g, d])))
    return pairs


def object_errors(export: Export, H: np.ndarray, detections: dict[int, list[dict]] | None = None,
                  classes: set[str] | None = None, iou_threshold: float = 0.5,
                  max_distance: float | None = None, dimensions: dict | None = None,
                  road_heading: np.ndarray | None = None) -> tuple[list[dict], dict | None]:
    """객체마다 매핑 오차 행을 만든다. 화면 경계에서 잘린 객체는 매핑 오차에서 뺀다.

    max_distance(m)를 주면 카메라에서 그보다 먼 객체는 검출 통계와 오차 모두에서 뺀다.
    짝이 없는 검출은 Homography로 구한 위치가 max_distance 안일 때만 오검출로 센다.
    dimensions는 클래스별 (길이, 폭), road_heading은 도로 방향 단위벡터(x, z)이다.

    반환: (오차 행 목록, 검출 통계 또는 None)
    """
    cam_xz = export.camera.ground_xz
    rows: list[dict] = []
    det_stats = {"gt": 0, "detections": 0, "matched": 0, "iou_sum": 0.0} if detections is not None else None
    gt_headings, det_headings = TrackHeadings(), TrackHeadings()

    def in_range(xz) -> bool:
        return max_distance is None or bool(np.hypot(*(np.asarray(xz) - cam_xz)) <= max_distance)

    def box_rows(base: str, frame: int, obj: dict, bbox, class_name: str, track_id,
                 headings: TrackHeadings, record_rows: bool, image_size) -> None:
        # 진행 방향은 보정 전 위치로 추적한다. 먼 객체도 이동 기록에 넣지만,
        # 화면 가장자리에 닿은 박스는 아래 가장자리가 잘렸을 수 있어 넣지 않는다.
        raw, corrected = correct_bottom_center(H, bbox, class_name, None, dimensions)
        if touches_border(bbox, *image_size):
            heading = headings.get(track_id)
        else:
            heading = headings.update(track_id, raw)
        if not record_rows or obj.get("truncated"):
            return
        gt = np.array([obj["ground_point_world"][0], obj["ground_point_world"][2]])
        rows.append(_error_row(base, frame, obj, gt, raw, cam_xz))
        rows.append(_error_row(f"{base}+view", frame, obj, gt, corrected, cam_xz))
        if heading is not None:
            corrected = correct_bottom_center(H, bbox, class_name, heading, dimensions)[1]
        rows.append(_error_row(f"{base}+track", frame, obj, gt, corrected, cam_xz))
        if road_heading is not None:
            by_road = correct_bottom_center(H, bbox, class_name, road_heading, dimensions)[1]
            rows.append(_error_row(f"{base}+road", frame, obj, gt, by_road, cam_xz))

    for record in export.frames:
        frame = record["frame"]
        image_size = (record["width"], record["height"])
        objects = [o for o in record["objects"]
                   if len(o.get("ground_point_world") or []) == 3
                   and (classes is None or o["class_name"] in classes)]
        near = [in_range(np.array(o["ground_point_world"])[[0, 2]]) for o in objects]

        for obj, is_near in zip(objects, near):
            if is_near and obj.get("ground_point_in_frame") and not obj.get("truncated"):
                gt = np.array([obj["ground_point_world"][0], obj["ground_point_world"][2]])
                est = pixels_to_ground(H, np.array([obj["ground_point_pixel"]]))[0]
                rows.append(_error_row("ground_pixel", frame, obj, gt, est, cam_xz))
            box_rows("bbox_bottom", frame, obj, obj["bbox_xyxy"], obj["class_name"], obj["track_id"],
                     gt_headings, is_near, image_size)

        if detections is None:
            continue
        dets = [d for d in detections.get(record["frame"], [])
                if classes is None or d.get("class_name") in classes]
        # 먼 객체까지 포함해 짝지은 뒤, 가까운 정답과 짝지어진 검출만 센다
        pairs = greedy_match([o["bbox_xyxy"] for o in objects], [d["bbox_xyxy"] for d in dets], iou_threshold)
        matched_dets = {d for _, d, _ in pairs}
        unmatched_near = sum(
            1 for i, d in enumerate(dets)
            if i not in matched_dets and in_range(pixels_to_ground(H, [bottom_center(d["bbox_xyxy"])])[0]))
        near_pairs = [(g, d, iou) for g, d, iou in pairs if near[g]]
        det_stats["gt"] += sum(near)
        det_stats["detections"] += len(near_pairs) + unmatched_near
        det_stats["matched"] += len(near_pairs)
        det_stats["iou_sum"] += sum(iou for _, _, iou in near_pairs)
        gt_of_det = {d: g for g, d, _ in pairs}
        for i, det in enumerate(dets):
            # 보정에는 실제 파이프라인처럼 검출된 클래스와 검출기의 추적 ID를 쓴다
            g = gt_of_det.get(i)
            box_rows("detection", frame, objects[g] if g is not None else {}, det["bbox_xyxy"],
                     det.get("class_name"), det.get("track_id"), det_headings, g is not None and near[g],
                     image_size)

    if det_stats is not None:
        matched = det_stats["matched"]
        det_stats["recall"] = matched / det_stats["gt"] if det_stats["gt"] else None
        det_stats["precision"] = matched / det_stats["detections"] if det_stats["detections"] else None
        det_stats["mean_iou"] = det_stats.pop("iou_sum") / matched if matched else None
        det_stats["iou_threshold"] = iou_threshold
    return rows, det_stats


def _error_row(mode: str, frame: int, obj: dict, gt: np.ndarray, est: np.ndarray, cam_xz: np.ndarray) -> dict:
    # 카메라에서 객체로 향하는 방향 기준으로 오차를 앞뒤(종방향)와 좌우(횡방향)로 나눈다
    sight = gt - cam_xz
    distance = float(np.linalg.norm(sight))
    along = sight / distance if distance > 0 else np.array([0.0, 1.0])
    right = np.array([along[1], -along[0]])
    err = est - gt
    return {
        "mode": mode,
        "frame": frame,
        "track_id": obj["track_id"],
        "class_name": obj["class_name"],
        "distance_m": distance,
        "gt_x": float(gt[0]),
        "gt_z": float(gt[1]),
        "est_x": float(est[0]),
        "est_z": float(est[1]),
        "error_m": float(np.linalg.norm(err)),
        "longitudinal_m": float(err @ along),  # 음수면 실제보다 카메라 쪽으로 추정
        "lateral_m": float(err @ right),  # 양수면 시선 기준 오른쪽으로 추정
    }


def summarize_rows(rows: list[dict]) -> dict:
    """모드별 전체 통계, 거리 구간별 통계, 클래스별 통계."""
    by_mode: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_mode[row["mode"]].append(row)

    summary = {}
    for mode in MODES:
        mode_rows = by_mode.get(mode)
        if not mode_rows:
            continue
        overall = summarize(r["error_m"] for r in mode_rows)
        overall["longitudinal_bias"] = _finite_mean(r["longitudinal_m"] for r in mode_rows)
        overall["lateral_bias"] = _finite_mean(r["lateral_m"] for r in mode_rows)
        bins = {}
        for lo, hi in zip(DISTANCE_BINS[:-1], DISTANCE_BINS[1:]):
            label = f"{lo:.0f}-{hi:.0f}m" if math.isfinite(hi) else f"{lo:.0f}m+"
            stats = summarize(r["error_m"] for r in mode_rows if lo <= r["distance_m"] < hi)
            if stats["n"]:
                stats["longitudinal_bias"] = _finite_mean(
                    r["longitudinal_m"] for r in mode_rows if lo <= r["distance_m"] < hi)
                bins[label] = stats
        by_class = {}
        for cls in sorted({r["class_name"] for r in mode_rows}):
            cls_rows = [r for r in mode_rows if r["class_name"] == cls]
            stats = summarize(r["error_m"] for r in cls_rows)
            stats["longitudinal_bias"] = _finite_mean(r["longitudinal_m"] for r in cls_rows)
            by_class[cls] = stats
        summary[mode] = {"overall": overall, "by_distance": bins, "by_class": by_class}
    return summary


def sweep(cp: ControlPoints, n_fits, noises, trials: int = 50, seed: int = 0,
          usable: np.ndarray | None = None) -> list[dict]:
    """기준점 수와 클릭 오차에 따라 매핑 정확도가 어떻게 바뀌는지 본다."""
    rng = np.random.default_rng(seed)
    results = []
    for n_fit in n_fits:
        for noise in noises:
            means, p95s = [], []
            for _ in range(trials if noise > 0 else 1):
                H, fit_idx = fit_from_control_points(cp, n_fit, noise, rng, usable)
                stats = summarize(control_point_errors(cp, H, fit_idx, usable))
                if stats["n"]:
                    means.append(stats["mean"])
                    p95s.append(stats["p95"])
            results.append({
                "n_fit": n_fit,
                "pixel_noise": noise,
                "trials": len(means),
                "mean_m": float(np.mean(means)) if means else math.nan,
                "p95_m": float(np.mean(p95s)) if p95s else math.nan,
            })
    return results


def _finite_mean(values) -> float | None:
    values = [v for v in values if np.isfinite(v)]
    return float(np.mean(values)) if values else None
