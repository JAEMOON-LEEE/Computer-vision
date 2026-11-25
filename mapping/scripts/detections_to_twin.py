"""실제 CCTV 검출 결과(detections.jsonl)를 도로 기준 좌표로 바꿔 디지털 트윈 재생 파일(<이름>.twin.json)을 만든다.

    python mapping/scripts/detections_to_twin.py --detections runs/detection/<폴더>/detections.jsonl \
        --calibration calibration/<카메라ID>.json --road-pose simulation/TwinSightSim/RealCctv/<이름>.road_pose.json \
        --road-context simulation/TwinSightSim/RealCctv/<이름>.road_context.json --frames "captures/<카메라ID>_*.png"

- 박스 아래 가운데를 캘리브레이션으로 노면 좌표(m)에 옮기고, 도로 방향으로 진행한다고 보고 편향을 보정해 차량 중심을 구한다.
- 도로 중앙선(road_pose.json의 road_line) 기준 along(카메라에서 앞쪽 거리)·lateral(오른쪽 +)로 바꾼다.
- --road-context를 주면 도로 영역 안인지(in_road)와 인식한 차선도 같은 좌표로 넣는다.
- --frames는 검출에 쓴 원본 프레임(정렬 순서 = 검출 frame 번호). 비교용으로 경로를 적어 둔다.
Unity의 TwinSight > City Lab > Replay Real CCTV Detections...가 simulation/TwinSightSim/RealCctv/*.twin.json을 읽는다.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping.calibration import load_calibration  # noqa: E402
from twinsight_mapping.correction import load_dimensions_file  # noqa: E402
from twinsight_mapping.twin import RoadAxes, detection_to_twin, lanes_to_twin, merge_duplicates  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--detections", type=Path, required=True)
    parser.add_argument("--calibration", type=Path, required=True, help="위도·경도로 만든 캘리브레이션 JSON")
    parser.add_argument("--road-pose", type=Path, required=True, help="road_relative_pose.py가 만든 *.road_pose.json")
    parser.add_argument("--road-context", type=Path, help="detect_road_context.py가 만든 road-context.json")
    parser.add_argument("--frames", help="검출에 쓴 원본 프레임 glob (정렬 순서가 frame 번호)")
    parser.add_argument("--dims-file", type=Path, help="correction.json (클래스별 유효 길이). 없으면 기본 차량 크기")
    parser.add_argument("--min-confidence", type=float, default=0.4)
    parser.add_argument("--relative-to", type=Path,
                        help="프레임 경로를 이 폴더 기준 상대 경로로 적는다. 기본: road_pose 파일의 두 단계 위(Unity 프로젝트 폴더)")
    parser.add_argument("--out", type=Path, help="기본: <road_pose 이름>.twin.json (같은 폴더)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cal = load_calibration(args.calibration)
    if not cal.get("origin_latlon"):
        sys.exit("위도·경도로 만든 캘리브레이션이 필요합니다(origin_latlon 없음)")
    road_pose = json.loads(args.road_pose.read_text(encoding="utf-8"))
    axes = RoadAxes.from_road_pose(road_pose, cal["origin_latlon"])
    camera_along = float(road_pose["along_m"])
    context = json.loads(args.road_context.read_text(encoding="utf-8")) if args.road_context else {}
    polygon = context.get("road_polygon") or None
    dims = load_dimensions_file(args.dims_file) if args.dims_file else None
    images = sorted(glob.glob(args.frames)) if args.frames else []
    size = tuple(cal["image_size"])
    base = (args.relative_to or args.road_pose.resolve().parent.parent).resolve()

    def image_path(p: str) -> str:
        """Unity 재생이 다른 PC에서도 찾도록 프로젝트 폴더 기준 상대 경로로 적는다(밖에 있으면 절대 경로)."""
        full = Path(p).resolve()
        try:
            return full.relative_to(base).as_posix()
        except ValueError:
            return str(full)

    frames, kinds, lanes_hist, merged = [], Counter(), Counter(), 0
    for line in args.detections.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        objects = []
        for i, det in enumerate(rec.get("detections", [])):
            if det.get("confidence", 0) < args.min_confidence:
                continue
            obj = detection_to_twin(det, cal["H"], axes, camera_along, size, dims, polygon)
            if obj is None:
                continue
            obj["id"] = int(obj["id"]) if obj["id"] is not None else i
            obj["in_road"] = True if obj["in_road"] is None else obj["in_road"]
            objects.append(obj)
        before = len(objects)
        objects = merge_duplicates(objects)   # 같은 차량을 여러 클래스로 겹쳐 검출한 것 정리
        merged += before - len(objects)
        for obj in objects:
            kinds["도로 안" if obj["in_road"] else "도로 밖"] += 1
            if obj["in_road"]:
                lanes_hist[round(obj["lateral_m"])] += 1
        idx = int(rec.get("frame", len(frames)))
        frames.append({"frame": idx, "timestamp": float(rec.get("timestamp", 0.0)),
                       "image": image_path(images[idx]) if idx < len(images) else "", "objects": objects})

    twin = {
        "camera_id": road_pose.get("camera_id"), "virtual_camera_id": road_pose.get("virtual_camera_id", ""),
        "image_size": list(size), "units": "m",
        "coordinates": "along_m: 카메라에서 도로 앞쪽(+), lateral_m: 도로 중앙선에서 오른쪽(+). 우측 통행 기준 direction",
        "camera": {"along_m": camera_along, "lateral_m": road_pose["lateral_m"], "height_m": road_pose["height_m"]},
        "lanes": lanes_to_twin(context, axes, camera_along) if context else [],
        "frames": frames,
    }
    out = args.out or args.road_pose.with_name(args.road_pose.name.replace(".road_pose.json", "") + ".twin.json")
    out.write_text(json.dumps(twin, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(f["objects"]) for f in frames)
    print(f"{len(frames)}프레임, 차량 {n}대 ({dict(kinds)}), 겹쳐 검출된 {merged}개 합침")
    if lanes_hist:
        print("도로 안 차량의 중앙선 기준 위치(m, 반올림): " + ", ".join(f"{k:+d}:{v}" for k, v in sorted(lanes_hist.items())))
    print(f"차선 {len(twin['lanes'])}개 변환")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
