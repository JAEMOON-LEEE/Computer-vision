"""레포 루트의 차량 3D 에셋(Papabear Car Package)에서 Unity가 쓸 파일만 Unity 프로젝트로 복사한다.

    git lfs pull --include="Papabear_Papabear Car Package/**/*.fbx,Papabear_Papabear Car Package/**/*.jpg,..."
    python simulation/tools/copy_vehicle_assets.py

- FBX 모델과 텍스처(jpg, jpeg, png, tif)만 복사한다. OBJ·DAE(같은 모델의 다른 형식)와
  클립 스튜디오 파일(clip, cs3o, csmo)은 Unity에 필요 없어 건너뛴다.
- 내용이 똑같은 FBX 모델은 한 번만 복사한다(텍스처는 모델 옆에 있어야 하므로 모두 복사).
- 아직 LFS로 내려받지 않은 파일(포인터 파일)은 건너뛰고 알려 준다.
복사한 뒤 Unity에서 TwinSight > Build Vehicle Prefabs 를 실행한다.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "Papabear_Papabear Car Package"
TARGET = REPO / "simulation" / "TwinSightSim" / "Assets" / "ThirdParty" / "Papabear"
KEEP = {".fbx", ".jpg", ".jpeg", ".png", ".tif"}
SKIP_NAMES = {"door.fbx"}  # 차량 일부(문)만 있는 모델


def is_lfs_pointer(path: Path) -> bool:
    with open(path, "rb") as f:
        return f.read(40).startswith(b"version https://git-lfs")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if not SOURCE.exists():
        sys.exit(f"에셋 폴더가 없습니다: {SOURCE}")

    seen: dict[str, Path] = {}
    copied = duplicates = pointers = 0
    for src in sorted(SOURCE.rglob("*")):
        if not src.is_file() or src.suffix.lower() not in KEEP or src.name.lower() in SKIP_NAMES:
            continue
        if is_lfs_pointer(src):
            pointers += 1
            continue
        # 같은 모델이 여러 세트에 들어 있으면 한 번만 쓴다. 텍스처는 모델 옆에 있어야 Unity가 찾으므로 모두 복사한다
        if src.suffix.lower() == ".fbx":
            digest = hashlib.sha256(src.read_bytes()).hexdigest()
            if digest in seen:
                duplicates += 1
                continue
            seen[digest] = src
        dst = TARGET / src.relative_to(SOURCE)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            shutil.copy2(src, dst)
        copied += 1

    print(f"복사 {copied}개 → {TARGET.relative_to(REPO)}")
    if duplicates:
        print(f"같은 내용이라 건너뜀 {duplicates}개")
    if pointers:
        print(f"⚠️ LFS로 아직 내려받지 않은 파일 {pointers}개를 건너뛰었습니다. git lfs pull --include=... 를 먼저 실행하세요.")


if __name__ == "__main__":
    main()
