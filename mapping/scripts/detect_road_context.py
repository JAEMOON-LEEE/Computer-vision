"""고정 CCTV 프레임에서 OpenCV로 도로·차선·정지선(횡단보도)을 찾아 팀 경고 엔진 형식 road-context.json을 만든다.

    # 실제 CCTV: 캘리브레이션 + 원본 프레임 여러 장(차량이 지워지도록 30초 이상에 걸친 것)
    python mapping/scripts/detect_road_context.py --calibration calibration/<카메라ID>.json \
        --frames "captures/<카메라ID>_*.png" --ignore 0.24,0.86,0.77,1 --polygon-far 170

    # Unity 내보내기(camera.json·control_points.json·frames/). City Lab은 1단위 ≈ 2.92 m
    python mapping/scripts/detect_road_context.py --export simulation/TwinSightSim/TwinSightExport/<폴더> --meters-per-unit 2.92

결과: road-context.json (road_polygon, stop_zones: 0~1 이미지 좌표) + 확인용 그림(*_overlay.jpg)
    python -m detection predict --source <영상> --alerts --context road-context.json
- --ignore x0,y0,x1,y1: 분석에서 뺄 화면 영역(0~1). CCTV 화면 글자(카메라 이름·방향 표시) 위치를 준다. 여러 번 줄 수 있다.
- --polygon-far: 도로 영역을 선이 확인된 곳보다 먼 곳까지 곧게 늘릴 거리(m, 직선 구간만).
- --export 모드는 정답 차량 바닥점이 도로 영역 안에 드는 비율도 출력한다. --detections를 주면 검출 결과로도 잰다.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping import load_export  # noqa: E402
from twinsight_mapping.calibration import load_calibration, read_image, write_image  # noqa: E402
from twinsight_mapping.road import GroundPlane, analyse_road, build_context, draw_context, median_background  # noqa: E402

VEHICLES = {"car", "truck", "bus", "motorcycle", "bicycle"}


def inside(point, polygon) -> bool:
    """detection/warnings.py와 같은 점-다각형 판정."""
    x, y = point
    result, previous = False, polygon[-1]
    for current in polygon:
        (ax, ay), (bx, by) = previous, current
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            result = not result
        previous = current
    return result


def sample(paths: list[str], limit: int) -> list[str]:
    if len(paths) <= limit:
        return paths
    idx = np.linspace(0, len(paths) - 1, limit).round().astype(int)
    return [paths[i] for i in idx]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--calibration", type=Path, help="calibrate_homography.py가 만든 캘리브레이션 JSON")
    source.add_argument("--export", type=Path, help="Unity 내보내기 폴더(camera.json, control_points.json, frames/)")
    parser.add_argument("--frames", nargs="*", help="원본 프레임(파일·glob). --export면 기본 frames/*.jpg")
    parser.add_argument("--max-frames", type=int, default=40, help="중앙값에 쓸 프레임 수(고르게 뽑음)")
    parser.add_argument("--meters-per-unit", type=float, default=1.0, help="노면 좌표 1단위가 몇 m인지(City Lab 약 2.92)")
    parser.add_argument("--max-distance", type=float, default=90.0, help="선을 찾을 최대 거리(m). 멀수록 위에서 본 그림이 흐려진다")
    parser.add_argument("--polygon-far", type=float, help="도로 영역을 이 거리(m)까지 곧게 늘린다")
    parser.add_argument("--lateral", type=float, default=25.0, help="도로 중심에서 좌우로 볼 범위(m)")
    parser.add_argument("--ignore", action="append", default=[], help="분석에서 뺄 화면 영역 x0,y0,x1,y1 (0~1). 여러 번 가능")
    parser.add_argument("--shoulder", type=float, default=0.6, help="바깥 차선 밖으로 도로 영역에 넣을 폭(m)")
    parser.add_argument("--stop-zone-length", type=float, default=15.0, help="정지 대기 영역 길이(m)")
    parser.add_argument("--detections", type=Path, help="detections.jsonl. 검출 바닥점이 도로 영역 안에 드는 비율을 잰다")
    parser.add_argument("--out", type=Path, help="기본: <캘리브레이션 이름>.road_context.json 또는 <내보내기>/road_context.json")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    export = None
    if args.calibration:
        cal = load_calibration(args.calibration)
        plane = GroundPlane(cal["H"], tuple(cal["image_size"]), args.meters_per_unit)
        camera_id = cal.get("camera_id")
        out = args.out or args.calibration.with_name(args.calibration.stem + ".road_context.json")
        patterns = args.frames or []
    else:
        export = load_export(args.export)
        ground_y = float(np.median(export.control_points.world[:, 1]))
        cam = export.camera
        plane = GroundPlane.from_camera(cam.K, cam.Rt, (cam.width, cam.height), ground_y, args.meters_per_unit)
        camera_id = cam.camera_id
        out = args.out or args.export / "road_context.json"
        patterns = args.frames or [str(args.export / "frames" / "*.jpg")]
    paths = sorted({p for pat in patterns for p in (glob.glob(pat) or [pat]) if Path(p).is_file()})
    if not paths:
        sys.exit("프레임이 없습니다. --frames로 원본 프레임을 주세요")
    paths = sample(paths, args.max_frames)
    frames = [read_image(Path(p)) for p in paths]
    w, h = plane.image_size
    frames = [f for f in frames if f is not None and f.shape[1] == w and f.shape[0] == h]
    if not frames:
        sys.exit(f"프레임 크기가 캘리브레이션({w}x{h})과 다릅니다")
    background = median_background(frames)

    ignore = np.zeros((h, w), bool)
    for text in args.ignore:
        x0, y0, x1, y1 = (float(v) for v in text.split(","))
        ignore[int(y0 * h):int(np.ceil(y1 * h)), int(x0 * w):int(np.ceil(x1 * w))] = True

    scene = analyse_road(background, plane, max_distance_m=args.max_distance, lateral_half_m=args.lateral,
                         ignore=ignore if ignore.any() else None)
    ctx = build_context(scene, plane, shoulder_m=args.shoulder, stop_zone_length_m=args.stop_zone_length,
                        polygon_far_m=args.polygon_far, camera_id=camera_id)
    ctx["frames_used"] = len(frames)
    ctx["source"] = str((args.calibration or args.export).resolve())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(ctx, indent=1, ensure_ascii=False), encoding="utf-8")
    overlay = out.with_name(out.stem + "_overlay.jpg")
    write_image(overlay, draw_context(background, ctx))
    write_image(out.with_name(out.stem + "_background.jpg"), background)

    print(f"카메라 {camera_id}: 프레임 {len(frames)}장 중앙값")
    for lane in ctx["lanes"]:
        extra = f", 점선 {lane['dash_length_m']} m / 간격 {lane['dash_period_m']} m" if lane["kind"] == "dashed" else ""
        print(f"  선 {lane['lateral_m']:+6.2f} m  {lane['color']:<6} {lane['kind']:<7} 폭 {lane['width_m']:.2f} m{extra}")
    if ctx["road_polygon"]:
        print(f"도로 영역: 가로 {ctx['road_lateral_m'][0]:+.1f} ~ {ctx['road_lateral_m'][1]:+.1f} m, "
              f"앞쪽 {ctx['road_along_m'][0]:.0f} ~ {ctx['road_along_m'][1]:.0f} m (중앙선 {ctx['centre_lateral_m']})")
    else:
        print("⚠️ " + ctx.get("warning", "도로 영역을 만들지 못했습니다"))
    print(f"횡단보도 {len(ctx['crosswalks'])}개, 정지선 {len(ctx['stop_lines'])}개, 정지 대기 영역 {len(ctx['stop_zones'])}개")

    def report(label, points):
        if points and ctx["road_polygon"]:
            n = sum(inside(p, ctx["road_polygon"]) for p in points)
            print(f"{label}: {n}/{len(points)} ({n / len(points):.0%})가 도로 영역 안")
    if export is not None:
        pts = [(o["ground_point_pixel"][0] / w, o["ground_point_pixel"][1] / h) for fr in export.frames for o in fr["objects"]
               if o.get("class_name") in VEHICLES and o.get("ground_point_in_frame") and o.get("ground_point_pixel")]
        report("정답 차량 바닥점", pts)
    if args.detections and args.detections.exists():
        pts = []
        for line in args.detections.read_text(encoding="utf-8-sig").splitlines():
            if line.strip():
                rec = json.loads(line)
                for d in rec.get("detections", []):
                    if d.get("class_name") in VEHICLES and d.get("confidence", 0) >= 0.5:
                        b = d["bbox_xyxy"]
                        pts.append(((b[0] + b[2]) / 2 / rec["width"], b[3] / rec["height"]))
        report("검출 차량 바닥점(신뢰도 0.5 이상)", pts)
    print(f"저장: {out}\n확인용 그림: {overlay}")


if __name__ == "__main__":
    main()
