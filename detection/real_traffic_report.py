"""Package completed real-data experiments without fitting or changing selection."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/"runs/real-traffic-v1"
PUBLIC=ROOT/"docs/validation/real-traffic-v1"


def read(path):return json.loads(path.read_text(encoding="utf8"))
def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf8")


def main():
    objects=read(RUN/"object-complete.json");scenes=read(RUN/"incidents/completion.json")
    assert objects["status"]==scenes["status"]=="complete"
    assert objects["selection"]["test_used_for_selection"] is False
    assert scenes["test_used_for_selection"] is False
    models={}
    for name in ("real-traffic.pt","real-traffic.json","yolo11s.pt","real-incident-scene-v1.xml","real-incident-scene-v1.json"):
        path=ROOT/"detection/models"/name
        models[name]={"bytes":path.stat().st_size,"sha256":hashlib.sha256(path.read_bytes()).hexdigest()}
    assert models["real-traffic.pt"]["sha256"]==objects["selected_sha256"]
    assert models["real-incident-scene-v1.xml"]["sha256"]==scenes["model_sha256"]
    expected={"simulation-cctv-day-night.pt":"7dd2720a7bd8c8757c3a0f38b901b7e6dea46d68e97257916a6810b6947bf1a2",
        "simulation-cctv-collision-v2.pt":"d78544874cdc94bb6589997a9d8b7c14c384af91dd94ff1e2261fa884738346e",
        "collision-policy-v2.xml":"ec45078409b067d9b2b9af738c7f338a90cb570ae2ed678c9a1c7f73fcc99f6c"}
    for name,digest in expected.items():assert hashlib.sha256((ROOT/"detection/models"/name).read_bytes()).hexdigest()==digest
    ui=[]
    # Include only sessions for this work's known functional inputs and modes.
    for path in sorted((ROOT/"runs/validation-lab").glob("*/session.json")):
        data=read(path);options=data["options"]
        if options["model"] not in ("real-traffic","real-coco"):continue
        if options["source_label"] not in ("user-example-input.png","video106.mp4","00016301.jpg"):continue
        frames=[json.loads(line) for line in (path.parent/"detections.jsonl").read_text(encoding="utf8").splitlines()]
        alerts=[json.loads(line) for line in (path.parent/"alerts.jsonl").read_text(encoding="utf8").splitlines()] if (path.parent/"alerts.jsonl").exists() else []
        ui.append({"session_id":data["session_id"],"options":options,"model_off":not data["enabled"],"frames":len(frames),
            "classes":data["detections_by_class"],"alerts":alerts,"reports_saved":len(list(path.parent.glob("report-*.json"))),
            "independent_accuracy_test":False,"contact_timing_verified":False})
    assert any(r["options"]["real_incident_scene"] and r["alerts"] and r["model_off"] for r in ui)
    assert any(r["options"]["model"]=="real-traffic" and r["frames"]==1 and r["reports_saved"] for r in ui)
    assert all(r["model_off"] for r in ui)
    tests=(RUN/"tests-finished.log").read_text(encoding="utf8",errors="replace")
    assert "113 passed" in tests
    completion={"status":"complete","completed_at":datetime.now(timezone.utc).isoformat(),
        "real_vehicle_finetuning_complete":True,"real_scene_training_complete":True,"production_ready":False,
        "models":models,"previous_models_unchanged":expected,"object_test":objects["test"],
        "scene_validation":scenes["selection"],"scene_test":scenes["test"],
        "scene_labels":"weak source clip labels; no physical contact or participant supervision",
        "scene_validation_gate_passed":scenes["alerts_enabled"],"scene_manual_opt_in_only":True,
        "default_vehicle_mode":"real-coco","mio_vehicle_selection":objects["selection"]["selected"],
        "camera_disjoint_evaluation":False,"night_specific_real_accuracy_evaluated":False,
        "all_data_under_D":True,"source_video_redistributed":False,"github_pushed":False,"team_database_modified":False,
        "tests_passed":113,"subtests_passed":7,"typescript_and_vite_build":"passed",
        "ui_cases":ui,"dashboard_url":"http://127.0.0.1:5174/lab",
        "known_failures":["MIO-trained model labels user work truck rear as car; COCO-s detects truck",
            "MIO val large bus omitted by selected model in UI",
            "MIO test truck27/75 with46 false positive boxes; bus6/14",
            "real scene test misses7/16 accident clips; false warnings3/16 normal clips",
            "scene warnings do not establish physical contact onset or participants"]}
    write(RUN/"work-complete.json",completion);write(PUBLIC/"completion.json",completion)
    write(PUBLIC/"object-selection.json",objects["selection"])
    write(PUBLIC/"objects.json",objects["test"])
    write(PUBLIC/"scene-selection.json",{k:v for k,v in scenes.items() if k!="test"})
    write(PUBLIC/"scenes.json",scenes["test"])
    write(PUBLIC/"ui-verification.json",{"functional_only":True,"cases":ui,"bus_miss_recorded":True})
    for source,target in ((RUN/"detector/results.csv",PUBLIC/"training.csv"),(RUN/"tests-finished.log",PUBLIC/"tests.log")):
        shutil.copy2(source,target)
    write(RUN/"work-state.json",{"status":"complete","model_off":True,"production_ready":False})
    before=objects["test"]["previous_synthetic"]["classes"];after=objects["test"]["selected_real"]["classes"]
    section="\n\n## 완료 결과 (2026-10-25)\n\n"
    section+="실제 CCTV 차량 학습8회와 후보 비교를 완료했다. 선택된 추가 학습 모델은 `mio_n`이다. val의 승용차·트럭·버스 AP50평균은 COCO11n0.3057, COCO11s0.3965, MIO 학습0.5357이다. 시험 데이터로 후보를 다시 선택하지 않았다.\n\n"
    section+="아래는 고정된 MIO test146장의 confidence0.25/IoU0.5 결과다. 카메라 독립·실제 고속도로 전체 성능을 뜻하지 않는다.\n\n|종류|정답 박스|이전 합성 모델 검출|실제 CCTV 학습 모델 검출|새 오탐 박스|\n|---|---:|---:|---:|---:|\n"
    labels={"person":"보행자","car":"승용차","truck":"트럭","bus":"버스","motorcycle":"오토바이","bicycle":"자전거"}
    for name,label in labels.items():
        a,b=before[name],after[name]
        section+=f"|{label}|{b['ground_truth']}|{a['true_positives']}|{b['true_positives']}|{b['false_positives']}|\n"
    section+="\n트럭 재현율36%, 버스42.9%로 여전히 미흡하고, 오토바이 시험은2개뿐이다. 원래 합성 모델에 없던 클래스도 포함한 비교다. 여섯 클래스 평균 AP50은0.0824→0.4834, 승용차 재현율46.2%→79.4%다.\n\n"
    section+="실제 사고 장면 분류는 train96클립에서2,056개 특징을 학습했다. val24에서 사고12/12·정상 오경고1/12로 깊이3/임계값0.55를 고정했다. 공식 test32의 결과는 **사고9/16, 정상 오경고3/16**이다. 사고7개를 놓쳤으며 정상 경고0건을 달성하지 못했다. 이 수치는 약한 영상 라벨에 대한 장면 판정이고 충돌 순간·참여 차량 정확도가 아니다.\n\n"
    section+="대시보드의 실제 영상 범용 모델로 사용자 영상 정지 화면의 작업 트럭 박스, 별도 TAD validation video106의0~5초/5fps26프레임 처리·1.2초 장면 경고·자동OFF·D 보고서 저장을 확인했다. 경고 시각을 물리적 접촉 정답으로 확인한 것은 아니다. MIO 모델의 큰 버스 누락 사례도 결과에 남겼다.113개 검사·7subtests·TypeScript/Vite 빌드 통과.\n\n"
    section+="가중치·원본 영상·라벨·특징·비교 결과는 D에 보존했다. 기존 합성 모델3개의 SHA가 변하지 않았음을 확인했다. 이번 작업에서 GitHub 업로드나 팀 DB 변경은 하지 않았다.\n\n[전체 증빙](validation/real-traffic-v1/completion.json) · [객체별 결과](validation/real-traffic-v1/objects.json) · [실제 사고 장면 시험](validation/real-traffic-v1/scenes.json) · [화면 기능 검사](validation/real-traffic-v1/ui-verification.json)\n"
    doc=ROOT/"docs/real_traffic_training.md";text=doc.read_text(encoding="utf8").split("\n\n## 완료 결과 (2026-10-25)")[0]
    doc.write_text(text.rstrip()+section,encoding="utf8")
    print("REAL TRAFFIC WORK COMPLETE",len(ui),"UI sessions",flush=True)


if __name__=="__main__":main()
