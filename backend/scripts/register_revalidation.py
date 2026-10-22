"""Prepare a fresh frozen-model verification report and its immutable catalog record."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from register_experiment_catalog import Builder, canonical


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def prediction_hash(path):
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
    for row in rows:
        row.pop("inference_ms", None)
    return hashlib.sha256(canonical(rows).encode()).hexdigest()


def prepare(repo, run, team_root):
    if not (run/"summary.json").exists():
        raise ValueError("Finish fresh inference first")
    docs = repo/"docs/validation"/run.name
    docs.mkdir(parents=True, exist_ok=True)
    database = run/"database"
    if database.exists():
        raise ValueError("Preserve immutable registration; choose a new run")
    summary = read(run/"summary.json")
    storage = read(run/"storage-check.json")
    if not storage["all_d_hashes_match"] or not storage["known_C_copies_absent"]:
        raise ValueError("Storage revalidation requires review before registration")
    prior = repo/"runs/night-v1"
    comparisons = []
    for folder in sorted((run/"temporal").iterdir()):
        if folder.is_dir():
            comparisons.append((folder/"detections.jsonl", prior/"temporal-combined"/folder.name/"detections.jsonl"))
    for domain in ["day", "night"]:
        comparisons.extend((run/("warnings-"+domain)/case/"detections.jsonl",
                            prior/"warning-checks"/domain/case/"detections.jsonl")
                           for case in read(run/("warnings-"+domain)/"verification.json")["cases"])
        comparisons.append((run/("detection-"+domain)/"detections.jsonl",
                            prior/"evaluation"/(domain+"-after")/"detections.jsonl"))
    comparisons.append((run/"real-night/detections.jsonl", prior/"evaluation/real-night-after/detections.jsonl"))
    reproducibility = {"timing_excluded": True, "comparisons": [
        {"output": str(new.relative_to(repo)), "prior": str(old.relative_to(repo)),
         "same_predictions": prediction_hash(new) == prediction_hash(old)} for new, old in comparisons]}
    reproducibility["all_same_predictions"] = all(e["same_predictions"] for e in reproducibility["comparisons"])
    (run/"reproducibility.json").write_text(json.dumps(reproducibility, ensure_ascii=False, indent=2), encoding="utf-8")
    (docs/"summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (docs/"reproducibility.json").write_text(json.dumps(reproducibility, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# 주간·야간 모델 재검증", "", "모델·임계값을 고정하고 별도 출력 폴더에서 새로 추론했다. 재학습·시험 자료에 의한 조정은 하지 않았다.", "",
             "합성 스틸72장, 신호 대기 검증·시험40영상(1,600프레임), 일반 경고10영상(900프레임), 보존된 실제 야간 영상600프레임을 검사했다.", "",
             "| 합성 이미지 시험 | 이미지 | mAP50 |", "| --- | ---: | ---: |"]
    for domain in ["day", "night"]:
        result = summary["detection"][domain]
        lines.append(f"| {domain} | {result['images']} | {result['mAP50_101point']:.4f} |")
    lines += ["", "mAP는 IoU0.5·101점 보간 AP 평균이다. 실제 CCTV 정확도를 뜻하지 않는다.", "",
              "| 신호 대기 | 사고 접촉 이후 엄격 통과 | 경고 발생 영상 | 정상 영상 | 정상 경고 |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for name, result in summary["temporal"].items():
        total = result["accident_clips"]
        lines.append(f"| {name} | {result['strict_passes']}/{total} | {result['any_warning_clips']}/{total} | {result['normal_clips']} | {result['normal_alert_count']} |")
    lines += ["", "정상 대기24영상(960프레임)에서 경고0건이다. 평가 범위를 넘는 무오탐 보장은 아니다.", "",
              "| 일반 경고 | Normal | Pothole | FallingDebris | VehicleCollision | StructureCollision |",
              "| --- | --- | --- | --- | --- | --- |"]
    for domain in ["day", "night"]:
        cases = summary["warning_cases"][domain]["cases"]
        lines.append("| "+domain+" | "+" | ".join(f"{'통과' if r['passed'] else '실패'} ({sum(r['alerts'].values())}건)" for r in cases.values())+" |")
    lines += ["", "## 남은 실패", ""]
    for group in summary["temporal"].values():
        for failure in group["failures"]:
            latency = failure.get("alert_latency_seconds")
            text = "경고 누락" if latency is None else f"접촉 대비 {latency:+.6f}초 경고(접촉 이전이면 엄격 검사 실패)"
            lines.append(f"- `{failure['clip']}`: {text}.")
    lines += ["", "일반 야간 StructureCollision에서도 경고가 누락됐다. 전체 경고 검증은 실패이며 모델은 실험 후보로 유지한다.", "",
              "## 실제 CCTV", "", "새 실시간 영상이 아니라 같은 원본 PTS를 유지한 기존120초 녹화600프레임을 재추론했다. 실제 정답 라벨이 없어 mAP·사고 재현율은 계산하지 않는다.", "",
              f"누적 검출 박스: {json.dumps(summary['real']['detections_by_class'], ensure_ascii=False)}. 경고: {json.dumps(summary['real']['alerts_by_type'], ensure_ascii=False)}. 누적 박스 수에는 반복 검출·오탐이 포함된다.", "",
              "재추론 프레임300을 육안 확인했을 때 하단 자막 두 곳을 차량으로 오인했고, 전조등 번짐 주변 실제 차량 누락도 남아 있었다. 실제 CCTV 일반화가 해결됐다는 근거는 없다.", "",
              f"실행 시간값을 제외한 예측 결과 {len(comparisons)}묶음의 이전 결과 일치 여부: {reproducibility['all_same_predictions']}.", "",
              "## 저장 위치·DB 무결성", "",
              "이전 C→D 이동7개 파일과 기존 원본·산출물8,927개의 D 파일 해시를 다시 검사했다. 알려진 이전 C 원본7개와 프로젝트 경로5곳에 남은 사본은 없었다.", "",
              "기존 DB 압축본2개(총337,626,424바이트)의 모든1MiB 블록 SHA256을 D 압축본과 대조했다. D 압축본의 전체 SHA256과 DB 파일 인덱스도 검사했다. 범위·상세 결과는 `storage-check.json`에 기록했다.", "",
              "원본·모델은 D드라이브에 보존한다. 신규 예측·평가 파일은 DB 원본 압축 보관 및 복원 해시 검사 대상이며, DB 저장 증빙은 이 폴더의 별도 JSON을 확인한다."]
    (docs/"report.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    (docs/"storage-check.json").write_text(json.dumps(storage, ensure_ascii=False, indent=2), encoding="utf-8")
    b = Builder(repo, team_root, repo/".env.database", "origin/codex/local-db-validation@3bddc0d")
    old = b.read_json(repo/"runs/night-v1/database/catalog-manifest-final.json")["records"]
    parents = [e["record"]["record_id"] for e in old if e["record"]["title"] in
               {"model-day-night-v1", "model-day-night-temporal", "evaluation-day-night-v1"}]
    if len(parents) != 3:
        raise ValueError("Missing prior model/evaluation provenance")
    files = b.paths(run)+b.paths(docs)+[repo/"detection/revalidate_day_night.py", Path(__file__).resolve(), run.with_suffix(".log")]
    key = b.add("evaluation-"+run.name, "evaluation", "mixed", files,
                {"summary": summary, "storage_revalidation": storage,
                 "all_same_predictions": reproducibility["all_same_predictions"],
                 "fresh_inference": True, "new_live_capture": False, "training_performed": False,
                 "source_archive_record": "night-v1-binary-archive-a1c5db40f6f2a3e1b295a1cd",
                 "original_model_bytes_archive": "night-v1-binary-archive-f9af09938cf2fe438d04bc8f"},
                parents=parents, status="failed" if not summary["all_warning_checks_passed"] else "completed")
    database.mkdir()
    manifest = {"format": "twinsight-catalog-import-v1", "workspace": str(repo.parent),
                "source_catalog_code": b.code_ref, "records": b.records, "excluded": b.excluded}
    (database/"catalog-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (database/"archive-file-list.json").write_text(json.dumps([str(p) for p in files], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evaluation_record": key, "files": len(files), "all_same_predictions": reproducibility["all_same_predictions"]}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", required=True, type=Path)
    p.add_argument("--team-code-root", required=True, type=Path)
    a = p.parse_args()
    prepare(Path.cwd().resolve(), a.run.resolve(), a.team_code_root.resolve())
