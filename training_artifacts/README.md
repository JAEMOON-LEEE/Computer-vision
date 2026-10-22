# 학습 모델과 합성데이터 공유

2026-10-22까지 학습한 모델, 학습·검증·시험 이미지와 YOLO 라벨, 촬영 원본 및 검증 결과를 함께 제공합니다. 큰 파일은 Git LFS로 저장합니다. 압축본 안의 같은 내용은 한 번만 보관하고 경로·크기·SHA256 인덱스로 복원합니다. JPEG 재인코딩이나 데이터 재분할은 하지 않았습니다.

## 모델

| 파일 (`detection/models/`) | 용도 |
| --- | --- |
| `simulation-cctv-day-night.pt` | 최신 주간·야간 YOLO 검출 후보: person, car, pothole, debris, barrier |
| `stop-zone-collision-day-night.xml` + `.json` | 위 검출기와 짝을 이루는 25특징 RTrees 충돌 경고 후보 |
| `simulation-cctv-queue.pt` + `stop-zone-collision-final.xml`/`.json` | 이전 주간·신호 대기 비교 모델 |
| `simulation-cctv.pt`, `simulation-cctv-base.pt` | 고정 CCTV·원거리 보강 단계 비교 모델 |
| `simulation-detection.pt`, `scenario-hazards.pt` | 초기 합성·위험물 학습 비교 모델 |
| 나머지 `stop-zone-collision*.xml`/`.json` | 이전 분류기 실험 보존본. 최신 모델과 임의로 조합하지 않습니다. |

최신 YOLO SHA256은 `7dd2720a7bd8c8757c3a0f38b901b7e6dea46d68e97257916a6810b6947bf1a2`입니다. 모든 모델과 압축본의 해시는 [manifest.json](2026-10-22/manifest.json)에 있습니다. 충돌 분류기의 JSON에 적힌 `detector_weights_sha256`과 YOLO가 일치해야 합니다.

## 데이터 구성

`2026-10-22/` 아래에 세 압축본을 제공합니다.

- `prepared-datasets.zip.xz`: 전처리한 데이터셋12버전의 이미지·YOLO 라벨·원래 train/val/test 분할·출처·설정. 최신 혼합 데이터 `day-night-v1`은580/200/200장입니다. 이전 버전과 원본·crop의 중복이 있으므로 버전별 이미지 수를 독립 표본 수로 더하지 않습니다.
- `synthetic-captures.zip.xz`: 학습·경고 시험에 사용한 합성 촬영 원본, 카메라·프레임 시각·정답 JSONL. 실제 CCTV 녹화 원본은 포함하지 않습니다.
- `experiment-results.zip.xz`: 학습 로그·체크포인트·검출·경고·평가 결과. 실제 CCTV에 대한 파생 검증 결과도 포함되지만, 정답 라벨이 없는 자료입니다.

초기 `scenario-prototype` 등 성능이 낮은 단계도 비교용으로 보존합니다. 실험 버전별 모델·자료를 임의로 합쳐 성능을 주장하지 않습니다. 미사용 공개 데이터, 폐기한 조명 촬영, 메모리 실패 실험, API 응답·서명 URL·비밀 환경파일·DB 복원 중복본은 제외합니다. Unity 자동 라벨은 전체 사람 검수가 완료되지 않았습니다.

## D드라이브에서 다운로드·복원

저장소를 D드라이브에 복제한 뒤 저장소 루트에서 실행합니다. 기존 작업 자료가 없는 새 복제본을 권장합니다. 기존 파일 내용이 다르면 복원 도구가 덮어쓰지 않고 중단합니다.

```powershell
git lfs install
git lfs pull --include="detection/models/*,training_artifacts/**"
$artifactWorkspace = Split-Path -Parent (Get-Location).Path
$env:TEMP = Join-Path $artifactWorkspace 'tmp'
$env:TMP = $env:TEMP
$env:PIP_CACHE_DIR = Join-Path $artifactWorkspace 'tools/pip-cache'
$env:YOLO_CONFIG_DIR = Join-Path $artifactWorkspace 'tools/ultralytics'
$env:TORCH_HOME = Join-Path $artifactWorkspace 'tools/torch-cache'
$env:HF_HOME = Join-Path $artifactWorkspace 'tools/huggingface-cache'
$env:XDG_CACHE_HOME = Join-Path $artifactWorkspace 'tools/cache'
$env:MPLCONFIGDIR = Join-Path $artifactWorkspace 'tools/matplotlib'
New-Item -ItemType Directory -Path $env:TEMP -Force | Out-Null
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r detection/requirements-cpu.txt

$artifactRoot = (Get-Location).Path
$artifactManifest = Get-Content training_artifacts/2026-10-22/manifest.json -Raw | ConvertFrom-Json
foreach ($artifactBundle in $artifactManifest.bundles) {
    .\.venv\Scripts\python.exe -m detection.artifacts --bundle $artifactBundle.file --root $artifactRoot --sha256 $artifactBundle.sha256
    if ($LASTEXITCODE -ne 0) { throw '데이터 복원 실패' }
}
```

도구는 모든 내부 파일 해시를 검사한 뒤 원래 저장소 상대 경로에 추출합니다. 새로 복원한 `datasets/*/dataset.yaml`은 실행 위치가 달라도 동작하도록 `path: .`로 바꾸며 원래 설정은 `dataset.original.yaml`에 보존합니다. 이미지·라벨·분할은 그대로입니다. 출처·과거 결과 JSON 안의 원래 절대 경로는 실험 기록으로 남아 있습니다.

최신 야간 합성 시험을 새 출력 폴더에서 실행하는 예입니다.

```powershell
.\.venv\Scripts\python.exe -m detection.evaluate_detection --data datasets/night-v1-full/dataset.yaml --weights detection/models/simulation-cctv-day-night.pt --out runs/team-night-evaluation --imgsz 640 --focus 0.3194444444444444,0.2708333333333333,0.6111111111111112,0.5625

.\.venv\Scripts\python.exe -m detection.verify_simulation --exports simulation/TwinSightSim/TwinSightExport --prefix night-v1-clip- --weights detection/models/simulation-cctv-day-night.pt --stop-model detection/models/stop-zone-collision-day-night.xml --out runs/team-night-warnings
```

두 번째 명령은 남아 있는 야간 구조물 충돌 누락 때문에 현재 실패 종료 코드가 나오는 것이 재현 결과입니다. 결과를 덮어쓰지 않도록 실행마다 새 `--out`을 지정합니다. `day-night-v1` 데이터셋으로 학습할 때 시험 분할을 튜닝에 사용하지 않습니다.

## 현재 성능과 한계

2026-10-22 재검증에서 합성 test mAP50은 주간0.9512, 야간0.9943입니다. 정상 신호 대기24영상의 경고는0건이고, 주간 일반 사고5종은 통과했습니다. 야간 신호 대기 사고 test4개 중3개에 경고가 발생했으며, 실제 접촉 이후 경고를 요구하는 엄격한 기준은2/4만 통과했습니다. 추돌 누락·구조물 조기경고와 일반 야간 구조물 충돌 누락이 남아 있습니다.

실제 야간 CCTV에는 자막 차량 오탐과 전조등 주변 누락이 남고 실제 정답 라벨은 없습니다. 합성 mAP를 실제 CCTV 정확도로 해석하지 않습니다. **실험 후보이며 실사용 검증 완료 모델이 아닙니다.** [전체 재검증 보고서](../docs/validation/revalidation-20261022-01/report.md), [모델 카드](../detection/MODEL_CARD.md), [낮·밤 학습 안내](../docs/day_night_training.md)를 함께 확인합니다.
