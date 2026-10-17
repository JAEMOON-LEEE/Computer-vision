"""Unity 없이 평가 코드를 시험할 수 있는 합성 내보내기 폴더를 만든다.

    python mapping/scripts/make_synthetic_export.py out/synthetic_flat --fake-detections
    python mapping/scripts/make_synthetic_export.py out/synthetic_sag --sag 0.0001

카메라·도로 배치는 Unity 예제 씬(TwinSight > Create Demo Road Scene)과 같다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from twinsight_mapping.synthetic import SceneConfig, generate  # noqa: E402


def main() -> None:
    defaults = SceneConfig()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--frames", type=int, default=defaults.frames)
    parser.add_argument("--fps", type=float, default=defaults.fps)
    parser.add_argument("--camera-height", type=float, default=defaults.camera_position[1], help="m")
    parser.add_argument("--pitch", type=float, default=defaults.pitch_deg, help="아래로 숙인 각도(도)")
    parser.add_argument("--yaw", type=float, default=defaults.yaw_deg, help="좌우 회전(도)")
    parser.add_argument("--vfov", type=float, default=defaults.vertical_fov_deg, help="세로 화각(도)")
    parser.add_argument("--sag", type=float, default=0.0,
                        help="노면 휘어짐 계수. y = sag * (z - 40)^2, 0이면 평평한 도로")
    parser.add_argument("--fake-detections", action="store_true", help="정답을 흔들어 만든 가짜 detections.jsonl도 쓴다")
    parser.add_argument("--det-jitter", type=float, default=defaults.det_jitter_px, help="가짜 검출 박스 흔들림(px)")
    parser.add_argument("--size-jitter", type=float, default=0.0,
                        help="차량마다 길이·폭을 이 비율(표준편차)만큼 다르게 한다. 예: 0.1")
    parser.add_argument("--seed", type=int, default=defaults.seed)
    args = parser.parse_args()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    x, _, z = defaults.camera_position
    cfg = SceneConfig(
        frames=args.frames,
        fps=args.fps,
        camera_position=(x, args.camera_height, z),
        pitch_deg=args.pitch,
        yaw_deg=args.yaw,
        vertical_fov_deg=args.vfov,
        sag=args.sag,
        fake_detections=args.fake_detections,
        det_jitter_px=args.det_jitter,
        size_jitter=args.size_jitter,
        seed=args.seed,
    )
    out = generate(cfg, args.out_dir)
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
