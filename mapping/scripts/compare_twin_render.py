"""Unity에서 렌더링한 디지털 트윈 화면(Logs/twin_replay/<이름>/manifest.json)을 실제 CCTV 화면과 비교한다.

    python mapping/scripts/compare_twin_render.py simulation/TwinSightSim/Logs/twin_replay/<이름>
    python mapping/scripts/compare_twin_render.py <폴더> --virtual-detections runs/detection/<가상 화면 검출>/detections.jsonl

1) 배치 검사: Unity에 놓인 차량 상자를 VirtualCCTV로 투영한 박스와 실제 CCTV 검출 박스를 비교(박스 아래 가운데 거리, IoU).
   변환(화면 → 실제 좌표 → 도로 기준 → City Lab)과 Unity 배치가 맞으면 같은 자리에 나온다.
2) 화면 검사(--virtual-detections): 렌더링한 가상 화면에 YOLO를 돌린 결과와 실제 검출을 짝지어 비교.
3) compare/frame_XXXX.jpg: 실제 화면 | 가상 화면 | 반씩 겹친 그림.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping.calibration import read_image, write_image  # noqa: E402


def unity_camera(manifest: dict):
    """Unity 카메라(왼손 좌표, y 위) → OpenCV 투영 (R: 월드 → 카메라, t, K)."""
    x, y, z, w = manifest["camera_rotation_xyzw"]
    # 쿼터니언 → 회전 행렬(Unity 로컬 → 월드)
    Rw = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                   [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                   [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    right, up, forward = Rw[:, 0], Rw[:, 1], Rw[:, 2]
    R = np.vstack([right, -up, forward])
    C = np.asarray(manifest["camera_position"], float)
    W, H = manifest["image_size"]
    f = (H / 2) / math.tan(math.radians(manifest["camera_vertical_fov_deg"]) / 2)
    K = np.array([[f, 0, W / 2], [0, f, H / 2], [0, 0, 1]])
    return R, -R @ C, K


def project(points, R, t, K):
    cam = np.atleast_2d(points) @ R.T + t
    uv = cam @ K.T
    return uv[:, :2] / uv[:, 2:3], cam[:, 2]


def box_of(obj, R, t, K):
    """놓인 차량의 월드 경계 상자(차량이 ±X를 보므로 축 정렬 상자 = 차량 상자)를 투영한 박스."""
    cx, cy, cz = obj["unity_position"]
    sx, sy, sz = obj["size_units"]
    corners = np.array([[cx + a * sx / 2, cy + b * sy, cz + c * sz / 2] for a in (-1, 1) for b in (0, 1) for c in (-1, 1)])
    uv, depth = project(corners, R, t, K)
    if (depth <= 0).any():
        return None
    return [float(uv[:, 0].min()), float(uv[:, 1].min()), float(uv[:, 0].max()), float(uv[:, 1].max())]


def iou(a, b) -> float:
    inter = max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def bottom(b):
    return np.array([(b[0] + b[2]) / 2, b[3]])


def summary(name, dist, ious):
    if not dist:
        print(f"{name}: 비교할 차량 없음")
        return
    d = np.array(dist)
    print(f"{name}: {len(d)}대, 박스 아래 가운데 거리 중앙값 {np.median(d):.1f} px (90 % {np.percentile(d, 90):.1f} px), "
          f"IoU 중앙값 {np.median(ious):.2f}, 10 px 이내 {np.mean(d <= 10):.0%}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("folder", type=Path, help="Logs/twin_replay/<이름> (manifest.json이 있는 폴더)")
    parser.add_argument("--virtual-detections", type=Path, help="렌더링 폴더에 YOLO를 돌린 detections.jsonl")
    parser.add_argument("--match-px", type=float, default=25.0, help="화면 검사에서 짝으로 볼 최대 거리(px)")
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    manifest = json.loads((args.folder / "manifest.json").read_text(encoding="utf-8"))
    R, t, K = unity_camera(manifest)
    W, H = manifest["image_size"]

    dist, ious, rows = [], [], []
    for fr in manifest["frames"]:
        for o in fr["objects"]:
            box = box_of(o, R, t, K)
            if box is None:
                continue
            d = float(np.linalg.norm(bottom(box) - bottom(o["real_bbox_xyxy"])))
            dist.append(d); ious.append(iou(box, o["real_bbox_xyxy"]))
            rows.append((fr["frame"], o["class_name"], o["prefab"], d))
    summary("1) 배치 검사(Unity 차량 상자 투영 vs 실제 검출)", dist, ious)
    worst = sorted(rows, key=lambda r: -r[3])[:3]
    if worst:
        print("   차이가 가장 큰 차량: " + ", ".join(f"프레임 {f} {c}({p}) {d:.1f} px" for f, c, p, d in worst))

    if args.virtual_detections and args.virtual_detections.exists():
        virtual = {}
        names = sorted(Path(fr["rendered_image"]).name for fr in manifest["frames"])
        for i, line in enumerate(l for l in args.virtual_detections.read_text(encoding="utf-8-sig").splitlines() if l.strip()):
            rec = json.loads(line)
            virtual[names[int(rec.get("frame", i))]] = [d for d in rec["detections"]
                                                        if d["class_name"] in ("car", "truck", "bus") and d["confidence"] >= 0.3]
        dist2, ious2, found, total = [], [], 0, 0
        for fr in manifest["frames"]:
            cands = list(virtual.get(Path(fr["rendered_image"]).name, []))
            for o in fr["objects"]:
                total += 1
                if not cands:
                    continue
                k = int(np.argmin([np.linalg.norm(bottom(c["bbox_xyxy"]) - bottom(o["real_bbox_xyxy"])) for c in cands]))
                d = float(np.linalg.norm(bottom(cands[k]["bbox_xyxy"]) - bottom(o["real_bbox_xyxy"])))
                if d <= args.match_px:
                    found += 1; dist2.append(d); ious2.append(iou(cands[k]["bbox_xyxy"], o["real_bbox_xyxy"]))
                    cands.pop(k)
        print(f"2) 화면 검사: 가상 화면 YOLO가 실제 차량 {total}대 중 {found}대({found / max(total, 1):.0%})를 {args.match_px:g} px 안에서 찾음")
        summary("   짝지어진 차량", dist2, ious2)

    out = args.folder / "compare"
    out.mkdir(exist_ok=True)
    project = args.folder.resolve().parents[2]   # <Unity 프로젝트>/Logs/twin_replay/<이름>
    for fr in manifest["frames"]:
        real_path = fr.get("real_image") or ""
        if real_path and not Path(real_path).is_absolute():
            real_path = str(project / real_path)
        real = read_image(real_path) if real_path and Path(real_path).exists() else None
        virt = read_image(fr["rendered_image"])
        if real is None or virt is None:
            continue
        for o in fr["objects"]:
            b = [int(v) for v in o["real_bbox_xyxy"]]
            cv2.rectangle(real, (b[0], b[1]), (b[2], b[3]), (0, 255, 0), 1)
            box = box_of(o, R, t, K)
            if box:
                cv2.rectangle(virt, (int(box[0]), int(box[1])), (int(box[2]), int(box[3])), (0, 200, 255), 1)
        blend = cv2.addWeighted(real, 0.5, virt, 0.5, 0)
        write_image(out / f"frame_{fr['frame']:04d}.jpg", np.hstack([real, virt, blend]))
    print(f"비교 그림: {out}")


if __name__ == "__main__":
    main()
