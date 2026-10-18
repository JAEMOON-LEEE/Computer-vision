# 초기 검출 모델 및 실행 검증

검증일: 2026-10-18. 차량·보행자는 **COCO 사전학습 기준 모델**, 도로 위험물은 아래의 **합성환경 실험 모델**입니다.

| 항목 | 값 |
| --- | --- |
| 모델 | Ultralytics YOLO11n Detect, COCO 사전학습 |
| 로컬 가중치 | `detection/models/yolo11n.pt` (첫 실행 자동 다운로드, Git 제외) |
| SHA-256 | `0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1` |
| 런타임 | Python 3.11.9, Ultralytics 8.4.182, PyTorch 2.9.1+cpu, torchvision 0.24.1+cpu, OpenCV 4.11.0.86 |
| 추론 설정 | CPU, 4 threads, imgsz=640, confidence=0.25, IoU=0.7 |
| 검출 대상 | person / car / truck / bus / motorcycle / bicycle |
| COCO 모델에 없는 대상 | pothole / crack / debris / barrier (별도 위험물 모델 사용) |

## 실행 결과

| 확인 항목 | 결과 |
| --- | --- |
| 검출 모듈 자동 검사 | 14개 통과: 박스·클래스 ID·두 모델 연결·입력 시각·경로·라벨 누락·분할 유출 등 |
| 기존 매핑 모듈 검사 | 22개 통과, 새 검출 JSONL도 기존 reader로 읽음 |
| 공식 패키지의 bus.jpg | 버스 1대와 보행자 4명 검출. 라벨이 있는 평가 세트의 정확도 측정은 아님 |
| 위 이미지를 반복한 12프레임 MP4 | 12프레임 처리 완료, 매 프레임 버스 1대·사람 4명. OpenCV 영상 입력·시간 저장 확인용 |
| 기존 Unity CCTV 저장 이미지 8장 | 8개 JSONL 레코드·박스 이미지 저장 완료. truck 검출 15개, 화면에서 건물 오탐과 작은 차량 미검출 확인 |
| 차선 크기 검증용 수직 이미지 | 기본 설정에서 검출 0개. 이 시점·합성 외형에 대한 추가 학습 필요 |
| 도로 위험 학습 설정 | 데이터가 없는 상태에서는 검사 오류로 중단. 실제 추가 학습은 실행하지 않음 |

12프레임 MP4 실행에서 첫 프레임을 제외한 추론 평균은 **174.640 ms**, p95는 **214.053 ms**, 디코딩·박스 이미지 저장·초기 준비를 포함한 처리 속도는 **2.745 fps**였습니다. 현재 PC의 짧은 실행 측정이며, 서로 다른 실제 영상의 속도나 GPU 성능을 뜻하지 않습니다. 현재 검증에서 30fps 실시간 처리는 달성하지 않았습니다.

## 다음 학습의 기준

실제 CCTV 라벨과 검수한 합성 이미지를 확보한 뒤 실제 데이터만 학습한 모델과 실제+합성 모델을 분리된 실제 평가 자료에서 비교합니다. City Lab 원본에 포함된 정적 차량은 현재 자동 라벨 대상이 아니므로 빠진 라벨을 보완해야 합니다. Unity의 가려진 영역까지 포함하는 박스 역시 학습 라벨로 쓸 때 검수가 필요합니다.

이 모듈의 구현·동작 확인, 합성 데이터 학습, 실제 CCTV 성능 검증은 각각 구분합니다. 실제 CCTV 평가 자료는 아직 없습니다.

로컬 결과: `runs/detection/public-sample-baseline`, `video-baseline`, `unity-baseline`, `lane-fit-baseline`.

## 합성환경 위험물 실험 모델

원본 도시 재질을 복원한 Unity 이미지로 pothole / debris / barrier 세 종류를 학습했습니다. 균열은 아직 학습하지 않았습니다.

| 항목 | 값 |
| --- | --- |
| 실험 가중치 | `detection/models/scenario-hazards.pt` (Git LFS로 제공, `git lfs pull` 필요) |
| SHA-256 | `8e2e0be792f509045d9388f66160f19693e30cc8643089f00635fca070637b6e` |
| 최종 학습 | `runs/detection/train_20261018_180558_055177/road-visible` |
| 자료 | `datasets/scenario-safe`: train 64 / val 16 / test 16장, 서로 다른 시드·촬영 세션 |
| 설정 | 초기 합성 모델에 추가 12 epochs, imgsz 416, batch 4, mosaic 0, freeze 10, CPU |
| 별도 합성 test | precision 0.829, recall 0.811, mAP50 0.924, mAP50-95 0.635 |
| 클래스별 test recall | pothole 1.000 / debris 0.434 / barrier 1.000 |

test는 16장·12개 위험물뿐이고 같은 도시·외형을 공유합니다. 위 수치를 실제 CCTV 일반화 성능으로 해석하지 않습니다. 초기 `scenario-prototype` 자료는 차량 가림 문제가 있었으며, 최종 자료는 건물에 가리지 않는 시점과 위험물 라벨을 화면으로 확인했습니다. 자동 라벨 전체에 대한 사람의 검수 완료를 뜻하지 않습니다.

고정 CCTV 연속 영상 `fixed-pothole-warning_20261018_181843`에서 40/40프레임 포트홀 검출과 `road_damage` 경고 1건을 확인했습니다. 경고는 세 번째 프레임에 나왔으며 정답 객체·사고 이벤트를 추론에 사용하지 않았습니다. CPU 두 모델 실행의 warm 평균 132.895ms, 전체 처리 3.152fps였습니다. 결과는 `runs/detection/fixed-pothole-warning/`에 있습니다.

고정 낙하물 영상의 imgsz 416 실행은 40프레임에서 검출·경고가 없었습니다. 이 시점·작은 대상에 대한 추가 자료와 해상도 검증이 필요합니다. COCO 모델의 합성 차량·단순 보행자 검출도 충분하지 않습니다. 충돌 의심 규칙은 입력·추적 기반 자동 검사를 통과했지만, 현재 고정 CCTV 영상에서 모델로 충돌 경고까지 성공했다고 주장하지 않습니다.

최신 자동 검사: Python 검출/경고 26개, 기존 매핑 22개, Unity 신호·양방향 정지선·생성 빈도·사고 물리 접촉 20개 통과. Unity 결과는 `simulation/TwinSightSim/Logs/traffic-scenario-validation.json`에 있습니다.

공유용 검증 기록: [Unity 동작 검사](../docs/validation/traffic-scenario-validation.json), [합성 test 지표](../docs/validation/synthetic-hazards-test-metrics.json), [포트홀 경고 실행](../docs/validation/pothole-warning-summary.json), [경고 레코드](../docs/validation/pothole-alert.jsonl).

![모델의 포트홀 검출과 경고](../docs/images/pothole-warning.jpg)
