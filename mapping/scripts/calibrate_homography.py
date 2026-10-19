"""실제 CCTV 화면의 미터 단위 Homography 캘리브레이션.

    # 1) 화면에서 점 찍기 → 2) 콘솔에 점마다 실제 좌표 입력
    python calibrate_homography.py --image captures/utic-1294_20261017_221500.png
    python calibrate_homography.py --image <이미지> --latlon     # 실제 좌표를 지도 위도·경도로 입력

    # 저장된 점 목록(CSV)을 고쳐서 다시 계산
    python calibrate_homography.py --image <이미지> --points calibration/utic-1294.points.csv

점 찍기 창: 왼쪽 클릭 = 점 추가, 오른쪽 클릭 또는 u = 마지막 점 지우기, Enter = 완료, Esc = 취소.
커서 주변을 확대한 돋보기가 화면 구석에 보인다.

실제 좌표를 얻는 방법
- 지도(브이월드 항공사진, 카카오맵·네이버지도)에서 같은 지점(차선 끝, 정지선 모서리, 맨홀 등)의 위도·경도를 읽는다(--latlon).
- 또는 도로 위에 직접 정한 좌표계(예: 한 차선 끝을 원점, 도로 방향을 z)로 차선 폭·점선 길이를 이용해 미터 좌표를 적는다.
점은 6개 이상, 화면 전체(가까운 곳·먼 곳·좌우)에 고르게 찍는다. 같은 평면(노면) 위의 점만 쓴다.

결과: calibration/<카메라ID>.json (CCTV 파이프라인이 자동으로 읽음), <카메라ID>.points.csv, <카메라ID>_birdseye.png
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping.calibration import (  # noqa: E402
    birds_eye_view,
    fit_calibration,
    latlon_to_local_xz,
    read_image,
    save_calibration,
    suspicious_points,
    write_image,
)
from twinsight_mapping.pose import pose_report  # noqa: E402

WINDOW = "Calibration (click points, Enter: done, right-click/u: undo, Esc: cancel)"
MAGNIFY_RADIUS = 20  # 돋보기가 보여 주는 반경(px)
MAGNIFY_SCALE = 6


class PointPicker:
    """이미지 위에서 점을 찍는다. 커서 주변을 확대한 돋보기로 정확한 픽셀을 고를 수 있다."""

    def __init__(self, image: np.ndarray):
        self.image = image
        self.points: list[tuple[int, int]] = []
        self.cursor: tuple[int, int] | None = None

    def on_mouse(self, event, x, y, flags, param):
        if event == cv2.EVENT_MOUSEMOVE:
            self.cursor = (x, y)
        elif event == cv2.EVENT_LBUTTONDOWN:
            self.points.append((x, y))
            print(f"  점 {len(self.points)}: 픽셀 ({x}, {y})")
        elif event == cv2.EVENT_RBUTTONDOWN:
            self.undo()

    def undo(self):
        if self.points:
            x, y = self.points.pop()
            print(f"  점 {len(self.points) + 1} 지움: ({x}, {y})")

    def render(self) -> np.ndarray:
        canvas = self.image.copy()
        for i, (x, y) in enumerate(self.points, start=1):
            cv2.drawMarker(canvas, (x, y), (0, 0, 255), cv2.MARKER_CROSS, 12, 1)
            cv2.putText(canvas, str(i), (x + 5, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1, cv2.LINE_AA)
        if self.cursor:
            self._draw_magnifier(canvas)
        return canvas

    def _draw_magnifier(self, canvas: np.ndarray) -> None:
        h, w = self.image.shape[:2]
        x, y = self.cursor
        r = MAGNIFY_RADIUS
        padded = cv2.copyMakeBorder(self.image, r, r, r, r, cv2.BORDER_CONSTANT)
        crop = padded[y:y + 2 * r + 1, x:x + 2 * r + 1]
        zoom = cv2.resize(crop, None, fx=MAGNIFY_SCALE, fy=MAGNIFY_SCALE, interpolation=cv2.INTER_NEAREST)
        c = r * MAGNIFY_SCALE + MAGNIFY_SCALE // 2
        cv2.line(zoom, (c, 0), (c, zoom.shape[0] - 1), (0, 255, 255), 1)
        cv2.line(zoom, (0, c), (zoom.shape[1] - 1, c), (0, 255, 255), 1)
        size = zoom.shape[0]
        if size >= min(w, h):
            return
        # 커서가 오른쪽 위에 있으면 돋보기를 왼쪽 위에 둔다
        left = 0 if (x > w - size - 20 and y < size + 20) else w - size
        canvas[0:size, left:left + size] = zoom
        cv2.rectangle(canvas, (left, 0), (left + size - 1, size - 1), (0, 255, 255), 1)

    def run(self) -> list[tuple[int, int]] | None:
        h, w = self.image.shape[:2]
        scale = min(2.0, 1400 / w, 900 / h)
        cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(WINDOW, int(w * scale), int(h * scale))
        cv2.setMouseCallback(WINDOW, self.on_mouse)
        try:
            while True:
                cv2.imshow(WINDOW, self.render())
                key = cv2.waitKey(20) & 0xFF
                if key in (13, 10, 32):
                    return self.points
                if key == 27:
                    return None
                if key in (ord("u"), 8):
                    self.undo()
                if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                    return self.points
        finally:
            cv2.destroyWindow(WINDOW)


def ask_world_coordinates(points, latlon: bool) -> list[tuple[int, float, float, float, float]]:
    """점마다 실제 좌표를 콘솔에서 입력받는다. 반환: [(id, u, v, a, b)] (a, b는 x z 또는 위도 경도)"""
    label = "위도 경도" if latlon else "x z (m)"
    print(f"\n점마다 실제 좌표를 '{label}' 형식으로 입력하세요. 빈칸이면 그 점은 쓰지 않습니다.")
    rows = []
    for i, (u, v) in enumerate(points, start=1):
        while True:
            text = input(f"  점 {i} (픽셀 {u}, {v}) → {label}: ").strip()
            if not text:
                break
            parts = re.split(r"[,\s]+", text)
            try:
                a, b = (float(p) for p in parts[:2])
            except ValueError:
                print("    숫자 두 개를 입력하세요. 예: 12.5 30  또는  36.7801 127.0012")
                continue
            if len(parts) != 2:
                print("    숫자 두 개만 입력하세요.")
                continue
            rows.append((i, float(u), float(v), a, b))
            break
    return rows


def write_points_csv(path: Path, rows, latlon: bool) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "u", "v", "lat", "lon"] if latlon else ["id", "u", "v", "x", "z"])
        writer.writerows(rows)


def read_points_csv(path: Path):
    """반환: (rows, latlon 여부)"""
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = [name.strip().lower() for name in reader.fieldnames or []]
        latlon = "lat" in fields
        rows = []
        for r in reader:
            r = {k.strip().lower(): v for k, v in r.items()}
            a, b = (r["lat"], r["lon"]) if latlon else (r["x"], r["z"])
            rows.append((int(r["id"]), float(r["u"]), float(r["v"]), float(a), float(b)))
    return rows, latlon


def default_camera_id(image_path: Path) -> str:
    # CCTV 파이프라인이 저장한 이름: <카메라ID>_<YYYYmmdd>_<HHMMSS>.png
    m = re.match(r"(.+?)_\d{8}_\d{6}$", image_path.stem)
    return m.group(1) if m else image_path.stem


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--image", type=Path, required=True, help="CCTV 원본 프레임 (화면 표시가 없는 것)")
    parser.add_argument("--camera-id", help="기본: 이미지 파일 이름에서 추출 (예: utic-1294)")
    parser.add_argument("--points", type=Path, help="점 목록 CSV (id,u,v,x,z 또는 id,u,v,lat,lon). 주면 점 찍기를 건너뛴다")
    parser.add_argument("--latlon", action="store_true", help="실제 좌표를 위도·경도로 입력한다")
    parser.add_argument("--origin", help="위도·경도 모드의 원점 'lat,lon' (기본: 첫 번째 점)")
    parser.add_argument("--road-heading-deg", type=float,
                        help="도로(차로) 방향. +z(위도·경도 모드면 북쪽)에서 +x(동쪽) 쪽으로 잰 각도. "
                             "편향 보정에서 차량 진행 방향을 아직 모를 때 쓴다")
    parser.add_argument("--fov", type=float, help="CCTV 세로 화각을 알면 고정(도). 카메라 자세 계산에 쓴다")
    parser.add_argument("--meters-per-unit", type=float, default=1.0,
                        help="가상환경 1단위가 몇 m인지. 카메라 자세의 Unity 값에만 적용")
    parser.add_argument("--out", type=Path, help="기본: calibration/<카메라ID>.json")
    parser.add_argument("--no-show", action="store_true", help="결과 창을 띄우지 않는다")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    image = read_image(args.image)
    height, width = image.shape[:2]
    camera_id = args.camera_id or default_camera_id(args.image)
    out = args.out or Path("calibration") / f"{camera_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    points_csv = out.with_suffix(".points.csv")
    print(f"카메라 {camera_id}, 이미지 {width}x{height}")

    if args.points:
        rows, latlon = read_points_csv(args.points)
    else:
        latlon = args.latlon
        print("\n화면에서 노면 위의 점을 찍으세요 (왼쪽 클릭 추가, 오른쪽 클릭/u 지우기, Enter 완료, Esc 취소).")
        clicked = PointPicker(image).run()
        if clicked is None:
            print("취소했습니다.")
            return
        rows = ask_world_coordinates(clicked, latlon)
        write_points_csv(points_csv, rows, latlon)
        print(f"점 목록 저장: {points_csv} (고친 뒤 --points 로 다시 계산할 수 있습니다)")

    if len(rows) < 4:
        sys.exit(f"좌표가 있는 점이 {len(rows)}개입니다. 4개 이상 필요합니다(6개 이상 권장).")

    ids = np.array([r[0] for r in rows])
    pixels = np.array([[r[1], r[2]] for r in rows])
    raw = np.array([[r[3], r[4]] for r in rows])
    origin = None
    if latlon:
        origin = tuple(float(v) for v in args.origin.split(",")) if args.origin else (raw[0, 0], raw[0, 1])
        ground = latlon_to_local_xz(raw[:, 0], raw[:, 1], origin)
        coordinate_system = "local_enu: x=동쪽(m), z=북쪽(m), origin_latlon 기준"
    else:
        ground = raw
        coordinate_system = "user: 입력한 x, z (m)"

    result = fit_calibration(pixels, ground)
    loo = result["loo_errors_m"]

    print(f"\n{'점':>3} {'픽셀 (u, v)':>18} {'실제 (x, z) m':>22} {'잔차 m':>8} {'LOO 오차 m':>10}")
    for i, pid in enumerate(ids):
        loo_text = f"{loo[i]:.3f}" if np.isfinite(loo[i]) else "-"
        print(f"{pid:>3} ({pixels[i, 0]:7.1f}, {pixels[i, 1]:7.1f}) ({ground[i, 0]:9.3f}, {ground[i, 1]:9.3f}) "
              f"{result['residuals_m'][i]:8.3f} {loo_text:>10}")
    print(f"\n맞춤 RMSE {result['fit_rmse_m']:.3f} m"
          + (f", LOO 오차 중앙값 {np.nanmedian(loo):.3f} m" if np.isfinite(loo).any() else ""))

    if len(rows) == 4:
        print("⚠️ 점이 4개라 오차를 확인할 수 없습니다(4점은 항상 정확히 맞음). 6개 이상 찍기를 권장합니다.")
    elif len(rows) < 6:
        print("⚠️ 점이 6개 미만입니다. 찍기 오차를 줄이려면 6개 이상을 권장합니다.")
    for i in suspicious_points(loo):
        print(f"⚠️ {ids[i]}번 점의 LOO 오차({loo[i]:.2f} m)가 다른 점보다 큽니다. 다시 찍거나 좌표를 확인하세요.")
    coverage = np.ptp(pixels[:, 0]) * np.ptp(pixels[:, 1]) / (width * height)
    if coverage < 0.3:
        print(f"⚠️ 점들이 화면의 {coverage:.0%}만 덮습니다. 이 범위 밖의 위치는 오차가 커질 수 있습니다.")

    save_calibration(out, camera_id=camera_id, image_path=args.image.resolve(), image_size=(width, height),
                     point_ids=ids, pixels=pixels, ground=ground, result=result,
                     coordinate_system=coordinate_system, origin_latlon=origin,
                     latlon=raw if latlon else None, road_heading_deg=args.road_heading_deg)
    preview = birds_eye_view(image, result["H"], ground, labels=ids)
    preview_path = out.with_name(f"{out.stem}_birdseye.png")
    write_image(preview_path, preview)
    print(f"\n저장: {out}\n위에서 본 그림: {preview_path}")

    # 같은 기준점으로 카메라 위치·높이·방향·각도·화각을 구해 가상 CCTV 배치값으로 저장한다
    if len(rows) >= 6:
        focal = (height / 2.0) / np.tan(np.radians(args.fov) / 2.0) if args.fov else None
        try:
            pose = pose_report(pixels, ground, (width, height), camera_id=camera_id, origin_latlon=origin,
                               meters_per_unit=args.meters_per_unit, focal=focal)
        except ValueError as e:
            print(f"⚠️ 카메라 자세를 구하지 못했습니다: {e}")
        else:
            pose["calibration"] = str(out.resolve())
            pose_path = out.with_suffix(".pose.json")
            pose_path.write_text(json.dumps(pose, indent=2, ensure_ascii=False), encoding="utf-8")
            p = pose["position_m"]
            print(f"\n카메라 자세 (가상 CCTV 배치값): 높이 {p['height']:.2f} m, 방향 {pose['heading_deg']:.1f}°, "
                  f"내려다보는 각도 {pose['pitch_deg']:.1f}°, 세로 화각 {pose['vertical_fov_deg']:.1f}°"
                  + (f", 위도·경도 {pose['position_latlon'][0]:.7f}, {pose['position_latlon'][1]:.7f}"
                     if pose.get("position_latlon") else ""))
            print(f"자세 저장: {pose_path} (자세한 값은 estimate_camera_pose.py --calibration {out})")
    else:
        print("ℹ️ 카메라 자세(가상 CCTV 배치값)는 기준점이 6개 이상일 때 계산합니다.")

    if not args.no_show:
        cv2.namedWindow("Birds-eye check", cv2.WINDOW_NORMAL)
        cv2.imshow("Birds-eye check", preview)
        print("창을 닫거나 아무 키나 누르면 끝납니다.")
        cv2.waitKey(0)
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
