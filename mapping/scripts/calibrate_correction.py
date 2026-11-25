"""가상환경 정답으로 박스 아래 가운데 편향 보정의 클래스별 유효 길이를 학습하고, 학습에 안 쓴 차량으로 검증한다.

    python mapping/scripts/calibrate_correction.py <내보내기 폴더> --detections <폴더>/detections_1280.jsonl --road-heading-deg 0
    python mapping/scripts/calibrate_correction.py <내보내기 폴더> --source gt        # YOLO 없이 정답 박스로 학습

- 검출 박스(YOLO)를 정답과 짝지어, 정답 위치에 닿으려면 박스 아래 가운데를 얼마나 밀어야 했는지로 유효 길이를 구한다.
- 보정에 쓰는 클래스는 실제 파이프라인과 같게 정한다: 검출 클래스 그대로, 또는 추적 ID별 다수결.
- 검증: 정답 차량(추적 ID)을 홀짝으로 나눠 한쪽으로 학습하고 다른 쪽으로 평가하는 것을 서로 바꿔 두 번 한다.
  같은 차량이 학습과 평가에 함께 들어가지 않는다.
- 마지막으로 전체 데이터로 다시 학습한 유효 길이를 <내보내기 폴더>/correction.json 에 저장한다.
  evaluate_mapping.py --dims-file 과 CCTV 파이프라인(--correction)이 이 파일을 읽는다.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping import load_detections, load_export, pixels_to_ground  # noqa: E402
from twinsight_mapping.correction import (  # noqa: E402
    DEFAULT_DIMENSIONS,
    TrackClassVoter,
    TrackHeadings,
    bearing_to_vector,
    correct_bottom_center,
    fit_effective_dimensions,
    required_support,
    touches_border,
)
from twinsight_mapping.evaluate import (  # noqa: E402
    bottom_center,
    fit_from_control_points,
    greedy_match,
    summarize,
)

VEHICLE_CLASSES = ("car", "bus", "motorcycle", "truck")
VARIANTS = [  # (이름, 크기표, 보정에 쓰는 클래스)
    ("보정 없음", None, None),
    ("기본 크기 · 검출 클래스", "default", "label"),
    ("기본 크기 · 다수결 클래스", "default", "voted"),
    ("학습 길이 · 검출 클래스", "learned", "label"),
    ("학습 길이 · 다수결 클래스", "learned", "voted"),
]


def collect_observations(export, H, detections, classes, max_distance, road_heading, iou_threshold):
    """프레임 순서대로 보며 보정에 쓸 관측을 모은다. 진행 방향과 다수결은 지난 프레임까지만 쓴다."""
    cam_xz = export.camera.ground_xz
    headings, voter = TrackHeadings(), TrackClassVoter()
    observations = []
    for record in export.frames:
        size = (record["width"], record["height"])
        objects = [o for o in record["objects"]
                   if len(o.get("ground_point_world") or []) == 3 and o["class_name"] in classes]
        if detections is None:
            items = [(o, o["bbox_xyxy"], o["class_name"], o["track_id"], 1.0) for o in objects]
        else:
            dets = [d for d in detections.get(record["frame"], []) if d.get("class_name") in classes]
            pairs = greedy_match([o["bbox_xyxy"] for o in objects], [d["bbox_xyxy"] for d in dets], iou_threshold)
            gt_of = {d: g for g, d, _ in pairs}
            items = [(objects[gt_of[i]] if i in gt_of else None, d["bbox_xyxy"], d.get("class_name"),
                      d.get("track_id"), d.get("confidence", 1.0)) for i, d in enumerate(dets)]

        for obj, bbox, label, track_id, confidence in items:
            voted = voter.update(track_id, label, confidence)
            raw = pixels_to_ground(H, np.array([bottom_center(bbox)]))[0]
            border = touches_border(bbox, *size)
            heading = headings.get(track_id) if border else headings.update(track_id, raw)
            if heading is None:
                heading = road_heading
            if obj is None or obj.get("truncated") or border:
                continue
            gt = np.array([obj["ground_point_world"][0], obj["ground_point_world"][2]])
            distance = float(np.linalg.norm(gt - cam_xz))
            if max_distance is not None and distance > max_distance:
                continue
            observations.append({"gt_track": obj["track_id"], "gt_class": obj["class_name"], "label": label,
                                 "voted": voted, "bbox": bbox, "gt": gt, "heading": heading, "distance": distance})
    return observations


def learn(observations, H):
    """다수결 클래스 기준으로 유효 길이를 학습한다. 반환: (크기표, 클래스별 통계)"""
    samples = []
    for o in observations:
        result = required_support(H, o["bbox"], o["gt"])
        if result is not None:
            samples.append((o["voted"], result[0], result[1], o["heading"]))
    stats = fit_effective_dimensions(samples, DEFAULT_DIMENSIONS)
    dims = dict(DEFAULT_DIMENSIONS)
    for name, s in stats.items():
        dims[name] = (s["length"], s["width"])
    return dims, stats


def error_rows(observations, H, dims, key, cam_xz):
    rows = []
    for o in observations:
        if dims is None:
            est = pixels_to_ground(H, np.array([bottom_center(o["bbox"])]))[0]
        else:
            est = correct_bottom_center(H, o["bbox"], o[key], o["heading"], dims)[1]
        sight = o["gt"] - cam_xz
        err = est - o["gt"]
        rows.append({"gt_class": o["gt_class"], "distance": o["distance"], "error": float(np.linalg.norm(err)),
                     "longitudinal": float(err @ (sight / np.linalg.norm(sight)))})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export_dir", type=Path)
    parser.add_argument("--detections", type=Path, help="detections.jsonl (기본: 폴더 안의 detections.jsonl)")
    parser.add_argument("--source", choices=["detection", "gt"], default="detection",
                        help="detection: YOLO 박스로 학습(기본), gt: 정답 박스로 학습")
    parser.add_argument("--classes", default=",".join(VEHICLE_CLASSES))
    parser.add_argument("--max-distance", type=float, default=80.0)
    parser.add_argument("--road-heading-deg", type=float, help="도로 방향(도). 추적 방향을 아직 모를 때 쓴다")
    parser.add_argument("--iou", type=float, default=0.5)
    parser.add_argument("--n-fit", type=int, default=8, help="Homography에 쓸 기준점 수")
    parser.add_argument("--out", type=Path, help="기본: <내보내기 폴더>/correction.json")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    export = load_export(args.export_dir)
    classes = set(args.classes.split(","))
    H, _ = fit_from_control_points(export.control_points, args.n_fit)
    road = bearing_to_vector(args.road_heading_deg) if args.road_heading_deg is not None else None

    detections = None
    if args.source == "detection":
        det_path = args.detections or args.export_dir / "detections.jsonl"
        if not det_path.exists():
            sys.exit(f"검출 파일이 없습니다: {det_path} (run_yolo_on_frames.py를 먼저 실행하거나 --source gt)")
        detections = load_detections(det_path)

    obs = collect_observations(export, H, detections, classes, args.max_distance, road, args.iou)
    cam_xz = export.camera.ground_xz
    print(f"관측 {len(obs)}개 (차량 {len({o['gt_track'] for o in obs})}대, {args.source} 박스, "
          f"{args.max_distance:g} m 이내)")

    # 2겹 교차 검증: 정답 차량을 홀짝으로 나눠 서로 바꿔 학습·평가
    heldout = {name: [] for name, _, _ in VARIANTS}
    for fold, train_parity in enumerate((0, 1), start=1):
        train = [o for o in obs if o["gt_track"] % 2 == train_parity]
        test = [o for o in obs if o["gt_track"] % 2 != train_parity]
        learned, stats = learn(train, H)
        print(f"\n[겹 {fold}] 학습 {len(train)}개 / 평가 {len(test)}개. 학습한 유효 길이: "
              + ", ".join(f"{k} {v['length']:.2f} m (n={v['n']})" for k, v in sorted(stats.items())))
        for name, dims_kind, key in VARIANTS:
            dims = None if dims_kind is None else (DEFAULT_DIMENSIONS if dims_kind == "default" else learned)
            heldout[name] += error_rows(test, H, dims, key, cam_xz)

    print("\n학습에 쓰지 않은 차량에서의 위치 오차 (m, 두 겹 합산). 종방향 음수 = 카메라 쪽")
    print(f"  {'방식':<26}{'n':>6}{'평균':>8}{'중앙값':>8}{'p95':>8}{'종방향':>8}")
    report = {}
    for name, _, _ in VARIANTS:
        rows = heldout[name]
        stats = summarize(r["error"] for r in rows)
        bias = float(np.mean([r["longitudinal"] for r in rows])) if rows else math.nan
        by_class = {}
        for cls in sorted({r["gt_class"] for r in rows}):
            cls_rows = [r for r in rows if r["gt_class"] == cls]
            by_class[cls] = {"n": len(cls_rows), "mean": float(np.mean([r["error"] for r in cls_rows])),
                             "longitudinal_bias": float(np.mean([r["longitudinal"] for r in cls_rows]))}
        report[name] = {**stats, "longitudinal_bias": bias, "by_class": by_class}
        print(f"  {name:<20}{stats.get('n', 0):>10}{stats.get('mean', math.nan):>8.3f}"
              f"{stats.get('median', math.nan):>8.3f}{stats.get('p95', math.nan):>8.3f}{bias:>8.3f}")

    class_names = sorted({c for v in report.values() for c in v["by_class"]})
    print("\n  정답 클래스별 평균 오차 / 종방향 편향 (m)")
    print("  " + " " * 26 + "".join(f"{c:>18}" for c in class_names))
    for name, _, _ in VARIANTS:
        cells = []
        for c in class_names:
            s = report[name]["by_class"].get(c)
            cells.append(f"{s['mean']:.2f} / {s['longitudinal_bias']:+.2f}" if s else "-")
        print(f"  {name:<20}" + "".join(f"{cell:>18}" for cell in cells))

    # 배포용: 전체 데이터로 다시 학습
    final_dims, final_stats = learn(obs, H)
    out = args.out or args.export_dir / "correction.json"
    data = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "export": str(args.export_dir),
        "source": args.source,
        "detections": str(args.detections or (args.export_dir / "detections.jsonl")) if detections else None,
        "camera": {"position": export.camera.position.tolist(), "image_size": [export.camera.width, export.camera.height]},
        "max_distance_m": args.max_distance,
        "dimensions": {k: [round(v[0], 3), round(v[1], 3)] for k, v in final_dims.items()},
        "fitted": final_stats,
        "heldout": report,
        "note": "dimensions의 길이는 차체 길이가 아니라 박스 아래 가장자리를 만드는 유효 길이다. "
                "학습한 카메라 높이·각도와 비슷한 CCTV에 쓴다.",
    }
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n전체 데이터로 학습한 유효 길이: "
          + ", ".join(f"{k} {v['length']:.2f} m" for k, v in sorted(final_stats.items())))
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
