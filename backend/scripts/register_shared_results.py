"""저장소의 실제 공유 모델/평가 보고서를 등록한다. 학습이나 평가를 재실행하지 않는다."""
import argparse
import json
from pathlib import Path
import sys

import httpx

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from backend.scripts.catalog import file_info, read_json, register, write_json

EXPECTED_MODEL_SHA = "8e2e0be792f509045d9388f66160f19693e30cc8643089f00635fca070637b6e"


def manifests(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    model = file_info(ROOT, {"path": "detection/models/scenario-hazards.pt", "role": "model"})
    if model["sha256"] != EXPECTED_MODEL_SHA:
        raise ValueError("모델 카드의 SHA-256과 파일이 다릅니다. LFS 다운로드와 모델 버전을 확인하세요")
    metrics_path = "docs/validation/synthetic-hazards-test-metrics.json"
    metrics = file_info(ROOT, {"path": metrics_path, "role": "metrics"})
    card = file_info(ROOT, {"path": "detection/MODEL_CARD.md", "role": "model_card"})
    model_id = "model-scenario-hazards-" + model["sha256"][:12]
    evaluation_id = "evaluation-scenario-hazards-" + metrics["sha256"][:12]
    common = {"owner": "이상민", "data_origin": "synthetic", "status": "completed"}
    bodies = [
        {"record": {**common, "record_id": model_id, "kind": "model", "title": "공유 합성 위험물 모델",
                    "parents": [], "details": {"source": "repository_shared_artifact", "model_sha256": model["sha256"],
                    "lineage_gaps": ["원본 학습 데이터셋과 학습 실행 폴더가 없어 해당 자료의 부모 관계는 미등록"],
                    "not_retrained_here": True}}, "files": [model, card]},
        {"record": {**common, "record_id": evaluation_id, "kind": "evaluation", "title": "공유 합성 test 평가 보고서",
                    "parents": [model_id], "details": {"metrics": read_json(ROOT / metrics_path),
                    "model_link_basis": "MODEL_CARD.md의 모델 SHA 및 합성 test 보고서 설명",
                    "not_reexecuted_here": True, "real_cctv_validation": False}}, "files": [metrics, card]},
    ]
    paths = []
    for body in bodies:
        body.update(root=str(ROOT), log_files=[])
        path = output / (body["record"]["record_id"] + ".json")
        if path.exists():
            if read_json(path) != body:
                raise ValueError("공유 보고서 내용이 변경되었습니다. 새 버전 manifest를 작성하세요")
        else:
            write_json(path, body)
        paths.append(path)
    return paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    paths = manifests(ROOT / "backend/data/catalog-manifests")
    with httpx.Client(base_url=args.api, timeout=60) as client:
        for path in paths:
            print(json.dumps(register(client, path), ensure_ascii=True))


if __name__ == "__main__":
    main()
