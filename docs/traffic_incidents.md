# 신호·사고 시나리오와 영상 기반 경고

## 기존 작업 재사용

배우준 팀원의 `TrafficSpawner`, `WaypointMover`, `TrackedObject`, `RoadSurface`, `GroundTruthExporter`를 그대로 기반으로 사용합니다. 기존 생성기·이동기에 신호 참조와 이동 거리 제한을 추가하고, 기존 exporter에 신호·시나리오 정답 필드를 추가했습니다. 기존 공간 매핑·평가 코드도 계속 사용합니다. 추적은 기존 Ultralytics ByteTrack 백엔드를 연결하며 새 추적 알고리즘을 만들지 않았습니다.

신호등은 도시의 `Cylinder005_01 - Default_0` 모델과 원본 `01_-_Default_baseColor.jpeg`를 재사용합니다. 새 구·기둥으로 만든 신호등은 제거했습니다. 차량용은 기존 도시 모델을 정지선 위치에 맞추고, 보행자용은 같은 원본 모델을 축소·회전해 빨강/초록 상태로 사용합니다. 별도 보행자 아이콘 모델은 없으므로 현재 모양은 원본 신호등과 같습니다. 점등 제어 셰이더는 원본 UV의 렌즈 영역과 LED 무늬를 사용합니다.

도로·인도는 원본 `new road textures/wide road/`의 BaseColor 아틀라스를 사용합니다. 여러 폴더에 같은 파일 이름이 있어서 밝은 회색 버전이 연결되던 문제를 수정했습니다. 원본 FBX·텍스처 파일 자체는 수정하지 않습니다.

## 실행

1. 기존 City Lab을 열고 **TwinSight → City Lab → Install Signals and Incident Scenarios**를 실행합니다. 전체 City Lab 재생성에도 자동 포함됩니다.
2. Game 뷰에서 Play합니다. `TrainingScenarios` Inspector에서 시드·프로필·에피소드 길이를 조절할 수 있습니다.
3. **E**로 기존 이미지·정답 저장을 시작합니다. 프레임 정답에는 `signals`와 `scenario`가 추가됩니다.

Play 중 **TwinSight → City Lab → Capture Prototype Incident Dataset (Play Mode)**는 초기 학습용 64/16/16장 세션을 순서대로 수집합니다. 이 촬영에서는 이동 차량을 잠시 비활성화하고 시드·시점을 분리해 위험물이 가려지지 않게 합니다. 카메라 시점이 변하는 학습용 스틸 세션이므로, 고정 `camera.json`을 가정하는 Homography·추적 평가에는 사용하지 않습니다. 신호·사고 경고의 시간축 평가는 E로 저장한 고정 CCTV 연속 영상으로 합니다.

| 키 | 실험 장면 |
| --- | --- |
| 1 | 정상 주행 |
| 2 | 포트홀 |
| 3 | 콘크리트 낙하물 |
| 4 | 차량 추돌 |
| 5 | 차량의 콘크리트 방호벽 충돌 |

자동 에피소드는 기본 24초마다 바뀝니다. `automaticEpisodes`를 끄면 수동 장면을 유지합니다. 현재 포트홀은 기존 도로 위에 얕은 함몰 형태를 표현한 시각 모형입니다. 도로 메시·충돌체를 실제로 굴착하지는 않습니다. 보행자는 절차적으로 만든 단순 인체 모형이며 실제 사람 검출 성능을 보장하는 에셋은 아닙니다.

## 신호와 차량

차량 초록 12초 → 노랑 3초 → 전체 정지 2초 → 보행자 초록 10초 → 보행자 초록 점멸 3초 → 전체 정지 2초 순서입니다. 신호 시간은 Inspector에서 바꿀 수 있습니다.

- 보행자 초록에만 새 횡단을 시작하고, 남은 시간에 건널 수 없는 경우 기다립니다.
- 이미 횡단 중인 사람은 건너기를 마칩니다. 사람이 남아 있으면 차량 초록을 보류합니다.
- 횡단보도에 차량이 남아 있으면 보행자 초록을 보류합니다.
- 일반 차량은 노랑·빨강에서 앞범퍼가 정지선 **0.08 Unity 단위 전**에 멈춥니다. 이미 정지선을 통과한 차는 횡단 구간을 빠져나갑니다.
- 초록이어도 횡단보도 출구가 막혀 있으면 정지선에서 기다립니다. 앞차와는 0.25 단위 간격을 둡니다.
- 차량 생성은 **차로별 5.5~8.5초 간격, 최대 5대**, 출발점 간격은 3.0 단위입니다. 각 `TrafficSpawner`에서 조절합니다.

실험 교차로의 정지선은 outbound world X=6.8, inbound X=9.65입니다. 도시의 실제 측량 단위와 일치한다고 가정하지 않습니다. 의도적으로 충돌을 만드는 실험 차량은 일반 교통 회피와 별도로 움직입니다.

## 확률과 정답

| 프로필 | 정상 | 포트홀 | 낙하물 | 차량 추돌 | 구조물 충돌 |
| --- | --- | --- | --- | --- | --- |
| Training | 20% | 20% | 20% | 20% | 20% |
| Evaluation | 90% | 2.5% | 2.5% | 2.5% | 2.5% |

이 비율은 실험용 샘플링 설정이며 실제 사고 발생률을 뜻하지 않습니다. 학습 장면에서는 이상 상황을 자주 보여 주고, 정상 장면도 함께 유지합니다. 최종 평가는 별도 실제 CCTV 자료와 정상 위주의 자료에서도 해야 합니다.

충돌 연출은 동적 Rigidbody·BoxCollider로 접촉을 만들고 `OnCollisionEnter`에서 `physics_contact` 정답을 기록합니다. 충돌 예정 상태(`collision_setup`)와 실제 충돌은 구분됩니다. 낙하물은 중력으로 떨어져 노면에 닿은 시점을 별도 기록합니다. 이는 차체 변형·타이어 역학을 포함한 정밀 사고 재현기는 아닙니다.

`ground_truth.jsonl`의 `scenario.events`는 학습·평가 정답입니다. **경고 엔진은 이 필드, Unity 객체 이름, 실제 신호 정답을 읽지 않습니다.**

## 모델 결과로 경고하기

```powershell
.\.venv\Scripts\python.exe -m detection predict --source "<Unity저장폴더>" --alerts --save-images
.\.venv\Scripts\python.exe -m detection predict --source "<Unity저장폴더>" --road-weights "<학습모델>/best.pt" --alerts --follow --show
```

`--follow`는 Unity가 새 이미지와 프레임 정보를 저장하면 이어서 검출합니다. 마지막 기록 이후 10초간 입력이 없으면 종료합니다. 현재 연결은 파일을 매개로 하며 처리 속도는 CPU·입력 크기에 영향을 받습니다. OpenCV 화면과 콘솔에서 경고를 보여 주고 `alerts.jsonl`에 저장합니다.

| 경고 종류 | 영상에서 사용하는 근거 |
| --- | --- |
| `road_damage` | 포트홀·균열이 신뢰도 기준 이상으로 여러 프레임에 유지 |
| `road_debris` | 낙하물이 여러 프레임에 유지 |
| `suspected_vehicle_collision` | 추적된 차량의 접근·겹침 이후 급정지 |
| `suspected_vehicle_structure_collision` | 추적 차량과 검출된 방호벽의 겹침 이후 급정지 |

정지선 대기 영역은 사고 의심 경고에서 제외할 수 있고, 단순 박스 겹침이나 미추적 박스만으로 충돌을 경고하지 않습니다. 영상만으로 실제 접촉을 확정하지 못하므로 상태는 `unconfirmed`로 저장합니다. 경고에는 카메라·프레임·시각·근거 박스와 추적 ID가 포함되고 반복 경고에는 대기 시간을 둡니다.

COCO 기본 모델에는 포트홀·균열·낙하물·방호벽 클래스가 없습니다. 합성환경용 위험물 가중치 또는 별도 학습 가중치가 필요합니다. 기본 검출 누락이나 추적 실패가 있으면 충돌 경고도 누락될 수 있습니다. 합성 초기 모델과 실제 CCTV용 학습 완료 모델은 구분합니다.

제공하는 합성 실험 가중치는 `detection/models/scenario-hazards.pt`입니다. `git lfs pull --include="detection/models/scenario-hazards.pt"` 후 위 명령의 `--road-weights`에 지정합니다. 포트홀 연속 검출과 경고는 확인했지만 낙하물·합성 차량은 아직 누락이 있으며, 균열은 미학습입니다. 상세 평가 범위는 [모델 카드](../detection/MODEL_CARD.md)에 기록했습니다.

팀원의 추적 결과를 직접 사용할 수도 있습니다.

```powershell
.\.venv\Scripts\python.exe -m detection warn --detections "detections.jsonl" --out "alerts.jsonl" --context "road-context.json"
```

## 도로 구조 인식은 어떻게 분담하나

**도로 인식 모듈을 별도로 두고 결과를 결합하면 됩니다.** 차량·사람·위험물의 객체 검출은 현재 YOLO, 도로·차선·횡단보도·정지선 영역 인식은 배우준 담당의 OpenCV/Segmentation, 객체 ID는 정재헌 담당의 추적 모듈로 연결합니다. 같은 YOLO 계열을 쓰더라도 검출 모델의 클래스에 `road`를 추가하는 것만으로 도로 마스크나 차선 구조가 생기지는 않습니다. 필요하면 담당 모듈에서 YOLO segmentation 등 별도 모델을 선택할 수 있습니다.

현재 저장소에는 Homography 좌표 변환·박스 위치 보정·오차 평가가 있고, 도로/차선 자동 분할 구현은 확인되지 않았습니다. 이 작업에서는 도로 분할 모델을 새로 만들지 않았습니다. 경고 엔진의 연결 지점은 `road_polygon`과 `stop_zones`입니다.

```json
{
  "road_polygon": [[0.1, 0.3], [0.9, 0.3], [1.0, 1.0], [0.0, 1.0]],
  "stop_zones": [[[0.2, 0.6], [0.4, 0.6], [0.4, 0.8], [0.2, 0.8]]]
}
```

좌표는 0~1 이미지 좌표입니다. 이 예시는 구조 설명용이며 현재 CCTV에 바로 적용하는 좌표가 아닙니다. 담당자가 실제 도로 마스크에서 도로 polygon·정지 대기 영역을 만들어 전달하면 `--context`로 읽습니다. 그 결과와 객체 검출·추적을 경고 계층에서 결합하고, 세계 좌표가 필요하면 기존 Homography 모듈을 사용합니다.

## 합성 데이터 학습

시드·촬영 세션을 분리한 Unity 정답을 변환합니다. 같은 연속 영상의 프레임을 무작위로 나누지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m detection prepare-unity --train "<train세션>" --val "<val세션>" --test "<test세션>" --out datasets/incidents --classes pothole,debris,barrier
.\.venv\Scripts\python.exe -m detection check-data --data datasets/incidents/dataset.yaml
.\.venv\Scripts\python.exe -m detection train --data datasets/incidents/dataset.yaml --epochs 30 --imgsz 512 --device cpu
```

변환 결과의 `provenance.json`에 합성 데이터 여부와 원본 세션을 남깁니다. 현재 exporter의 가려진 영역까지 포함하는 박스는 최종 학습 전 검수가 필요합니다. 자동 변환 자체를 사람의 라벨 검수 완료로 표시하지 않습니다.
