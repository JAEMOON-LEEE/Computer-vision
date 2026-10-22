# TwinSight 객체 검출 모델

이진규 담당의 객체 검출 모듈입니다. Ultralytics YOLO와 OpenCV로 실행하며, 기본 COCO 사전학습 모델과 Unity 합성데이터로 추가 학습한 모델을 제공합니다. 배우준 팀원의 Unity 저장 형식을 입력으로 읽고, 같은 `detections.jsonl` 계약으로 결과를 출력합니다. 객체 추적과 공간 매핑은 기존 팀 모듈을 재사용합니다.

**학습 모델·데이터 다운로드:** [공유 자료와 복원 방법](../training_artifacts/README.md). 최신 주간·야간 실험 모델은 `detection/models/simulation-cctv-day-night.pt`, 대응 충돌 경고 모델은 `stop-zone-collision-day-night.xml`과 같은 이름의 JSON입니다. 야간 사고 누락이 남은 실험 후보이며 기본값을 실사용 모델로 자동 변경하지 않습니다.

**신호·사고·경고 확장:** [실험 안내](../docs/traffic_incidents.md)를 참고합니다. `--alerts`는 기존 ByteTrack을 연결해 영상 기반 경고를 만들고, `warn`은 팀원의 추적 결과를 직접 받아 경고합니다. `--follow`는 Unity의 새 저장 프레임을 이어서 읽습니다.

## 현재 가능한 범위

| 대상 | 현재 상태 |
| --- | --- |
| 차량·보행자 | COCO 기본 모델 및 주간·야간 합성데이터 추가 학습 모델 제공. 실제 CCTV 정확도 검증은 별도 필요 |
| 교통 클래스 | `person`, `car`, `truck`, `bus`, `motorcycle`, `bicycle` |
| 도로 결함·낙하물 | 합성 포트홀·낙하물·구조물 학습 완료. 균열은 미학습. 야간 사고 경고와 실제 CCTV 오탐 보완 필요 |

클래스 이름을 추가하는 것만으로 새 대상을 검출할 수는 없습니다. COCO 기본 모델은 도로 결함·낙하물을 검출하지 않으며, 프로젝트 학습 모델을 `--weights`로 지정해야 합니다. 실행 결과의 `capabilities.unavailable`에서 미지원 클래스를 확인합니다.

## 설치 (Windows, Python 3.11)

저장소 루트에서 실행합니다. 현재 PC에는 이 전용 가상환경을 구성했습니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r detection/requirements-cpu.txt
```

CPU 설치는 검증용입니다. NVIDIA GPU를 사용할 환경은 해당 CUDA에 맞는 PyTorch·torchvision을 먼저 설치하고 `detection/requirements.txt`를 설치한 뒤 `--device 0`을 지정합니다. 기본값은 CPU이며 실시간 처리 속도는 `summary.json`의 실제 측정값으로 확인합니다.

## 검출 실행

### Unity 환경에서 저장한 이미지

Unity City Lab에서 Game 뷰를 연 상태로 Play 후 **E**를 눌러 저장합니다. `<Unity저장폴더>`에는 `ground_truth.jsonl`과 `frames/`가 있어야 합니다.

```powershell
.\.venv\Scripts\python.exe -m detection predict --source "<Unity저장폴더>" --save-images
```

Unity 정답 라벨은 추론에 사용하지 않습니다. 프레임 번호·시뮬레이션 시간·카메라 ID·이미지 경로만 유지합니다. 현재 연결은 **Unity 저장 → Python 검출**입니다. Unity 화면에 실시간으로 박스를 다시 그리는 연결은 별도 작업입니다.

### CCTV 녹화 영상·웹캠·영상 스트림

```powershell
.\.venv\Scripts\python.exe -m detection predict --source "video.mp4" --show --save-images
.\.venv\Scripts\python.exe -m detection predict --source 0 --show --max-frames 300
.\.venv\Scripts\python.exe -m detection predict --source "rtsp://camera/stream" --camera-id cctv-01 --show
```

이미지 한 장 또는 이미지 폴더도 입력할 수 있습니다. 창에서 Q/Esc, 콘솔에서 Ctrl+C로 종료합니다. `--stride 2`는 두 프레임마다 하나를 검출하고 원래 프레임 번호를 유지합니다. 저장 프레임 수 제한은 `--max-frames`, 해상도는 `--imgsz 640`, 신뢰도는 `--conf 0.25`로 조절합니다. `--show`를 생략하면 창 없이 저장합니다.

## 출력과 팀 연동

기본 출력은 `runs/detection/<실행시각>/`입니다. `--out <빈폴더>`로 바꿀 수 있습니다.

- `detections.jsonl`: 프레임별 박스·클래스·신뢰도. 미검출 프레임도 빈 배열로 저장합니다.
- `annotated/*.jpg`: 박스를 그린 이미지(`--save-images`).
- `session.json`: 모델 경로·이름별 클래스 ID·설정·지원 클래스·실행 상태.
- `summary.json`: 클래스별 검출 수, 처리 FPS, 첫 프레임 이후 평균·p95 추론 시간. 정확도 지표가 아닙니다.

`session.json`에 라이브러리 버전과 가중치 SHA-256도 남깁니다. 첫 프레임만 처리한 실행은 준비 시간이 섞이므로 warm 지표를 `null`로 기록합니다.

`class_id`는 **각 모델의 원래 ID**이고 `model_id`와 함께 해석합니다. `category_id`는 이 모듈에서 정한 고정 ID로 `person=0, car=1, truck=2, bus=3, motorcycle=4, bicycle=5, pothole=6, crack=7, debris=8, barrier=9`입니다. 기존 매핑 모듈은 `class_name`을 사용하므로 호환됩니다. 팀 전체의 최종 ID 규약은 합의 후 확정합니다.

박스는 원본 영상 픽셀의 `[x1,y1,x2,y2]`, `ground_point_px`는 박스 아래 중앙입니다. 기본 `track_id`는 `null`이고 `--track` 또는 `--alerts`를 사용하면 기존 ByteTrack 백엔드가 부여합니다. 팀원의 추적 모듈 결과를 `warn` 명령에 직접 넣을 수도 있습니다. 스트림의 `timestamp`는 OpenCV 수신 시각(Unix 초)이며 카메라 촬영 시각은 아닙니다. 녹화 영상은 FPS 기준 영상 시간, Unity는 원래 시뮬레이션 시간을 유지합니다.

기존 매핑 평가에 연결하려면 다음처럼 검출 파일을 지정합니다. 옵션은 `mapping/scripts/evaluate_mapping.py --help`에서 확인합니다.

```powershell
python mapping/scripts/evaluate_mapping.py "<Unity저장폴더>" --detections "<검출폴더>/detections.jsonl" --classes car
```

도시 원본의 정적 차량에는 현재 Unity 정답 라벨이 없습니다. 이 차량을 모델이 검출하면 미라벨 대상이므로 곧바로 오탐으로 해석하면 안 됩니다. 학습·검출 정확도 평가용 데이터는 모든 대상의 라벨과 가림 처리를 검수해야 합니다. 현재 생성 영상만으로 실제 CCTV 정확도를 주장하지 않습니다.

## 도로 결함·낙하물 추가 학습

우선 도로 위험 3종을 별도 모델로 학습하면 기존 차량·보행자 검출 능력을 유지하면서 연결할 수 있습니다. 라벨은 객체 검출용 사각형이며 정밀한 균열 마스크·도로 영역 분할과는 구분합니다.

데이터를 아래처럼 준비하고 `configs/road.example.yaml`을 복사해 실제 경로를 적습니다. 라벨은 한 줄에 `클래스ID 중심x 중심y 폭 높이`이며 좌표는 0~1로 정규화합니다. 로컬 ID는 YAML의 이름 순서에 맞춥니다. 검수한 배경 이미지는 빈 `.txt` 파일을 둡니다.

```text
datasets/road/
  images/train/   images/val/   images/test/
  labels/train/   labels/val/   labels/test/
```

같은 CCTV·촬영 세션의 연속 프레임을 train/val/test에 섞지 않습니다. 별도 촬영 세션·카메라로 나누고 실제 CCTV 평가 세트를 학습에서 분리합니다. 검사기는 잘못된 박스·누락 라벨·각 클래스의 샘플 부족(0개)·분할 간 완전히 같은 이미지를 차단하지만 유사 프레임까지 판단하지는 못합니다.

```powershell
.\.venv\Scripts\python.exe -m detection check-data --data detection/configs/road.example.yaml
.\.venv\Scripts\python.exe -m detection train --data detection/configs/road.example.yaml --weights yolo11n.pt --epochs 100 --device 0
.\.venv\Scripts\python.exe -m detection validate --data detection/configs/road.example.yaml --weights "<학습폴더>/weights/best.pt" --split test --device 0
.\.venv\Scripts\python.exe -m detection predict --source "video.mp4" --road-weights "<학습폴더>/weights/best.pt" --show
```

`validate`는 precision·recall·mAP 등을 저장합니다. 학습된 가중치는 `runs/detection/train_<시각>/twinsight/weights/best.pt`에 생깁니다. 기본 모델 가중치와 데이터셋의 클래스 순서가 다르면 학습 시 새 출력층을 구성합니다. 향후 9종을 모두 충분히 라벨링하면 `configs/all.example.yaml`로 통합 모델을 학습하고 `--weights best.pt` 하나로 실행할 수 있습니다.

영상·데이터셋·실행 결과와 일반 학습 가중치는 Git에서 제외합니다. 아래 실험용 위험물 가중치만 Git LFS로 제공합니다. 초기 실행은 공식 YOLO 가중치를 `detection/models/`에 내려받으며 별도 유료 API가 필요하지 않습니다.

## 검증

2026-10-20 가상환경의 차량·보행자·포트홀·낙하물·방호벽을 함께 학습한 로컬 모델 `detection/models/simulation-detection.pt`를 추가했습니다. 촬영·학습 재현 방법과 제한 사항은 [가상환경 추가 학습](../docs/synthetic_training.md)을 참고하세요. 이 모델은 `--weights detection/models/simulation-detection.pt`로 실행합니다.

합성 위험물 실험 가중치 `detection/models/scenario-hazards.pt`를 Git LFS로 제공합니다. 저장소를 받은 뒤 `git lfs pull --include="detection/models/scenario-hazards.pt"`로 내려받으세요. 포트홀·낙하물·방호벽을 학습했고, 균열은 미학습입니다. 실제 CCTV 성능과 합성 차량 검출에는 추가 학습이 필요하며, 세부 검증 범위는 아래 모델 카드에 기록했습니다.

```powershell
.\.venv\Scripts\python.exe -m detection predict --source "<Unity저장폴더>" --road-weights detection/models/scenario-hazards.pt --imgsz 416 --alerts --save-images
```

신호·사고 설정과 도로 인식 담당 모듈의 연동은 [실험 안내](../docs/traffic_incidents.md)를 참고합니다.

실행한 입력과 측정값, 현재 미검출·오탐 사례는 [MODEL_CARD.md](MODEL_CARD.md)에 기록했습니다.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s detection/tests -v
```

기존 코드와의 구분: 팀원 구현인 `mapping/scripts/run_yolo_on_frames.py`는 단순 프레임 검출·추적 실행 도구로 보존했습니다. 이 모듈은 검출 클래스 관리, 이미지·영상·웹캠 입력, 선택적 도로 위험 모델, 학습·평가·데이터 검사와 실행 기록을 추가합니다.

설계 근거: [YOLO11 모델](https://docs.ultralytics.com/models/yolo11/), [YOLO 라벨 형식](https://docs.ultralytics.com/datasets/detect/), [학습](https://docs.ultralytics.com/modes/train/), [추론](https://docs.ultralytics.com/modes/predict/).

- 사진 시점의 CCTV 복원·원거리 보강 학습·경고 재검사: [고정 CCTV 학습](../docs/cctv_training.md)

- 신호 대기 구역 내부 사고와 정상 대기 구분 학습: [학습·실행 안내](../docs/stop_zone_training.md)

- 실제 CCTV 연결·야간 검출 확인과 남은 한계: [실제 CCTV 검증](../docs/real_cctv_validation.md)

- 낮·밤 환경 선택과 야간 합성 보강 학습: [야간 학습](../docs/day_night_training.md)
