"""노면 기준점으로 CCTV 카메라의 위치·높이·방향·내려다보는 각도·화각을 구해 가상 CCTV 배치값으로 내보낸다.

    # 실제 CCTV: calibrate_homography.py가 만든 캘리브레이션 파일로 (위도·경도로 찍었으면 카메라 위도·경도도 나옴)
    python mapping/scripts/estimate_camera_pose.py --calibration calibration/utic-아산향산사거리.json
    python mapping/scripts/estimate_camera_pose.py --calibration <파일> --meters-per-unit 2.7   # 가상환경 1단위 = 2.7 m
    python mapping/scripts/estimate_camera_pose.py --calibration <파일> --ground-y 0.507        # 장면 노면이 y=0.507

    # 검증: 정답을 아는 Unity 가상 카메라 내보내기 폴더(camera.json, control_points.json)로
    python mapping/scripts/estimate_camera_pose.py --export simulation/TwinSightSim/TwinSightExport/<폴더>

결과(가상 CCTV 배치값): <캘리브레이션 파일 이름>.pose.json
- position_m: 동(x)·북(z)·노면에서 잰 높이(m), position_latlon: 카메라 위도·경도
- heading_deg: 북쪽에서 동쪽으로 잰 방향, pitch_deg: 아래로 숙인 각도, roll_deg: 좌우 기울기
- vertical_fov_deg / horizontal_fov_deg: 화각
- unity: Unity 카메라에 그대로 넣는 position(y에 노면 높이 포함), eulerAngles, fieldOfView
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping import load_export  # noqa: E402
from twinsight_mapping.calibration import load_calibration  # noqa: E402
from twinsight_mapping.homography import select_spread_points  # noqa: E402
from twinsight_mapping.pose import describe_pose, estimate_camera_pose, pose_report  # noqa: E402


def angle_diff(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def print_report(r: dict) -> None:
    p = r["position_m"]
    print(f"  위치: 동 {p['x_east']:.2f} m, 북 {p['z_north']:.2f} m, 노면에서 높이 {p['height']:.2f} m")
    if r.get("position_latlon"):
        lat, lon = r["position_latlon"]
        print(f"  위도·경도: {lat:.7f}, {lon:.7f}")
    print(f"  방향(북→동) {r['heading_deg']:.1f}°, 내려다보는 각도 {r['pitch_deg']:.1f}°, 좌우 기울기 {r['roll_deg']:.1f}°")
    print(f"  화각: 세로 {r['vertical_fov_deg']:.1f}°, 가로 {r['horizontal_fov_deg']:.1f}° (초점거리 {r['focal_px']:.0f} px)")
    print(f"  기준점 {r['points']}개, 재투영 RMSE {r['rmse_px']:.2f} px")
    loo = r.get("leave_one_out_std")
    if loo:
        print(f"  점 하나를 빼면 흔들리는 정도(표준편차): 높이 {loo['height']:.2f} m, 방향 {loo['heading_deg']:.2f}°, "
              f"각도 {loo['pitch_deg']:.2f}°, 세로 화각 {loo['vertical_fov_deg']:.2f}°")
    u = r["unity"]
    print(f"  Unity: position {[round(v, 3) for v in u['position']]}, eulerAngles "
          f"{[round(v, 2) for v in u['euler_deg']]}, fieldOfView {u['field_of_view']:.2f}"
          + (f" (1단위 = {u['meters_per_unit']:g} m)" if u["meters_per_unit"] != 1 else "")
          + (f" (노면 y = {u['ground_y']:g})" if u["ground_y"] else ""))


def run_calibration(args) -> None:
    data = load_calibration(args.calibration)
    pixels = np.array([p["pixel"] for p in data["points"]], float)
    ground = np.array([p["world_xz"] for p in data["points"]], float)
    size = tuple(data["image_size"])
    focal = (size[1] / 2.0) / math.tan(math.radians(args.fov) / 2.0) if args.fov else None

    report = pose_report(pixels, ground, size, camera_id=data.get("camera_id"), origin_latlon=data.get("origin_latlon"),
                         meters_per_unit=args.meters_per_unit, ground_y=args.ground_y, focal=focal)
    report["calibration"] = str(Path(args.calibration).resolve())
    out = args.out or Path(args.calibration).with_suffix(".pose.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"카메라 {report['camera_id']} 자세")
    print_report(report)
    if report["rmse_px"] > 3.0:
        print("⚠️ 재투영 오차가 3 px를 넘습니다. 잘못 찍은 점이나 노면이 아닌 점이 섞였는지 확인하세요.")
    loo = report.get("leave_one_out_std")
    if loo is None:
        print("⚠️ 점이 6개 미만이라 결과가 얼마나 믿을 만한지 확인할 수 없습니다.")
    elif loo["height"] > 1.0 or loo["pitch_deg"] > 2.0:
        print("⚠️ 점 하나에 따라 결과가 크게 흔들립니다. 화면 전체에 고르게 퍼진 점을 더 찍으세요.")
    print(f"저장: {out}")


def run_validation(args) -> None:
    export = load_export(args.export)
    truth = json.loads((Path(args.export) / "camera.json").read_text(encoding="utf-8"))
    size = (truth["image_width"], truth["image_height"])
    tx, ty, tz = truth["position"]
    t_pitch, t_heading, t_roll = truth["rotation_euler_deg"]
    t_vfov = truth["vertical_fov_deg"]

    cp = export.control_points
    usable = cp.in_frame & (np.linalg.norm(cp.ground - export.camera.ground_xz, axis=1) <= args.max_distance)
    pixels_all, ground_all = cp.pixel[usable], cp.ground[usable]
    # 기준점은 노면 위에 있다. 노면이 y=0이 아닌 장면(City Lab)에서는 높이를 노면에서 잰다
    point_y = cp.world[usable, 1]
    ground_y = float(np.median(point_y)) if len(point_y) else 0.0
    t_height = ty - ground_y
    print(f"정답 카메라: 위치 ({tx:.2f}, {tz:.2f}) m, 노면에서 높이 {t_height:.2f} m (Unity y {ty:.2f}, 노면 y "
          f"{ground_y:.3f}), 방향 {t_heading:.1f}°, 각도 {t_pitch:.1f}°, 세로 화각 {t_vfov:.1f}°")
    print(f"사용할 수 있는 기준점 {int(usable.sum())}개 (화면 안, 카메라에서 {args.max_distance:g} m 이내)")
    if len(point_y) and float(np.ptp(point_y)) > 0.05:
        print(f"⚠️ 기준점 높이가 {float(np.ptp(point_y)):.2f}만큼 서로 다릅니다. 평평한 노면 가정이 맞지 않을 수 있습니다.")

    focal = (size[1] / 2.0) / math.tan(math.radians(args.fov) / 2.0) if args.fov else None
    if focal:
        print(f"세로 화각을 {args.fov:g}°로 고정합니다")

    def errors(pixels, ground) -> dict:
        d = describe_pose(estimate_camera_pose(pixels, ground, size, focal), size, ground_y=ground_y)
        p = d["position_m"]
        return {
            "position_m": math.hypot(p["x_east"] - tx, p["z_north"] - tz),
            "height_m": p["height"] - t_height,
            "heading_deg": angle_diff(d["heading_deg"], t_heading),
            "pitch_deg": d["pitch_deg"] - t_pitch,
            "roll_deg": angle_diff(d["roll_deg"], t_roll),
            "vfov_deg": d["vertical_fov_deg"] - t_vfov,
            # 가상 CCTV에 그대로 넣는 Unity position이 정답 카메라 자리와 얼마나 떨어졌는지
            "unity_position": float(np.linalg.norm(np.array(d["unity"]["position"]) - [tx, ty, tz])),
        }

    exact = errors(pixels_all, ground_all)
    print("\n[1] 정확한 기준점 전부 사용: " + ", ".join(f"{k} {v:+.4f}" for k, v in exact.items()))

    rng = np.random.default_rng(args.seed)
    n_points = [int(v) for v in args.n_points.split(",")]
    noises = [float(v) for v in args.pixel_noise.split(",")]
    rows = []
    for n in n_points:
        idx = select_spread_points(pixels_all, n)
        for noise in noises:
            trial_errors = []
            for _ in range(args.trials if noise > 0 or args.world_noise else 1):
                pixels = pixels_all[idx] + (rng.normal(0.0, noise, (len(idx), 2)) if noise > 0 else 0.0)
                ground = ground_all[idx] + (rng.normal(0.0, args.world_noise, (len(idx), 2)) if args.world_noise else 0.0)
                try:
                    trial_errors.append(errors(pixels, ground))
                except ValueError:
                    continue
            if not trial_errors:
                continue
            keys = trial_errors[0].keys()
            summary = {k: {"median_abs": float(np.median([abs(e[k]) for e in trial_errors])),
                           "p95_abs": float(np.percentile([abs(e[k]) for e in trial_errors], 95))} for k in keys}
            # 방향이 10° 넘게 틀리거나 높이가 2 m 넘게 틀린 실행은 '크게 실패'로 센다
            failures = sum(1 for e in trial_errors if abs(e["heading_deg"]) > 10 or abs(e["height_m"]) > 2)
            rows.append({"n_points": n, "pixel_noise": noise, "trials": len(trial_errors),
                         "failure_rate": failures / len(trial_errors), "errors": summary})

    print("\n[2] 기준점 수 x 클릭 오차별 절대오차 중앙값 (괄호: p95)"
          + (f", 기준점 좌표 오차 {args.world_noise:g} m" if args.world_noise else ""))
    print(f"  {'점':>3} {'오차px':>6} {'위치 m':>14} {'높이 m':>14} {'방향 °':>14} {'각도 °':>14} {'세로화각 °':>14}"
          f" {'크게 실패':>9}")
    for r in rows:
        e = r["errors"]
        cells = [f"{e[k]['median_abs']:.2f} ({e[k]['p95_abs']:.2f})"
                 for k in ("position_m", "height_m", "heading_deg", "pitch_deg", "vfov_deg")]
        print(f"  {r['n_points']:>3} {r['pixel_noise']:>6g} " + "".join(f"{c:>14}" for c in cells)
              + f"{r['failure_rate']:>9.0%}")

    out = args.out or Path(args.export) / "pose_eval" / "pose_validation.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "truth": {"position": truth["position"], "rotation_euler_deg": truth["rotation_euler_deg"],
                  "vertical_fov_deg": t_vfov, "image_size": list(size), "ground_y": ground_y,
                  "height_above_ground": t_height},
        "max_distance_m": args.max_distance,
        "world_noise_m": args.world_noise,
        "exact_all_points": exact,
        "sweep": rows,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n저장: {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--calibration", type=Path, help="calibrate_homography.py가 만든 캘리브레이션 JSON")
    source.add_argument("--export", type=Path, help="검증용 Unity 내보내기 폴더")
    parser.add_argument("--out", type=Path, help="결과 JSON 경로")
    parser.add_argument("--meters-per-unit", type=float, default=1.0, help="가상환경 1단위가 몇 m인지(Unity 값에만 적용)")
    parser.add_argument("--ground-y", type=float, default=0.0,
                        help="가상 CCTV를 놓을 장면의 노면 높이(Unity y). Unity position의 y에 더한다. City Lab 도로는 약 0.507")
    parser.add_argument("--fov", type=float, help="CCTV 세로 화각을 알면 고정(도)")
    parser.add_argument("--n-points", default="4,6,8,12", help="검증: 기준점 수 목록")
    parser.add_argument("--pixel-noise", default="0,1,2,4", help="검증: 클릭 오차(px) 목록")
    parser.add_argument("--trials", type=int, default=50, help="검증: 조합마다 반복 횟수")
    parser.add_argument("--max-distance", type=float, default=60.0, help="검증: 카메라에서 이 거리(m) 안의 기준점만")
    parser.add_argument("--world-noise", type=float, default=0.0,
                        help="검증: 기준점 실제 좌표 오차(m, 표준편차). 지도에서 위도·경도를 읽는 오차를 흉내 낸다")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if args.calibration:
        run_calibration(args)
    else:
        run_validation(args)


if __name__ == "__main__":
    main()
