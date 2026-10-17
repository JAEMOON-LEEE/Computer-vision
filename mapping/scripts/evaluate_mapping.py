"""가상환경 내보내기 폴더로 공간 매핑(Homography) 정확도를 평가한다.

    python mapping/scripts/evaluate_mapping.py <내보내기 폴더>
    python mapping/scripts/evaluate_mapping.py <내보내기 폴더> --n-fit 8 --pixel-noise 2 --sweep

폴더에 detections.jsonl이 있으면 YOLO 검출 결과로 구한 위치 오차도 함께 계산한다.
박스 아래 가운데 방식에는 카메라 쪽 편향을 보정한 결과도 함께 낸다(--road-heading-deg를 주면 도로 방향 보정 포함).
결과는 <내보내기 폴더>/mapping_eval/ 에 저장한다.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import unicodedata
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping import load_detections, load_export  # noqa: E402
from twinsight_mapping.correction import bearing_to_vector, parse_dimensions  # noqa: E402
from twinsight_mapping.evaluate import (  # noqa: E402
    DISTANCE_BINS,
    MODES,
    check_camera_consistency,
    control_point_errors,
    fit_from_control_points,
    object_errors,
    summarize,
    summarize_rows,
    sweep,
    usable_control_points,
)

CORRECTION_LABELS = {"view": "시선 방향 가정", "track": "추적 방향", "road": "도로 방향"}
MODE_LABELS = {
    "ground_pixel": "정답 바닥점",
    "bbox_bottom": "정답 박스 아래 가운데",
    "detection": "YOLO 박스 아래 가운데",
}
for _base in ("bbox_bottom", "detection"):
    for _key, _label in CORRECTION_LABELS.items():
        MODE_LABELS[f"{_base}+{_key}"] = f"  + 보정 ({_label})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("export_dir", type=Path)
    parser.add_argument("--n-fit", type=int, default=6, help="Homography에 쓸 기준점 수 (기본 6)")
    parser.add_argument("--pixel-noise", type=float, default=0.0, help="기준점 클릭 오차 표준편차(px)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--detections", type=Path, help="detections.jsonl (기본: 폴더 안의 파일)")
    parser.add_argument("--classes", help="평가할 클래스, 쉼표로 구분 (예: car,truck,bus)")
    parser.add_argument("--iou", type=float, default=0.5, help="검출-정답 짝짓기 IoU 기준")
    parser.add_argument("--max-distance", type=float,
                        help="카메라에서 이 거리(m) 안의 기준점·객체만 쓴다. 먼 구간을 빼고 볼 때")
    parser.add_argument("--road-heading-deg", type=float,
                        help="도로 방향(도, +z에서 +x 쪽으로. 예제 씬은 0). 주면 도로 방향 보정도 계산")
    parser.add_argument("--dims", help="클래스별 차량 크기 덮어쓰기 (예: car=4.5x1.8,truck=8x2.5)")
    parser.add_argument("--sweep", action="store_true", help="기준점 수 x 클릭 오차 조합별 정확도표도 만든다")
    parser.add_argument("--out", type=Path, help="결과 폴더 (기본: <내보내기 폴더>/mapping_eval)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    export = load_export(args.export_dir)
    cp = export.control_points
    out_dir = args.out or args.export_dir / "mapping_eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    classes = set(args.classes.split(",")) if args.classes else None

    print(f"카메라 {export.camera.camera_id}: 기준점 {len(cp.ids)}개 (화면 안 {int(cp.in_frame.sum())}개), "
          f"프레임 {len(export.frames)}개")

    consistency = check_camera_consistency(export)
    if consistency is not None:
        flag = "정상" if consistency < 1.0 else "확인 필요: camera.json과 기준점 픽셀이 맞지 않습니다"
        print(f"카메라 정보 재투영 최대 오차: {consistency:.3f} px ({flag})")

    usable = usable_control_points(export, args.max_distance)
    rng = np.random.default_rng(args.seed)
    H, fit_idx = fit_from_control_points(cp, args.n_fit, args.pixel_noise, rng, usable)
    cp_stats = summarize(control_point_errors(cp, H, fit_idx, usable))
    within = f", {args.max_distance:g} m 이내" if args.max_distance else ""
    print(f"\n[1] Homography: 기준점 {len(fit_idx)}개로 계산, 클릭 오차 {args.pixel_noise:g} px{within}")
    print(f"    사용하지 않은 기준점 {cp_stats['n']}개의 노면 오차: {_stats_line(cp_stats)}")

    detections = None
    det_path = args.detections or (args.export_dir / "detections.jsonl")
    if det_path.exists():
        detections = load_detections(det_path)
    dimensions = parse_dimensions(args.dims)
    road_heading = bearing_to_vector(args.road_heading_deg) if args.road_heading_deg is not None else None
    rows, det_stats = object_errors(export, H, detections, classes, args.iou, args.max_distance,
                                    dimensions=dimensions, road_heading=road_heading)
    summary = summarize_rows(rows)
    modes = [m for m in MODES if m in summary]

    print("\n[2] 객체 위치 오차 (m). 종방향 편향이 음수면 실제보다 카메라 쪽으로 추정")
    print("    보정에 쓴 차량 크기(길이x폭): "
          + ", ".join(f"{k} {v[0]:g}x{v[1]:g}" for k, v in dimensions.items()))
    print("  " + _pad("방식", 28) + "".join(f"{h:>9}" for h in ("n", "평균", "중앙값", "p95", "종방향", "횡방향")))
    for mode in modes:
        o = summary[mode]["overall"]
        print("  " + _pad(MODE_LABELS[mode], 28) + f"{o['n']:>9}" + "".join(
            f"{_fmt(v):>9}" for v in (o["mean"], o["median"], o["p95"], o["longitudinal_bias"], o["lateral_bias"])))

    bin_labels = [f"{lo:.0f}-{hi:.0f}m" if math.isfinite(hi) else f"{lo:.0f}m+"
                  for lo, hi in zip(DISTANCE_BINS[:-1], DISTANCE_BINS[1:])]
    bin_labels = [b for b in bin_labels if any(b in summary[m]["by_distance"] for m in modes)]
    print("\n  거리 구간별 평균 오차 (m)")
    print("  " + _pad("방식", 28) + "".join(f"{b:>9}" for b in bin_labels))
    for mode in modes:
        bins = summary[mode]["by_distance"]
        print("  " + _pad(MODE_LABELS[mode], 28)
              + "".join(f"{_fmt(bins[b]['mean']) if b in bins else '-':>9}" for b in bin_labels))

    class_names = sorted({c for m in modes if m != "ground_pixel" for c in summary[m]["by_class"]})
    print("\n  클래스별 평균 오차 / 종방향 편향 (m)")
    print("  " + _pad("방식", 28) + "".join(f"{c:>18}" for c in class_names))
    for mode in modes:
        if mode == "ground_pixel":
            continue
        by_class = summary[mode]["by_class"]
        cells = [f"{_fmt(by_class[c]['mean'])} / {_fmt(by_class[c]['longitudinal_bias'])}" if c in by_class else "-"
                 for c in class_names]
        print("  " + _pad(MODE_LABELS[mode], 28) + "".join(f"{cell:>18}" for cell in cells))

    if det_stats:
        print(f"\n[3] 검출 (IoU >= {args.iou}): 정답 {det_stats['gt']}개, 검출 {det_stats['detections']}개, "
              f"짝지어짐 {det_stats['matched']}개, 재현율 {_fmt(det_stats['recall'])}, "
              f"정밀도 {_fmt(det_stats['precision'])}, 평균 IoU {_fmt(det_stats['mean_iou'])}")
    elif detections is None:
        print("\n[3] detections.jsonl이 없어 YOLO 검출 기반 오차는 건너뜁니다")

    sweep_rows = None
    if args.sweep:
        sweep_rows = sweep(cp, n_fits=(4, 6, 8, 12, 16), noises=(0.0, 1.0, 2.0, 4.0), seed=args.seed,
                           usable=usable)
        print("\n[4] 기준점 수 x 클릭 오차별 노면 오차 (사용하지 않은 기준점, 평균 / p95, m)")
        noises = sorted({r["pixel_noise"] for r in sweep_rows})
        print("      기준점 " + "".join(f"{f'{n:g}px':>16}" for n in noises))
        for n_fit in sorted({r["n_fit"] for r in sweep_rows}):
            cells = [r for r in sweep_rows if r["n_fit"] == n_fit]
            print(f"      {n_fit:>6} " + "".join(f"{_fmt(r['mean_m']):>8}/{_fmt(r['p95_m']):<7}" for r in cells))

    report = {
        "export_dir": str(args.export_dir),
        "camera_id": export.camera.camera_id,
        "camera_reprojection_max_px": consistency,
        "max_distance_m": args.max_distance,
        "homography": {
            "n_fit": len(fit_idx),
            "pixel_noise": args.pixel_noise,
            "fit_control_point_ids": cp.ids[fit_idx].tolist(),
            "matrix_pixel_to_ground": H.tolist(),
            "held_out_error_m": cp_stats,
        },
        "correction": {
            "dimensions": {k: list(v) for k, v in dimensions.items()},
            "road_heading_deg": args.road_heading_deg,
        },
        "objects": summary,
        "detection": det_stats,
        "sweep": sweep_rows,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if rows:
        with open(out_dir / "object_errors.csv", "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    print(f"\n저장: {out_dir}")


def _stats_line(stats: dict) -> str:
    if not stats.get("n"):
        return "데이터 없음"
    return (f"n={stats['n']}, 평균 {_fmt(stats['mean'])}, 중앙값 {_fmt(stats['median'])}, "
            f"p95 {_fmt(stats['p95'])}, 최대 {_fmt(stats['max'])}")


def _pad(text: str, width: int) -> str:
    """한글처럼 두 칸을 차지하는 글자를 고려해 오른쪽을 공백으로 채운다."""
    shown = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(0, width - shown)


def _fmt(value) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "-"
    return f"{value:.3f}"


if __name__ == "__main__":
    main()
