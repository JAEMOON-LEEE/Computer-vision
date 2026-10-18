# TwinSightSim — Unity 가상 CCTV 환경

Unity 도로 씬에 가상 CCTV를 두고, 렌더링 이미지와 정답(객체 박스, 바닥점의 실제 노면 좌표, 노면 기준점)을 함께 저장합니다. 저장 형식은 [docs/data_format.md](../../docs/data_format.md)를 따릅니다.

지금은 **공간 매핑 검증**이 첫 목표입니다. 가상환경에서는 모든 객체의 실제 위치를 정확히 알 수 있어서, Homography로 바꾼 좌표가 몇 m 틀리는지 숫자로 잴 수 있습니다. 같은 저장 데이터를 YOLO 합성 학습데이터로도 쓸 수 있습니다.

## 준비

1. Unity Hub를 설치하고, **Installs** 탭에서 에디터 **6000.6.6f1**이 설치 완료(Installed)인지 확인합니다. 이 프로젝트의 `ProjectSettings/ProjectVersion.txt`가 이 버전으로 되어 있습니다. 다른 Unity 6 버전으로 열면 Hub가 버전을 바꿀지 묻습니다.
2. Unity Hub → **Projects → Add → Add project from disk** → `simulation/TwinSightSim` 폴더(안에 `Assets`, `ProjectSettings`가 있는 폴더)를 선택합니다.
3. 처음 열 때 Unity가 나머지 설정 파일(`ProjectSettings/*.asset`), 기본 패키지 목록(`Packages/manifest.json`), 스크립트의 `.meta` 파일을 만듭니다. 이 파일들은 커밋하고, `Library/` 등 자동 생성 폴더는 `.gitignore`로 제외됩니다.
4. 렌더 파이프라인은 기본(Built-in)으로 충분합니다. 노트북 내장 그래픽(Intel Iris Xe 등)에서도 예제 씬이 돌아가는 수준입니다.

## 예제 씬으로 바로 실행

1. 상단 메뉴 **TwinSight → Create Demo Road Scene**을 누릅니다. 왕복 4차로 직선 도로, 도로변 높이 8 m 가상 CCTV, 노면 기준점 격자, 차로별 차량 생성기, 포트홀 3개가 들어간 `Assets/TwinSight/Demo/DemoRoad.unity`가 만들어집니다.
2. **Game 뷰를 연 상태로** Play를 누릅니다. 15초 동안 차량이 도로에 퍼지게 기다린 뒤 300프레임(10 fps 기준 30초)을 저장하고 자동으로 멈춥니다.
3. 저장 위치는 `simulation/TwinSightSim/TwinSightExport/virtual-cam-01_<날짜_시각>/`입니다(Console 창에도 출력됨).
4. 평가합니다.

```bash
python mapping/scripts/evaluate_mapping.py simulation/TwinSightSim/TwinSightExport/<저장 폴더> --max-distance 80 --sweep
```

처음 한 번은 결과 맨 위의 `카메라 정보 재투영 최대 오차`가 1 px 미만(정상)인지 확인합니다. 1 px을 넘으면 Unity 쪽 카메라 정보 저장이 Python 쪽 계산과 맞지 않는다는 뜻이므로 결과를 믿기 전에 원인을 찾아야 합니다.

예제 차량은 상자 모양이라 사전학습 YOLO가 차로 인식하지 못합니다. 공간 매핑 검증(정답 박스 기준)에는 충분하고, YOLO까지 평가하려면 아래처럼 실제 3D 에셋으로 바꿉니다.

## 3D 에셋으로 바꾸기

저장소에 있는 도시와 SUV·Mini 에셋을 조합한 실험 씬은 **TwinSight → City Lab → Build City Traffic Lab**으로 생성합니다. 바퀴 분리·회전, 양방향 주행, CCTV 및 정답 저장 방법은 [도시·차량 실험 환경 안내](../../docs/city_lab.md)를 참고하세요.

| 대상 | 할 일 |
| --- | --- |
| 차량 모델 | 프리팹 피벗을 **바닥 중심**에, 앞을 **+z**로 맞춥니다. 모델 Import Settings에서 **Read/Write**를 켜면 정답 박스가 메시에 꼭 맞습니다(끄면 회전된 상자 박스를 씀). 각 차로의 `TrafficSpawner → Prefabs`에 넣고 `Class Name`을 YOLO 이름(`car`, `truck`, `bus`, `motorcycle`)과 같게 적습니다. |
| 도로·인도 모델 | Collider(MeshCollider 등)를 붙이고 `RoadSurface` 컴포넌트를 붙입니다. 기준점과 차량 높이는 `RoadSurface`가 붙은 면에만 놓입니다. |
| 보행자·낙하물·포트홀 | `TrackedObject`를 붙이고 `Class Name`을 적습니다(`person`, `debris`, `pothole`). 애니메이션 캐릭터(SkinnedMeshRenderer)도 현재 자세로 박스를 계산합니다. |
| 실제 CCTV 재현 | `VirtualCCTV`의 위치(높이), 회전(내려다보는 각도), Field of View(세로 화각)를 실제 CCTV 설치 정보와 같게 맞춥니다. |
| 날씨·조도 | Directional Light 세기·각도, Fog, Skybox를 바꿔 가며 같은 씬을 여러 번 저장합니다. |

## 컴포넌트

| 스크립트 | 붙이는 곳 | 역할 |
| --- | --- | --- |
| `GroundTruthExporter` | 가상 CCTV 카메라 | 이미지·정답·카메라 정보·기준점 저장. 해상도, fps, 준비 시간, 저장 프레임 수 설정 |
| `CalibrationGrid` | 빈 오브젝트 | 노면 위 격자 기준점 생성. 오브젝트 위치·회전 기준으로 놓임 |
| `TrackedObject` | 정답을 낼 객체 | 클래스 이름, 정답 박스·바닥점 계산 |
| `RoadSurface` | 도로·인도 | 노면으로 인식할 Collider 표시 |
| `TrafficSpawner` | 차로 오브젝트 | 경로 시작점에서 차량 프리팹을 주기적으로 생성. 같은 차로는 같은 속도 |
| `WaypointMover` | (스포너가 자동으로 붙임) | 경로점을 따라 이동, 노면 높이에 맞춤 |

## 알아 둘 점

- 저장 중에는 `Time.captureDeltaTime`으로 프레임마다 시뮬레이션 시간이 정확히 1/fps씩 흐릅니다. 이미지 저장이 느려도 시간 간격은 일정하지만, 화면은 실제보다 느리게 보일 수 있습니다.
- 에디터에서는 Game 뷰가 닫혀 있으면 프레임이 저장되지 않습니다.
- 정답 박스는 가려진 부분까지 포함합니다(가림 여부는 아직 계산하지 않음).
- `TwinSightExport/`, `Library/` 등 Unity 생성 폴더는 `.gitignore`에 들어 있어 커밋되지 않습니다.
- 2026-10-18 Unity 6000.6.6f1에서 프로젝트 컴파일 및 도시·차량 실험 씬 생성, 차량 메시 보존·바퀴 회전, 짧은 이미지·정답 저장을 검증했습니다. 기본 `DemoRoad`의 전체 평가 실험 결과는 별도로 기록합니다.
