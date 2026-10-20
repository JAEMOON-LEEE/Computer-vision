"""실제 CCTV 자세를 도로 중앙선 기준 값으로 바꿔, 지도가 다른 가상 도로(City Lab)에 옮길 수 있게 한다.

    python mapping/scripts/road_relative_pose.py --pose calibration/<카메라ID>.pose.json \
        --road-line 37.76880,126.79230 37.76990,126.79130 --ref-point 37.771067,126.790516 --virtual-id city-lab-geumchon

- --road-line: 실제 도로 중앙선(중앙분리대 가운데) 위 두 점의 위도·경도. 첫 점 → 둘째 점 방향이 '도로 앞쪽'이다.
  카메라가 보는 쪽(보통 사거리 쪽)으로 둔다.
- --ref-point: 카메라에서 앞쪽 거리를 재고 싶은 지점(정지선·사거리 중심 등). Unity 배치 메뉴가 이 거리를 쓴다.

결과: <카메라ID>.road_pose.json
- along_m / lateral_m: 중앙선 기준 카메라 위치(앞쪽 +, 오른쪽 +, m)
- height_m: 노면에서 잰 높이, yaw_to_road_deg: 도로 방향 대비 카메라 방향(오른쪽 +)
- pitch_deg, roll_deg, vertical_fov_deg, image_size, ref_ahead_m(카메라에서 기준 지점까지 앞쪽 거리)
Unity의 TwinSight > City Lab > Place VirtualCCTV From Real CCTV가 이 파일을 읽는다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping.pose import road_relative_pose  # noqa: E402


def latlon(text: str) -> tuple[float, float]:
    lat, lon = (float(v) for v in text.replace(" ", "").split(","))
    return lat, lon


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pose", type=Path, required=True, help="calibrate_homography.py가 만든 <카메라ID>.pose.json")
    parser.add_argument("--road-line", nargs=2, type=latlon, required=True, metavar=("LAT,LON", "LAT,LON"),
                        help="도로 중앙선 위 두 점. 첫 점 → 둘째 점이 도로 앞쪽(카메라가 보는 쪽)")
    parser.add_argument("--ref-point", type=latlon, help="앞쪽 거리를 잴 지점(정지선·사거리 중심)의 'lat,lon'")
    parser.add_argument("--virtual-id", help="가상 CCTV 카메라 ID(영문). Unity 내보내기 폴더 이름에 쓴다")
    parser.add_argument("--out", type=Path, help="기본: <카메라ID>.road_pose.json (자세 파일과 같은 폴더)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    pose = json.loads(args.pose.read_text(encoding="utf-8"))
    result = road_relative_pose(pose, args.road_line[0], args.road_line[1], args.ref_point)
    result["virtual_camera_id"] = args.virtual_id or ""
    result["source_pose"] = str(args.pose.resolve())
    stem = args.pose.name.removesuffix(".pose.json").removesuffix(".json")
    out = args.out or args.pose.with_name(f"{stem}.road_pose.json")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    side = "오른쪽" if result["lateral_m"] >= 0 else "왼쪽"
    turn = "오른쪽" if result["yaw_to_road_deg"] >= 0 else "왼쪽"
    print(f"카메라 {result['camera_id']} (도로 방향 {result['road_bearing_deg']:.1f}°)")
    print(f"  위치: 중앙선 {side} {abs(result['lateral_m']):.2f} m, 노면에서 높이 {result['height_m']:.2f} m")
    print(f"  방향: 도로보다 {turn}으로 {abs(result['yaw_to_road_deg']):.1f}°, 내려다보는 각도 {result['pitch_deg']:.1f}°, "
          f"좌우 기울기 {result['roll_deg']:.1f}°, 세로 화각 {result['vertical_fov_deg']:.1f}°")
    if result["has_ref"]:
        print(f"  기준 지점까지 앞쪽 거리 {result['ref_ahead_m']:.1f} m (기준 지점은 중앙선에서 {result['ref_lateral_m']:+.1f} m)")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
