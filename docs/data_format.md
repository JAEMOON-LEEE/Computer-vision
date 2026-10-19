# 가상환경·CCTV 공통 데이터 형식 (초안)

Unity 가상환경이 내보내는 정답 데이터와, 실제 CCTV 영상에서 나온 YOLO 검출 결과가 같은 형식을 쓰도록 정한 초안입니다. README의 "모듈 연동 시 정의할 항목" 중 영상 입력 → 분석, 검출 → 추적, 추적 → 공간 매핑 구간을 다룹니다. 팀에서 합의하면서 바꿔 나갑니다.

## 좌표 규칙

- **이미지 좌표**: 픽셀 단위, 왼쪽 위가 원점, `u`는 오른쪽, `v`는 아래로 증가합니다(OpenCV와 같음). 바운딩 박스는 `[x1, y1, x2, y2]`(왼쪽 위, 오른쪽 아래)입니다.
- **월드 좌표(가상환경)**: Unity 좌표, 미터 단위. `x` 오른쪽, `y` 위, `z` 앞. 노면 위치는 `(x, z)` 두 값으로 다룹니다.
- **월드 좌표(실제 CCTV)**: 노면 위치를 지역 평면 좌표(예: TM·UTM, 미터)로 두면 같은 매핑 코드를 그대로 쓸 수 있습니다.
- **시각**: `timestamp`는 초 단위 실수입니다. 가상환경은 시뮬레이션 시간, 실제 CCTV는 Unix 시간을 넣습니다.

## 폴더 구성

```
<export>/
  camera.json          카메라 정보 (한 번)
  control_points.json  노면 기준점: 월드 좌표 ↔ 픽셀 좌표 (한 번)
  ground_truth.jsonl   프레임별 정답 (가상환경만)
  detections.jsonl     프레임별 검출 결과 (YOLO, 실제·가상 공통)
  frames/000000.jpg …  렌더링 이미지
```

`.jsonl`은 한 줄에 JSON 객체 하나(프레임 하나)입니다.

## camera.json

| 필드 | 설명 |
| --- | --- |
| `camera_id` | 카메라 ID |
| `image_width`, `image_height` | 이미지 크기(px) |
| `vertical_fov_deg` | 세로 화각 |
| `capture_fps` | 저장 프레임률 |
| `fx`, `fy`, `cx`, `cy` | 내부 파라미터(px). 위 이미지 좌표 규칙 기준 |
| `position` | 카메라 위치 `[x, y, z]` |
| `rotation_euler_deg` | Unity 회전(도) |
| `forward` | 카메라가 보는 방향 단위 벡터 |
| `world_to_camera_cv` | 월드 → 카메라 좌표 3×4 행렬(행 우선 12개 값). 카메라 축은 OpenCV 기준(x 오른쪽, y 아래, z 앞) |

`world_to_camera_cv`와 `fx·fy·cx·cy`로 기준점을 다시 투영해서, 내보낸 픽셀 좌표와 맞는지 확인합니다(`mapping/scripts/evaluate_mapping.py`가 자동으로 확인). Unity 월드는 왼손 좌표계여서 이 행렬의 회전 부분 행렬식은 -1입니다.

## control_points.json

```json
{
  "camera_id": "virtual-cam-01",
  "points": [
    {"id": 0, "world": [-12.0, 0.0, 0.0], "pixel": [143.2, 1012.7], "in_frame": true}
  ]
}
```

노면 위 격자점입니다. 실제 CCTV에서 차선 끝점처럼 측량 좌표를 아는 점을 화면에서 찍는 작업을 대신합니다. 매핑 평가에서는 이 중 일부로 Homography를 구하고, 나머지로 오차를 잽니다.

## ground_truth.jsonl (가상환경 정답)

```json
{
  "camera_id": "virtual-cam-01", "frame": 12, "timestamp": 11.2,
  "image": "frames/000012.jpg", "width": 1920, "height": 1080,
  "objects": [
    {
      "track_id": 3, "class_name": "car",
      "bbox_xyxy": [812.4, 530.1, 905.8, 601.3], "truncated": false,
      "ground_point_world": [1.75, 0.0, 42.3],
      "ground_point_pixel": [858.9, 588.0], "ground_point_in_frame": true
    }
  ]
}
```

- `bbox_xyxy`: 객체 메시를 투영한 정답 박스입니다. 가려진 부분도 포함합니다.
- `truncated`: 박스가 화면 경계에서 잘렸는지 여부입니다.
- `ground_point_world`: 객체 바닥면 중심(차량이면 차체 아래 중심)의 노면 좌표입니다. 공간 매핑이 맞혀야 하는 값입니다.
- `ground_point_pixel`: 위 점이 화면에 찍히는 위치입니다. 화면 밖이면 `ground_point_in_frame`이 `false`입니다.

## detections.jsonl (검출 결과, 실제·가상 공통)

```json
{
  "camera_id": "utic-1294", "frame": 12, "timestamp": 1760688000.4,
  "width": 720, "height": 480,
  "detections": [
    {"class_name": "car", "class_id": 2, "bbox_xyxy": [310.0, 340.5, 335.1, 385.0], "confidence": 0.87, "track_id": 15,
     "ground_point_px": [322.55, 385.0], "mapped_xz": [3.42, 41.87], "mapped_xz_corrected": [3.61, 44.15]}
  ],
  "image": "frames/000012.jpg"
}
```

- `class_id`, `track_id`는 없으면 생략하거나 `null`로 둡니다. `track_id`는 ByteTrack이 붙인 객체 번호로, 같은 카메라·같은 실행 안에서만 유지됩니다.
- `ground_point_px`(선택): 노면 좌표로 바꾼 픽셀(박스 아래 가운데).
- `mapped_xz`(선택): 캘리브레이션으로 바꾼 노면 좌표(박스 아래 가운데 그대로). 단위는 같은 폴더 `session.json`의 `mapped_units`(`m`이면 미터)를 따릅니다.
- `mapped_xz_corrected`(선택): 박스 아래 가운데의 카메라 쪽 편향을 보정한 노면 좌표(`mapping/twinsight_mapping/correction.py`). 미터 단위 캘리브레이션일 때만 있고, 위치를 쓸 때는 이 값을 우선합니다. 보정 설정은 `session.json`의 `ground_correction`에 있습니다.
- `class_voted`(선택): 같은 추적 ID에서 지난 프레임까지 받은 클래스의 신뢰도 가중 다수결입니다. 편향 보정에는 이 클래스를 씁니다.

## 실시간 서버 (CCTV --serve)

CCTV 파이프라인을 `--serve 8765`로 실행하면 Unity 디지털 트윈(`CctvLiveClient`)이 읽어 가는 HTTP 서버가 열립니다(기본 `127.0.0.1`).

- `GET /frame.jpg`: 최신 원본 프레임(JPEG)
- `GET /state`: 최신 검출 결과

```json
{
  "camera_id": "utic-당진청주선아산", "camera_name": "[당진청주선]아산", "units": "m",
  "timestamp": 1792378186.07, "frame": 531, "width": 720, "height": 480,
  "objects": [{"id": 15, "class_name": "car", "x": 3.61, "z": 44.15, "confidence": 0.87, "bbox": [310.0, 340.5, 335.1, 385.0]}],
  "unplaced": 0
}
```

- `objects`에는 노면 좌표가 있는 검출만 들어갑니다. 좌표는 `mapped_xz_corrected`가 있으면 그 값, 없으면 `mapped_xz`이고, 클래스는 다수결 클래스(`class_voted`)입니다. `unplaced`는 좌표가 없는 검출 수입니다.
- `id`는 추적 ID이고, 추적 ID가 없으면 음수 임시 번호입니다.
- `units`가 `px`이면 예전 픽셀 단위 캘리브레이션이라 실제 거리가 아닙니다.

## correction.json (편향 보정 유효 길이)

`mapping/scripts/calibrate_correction.py`가 가상환경 정답으로 만들고, `evaluate_mapping.py --dims-file`과 CCTV 파이프라인(`--correction`, 기본 `calibration/correction.json`)이 읽습니다.

```json
{
  "source": "detection",
  "camera": {"position": [8.5, 8.0, -10.0], "image_size": [1920, 1080]},
  "dimensions": {"car": [2.12, 1.85], "bus": [6.44, 2.5], "truck": [2.52, 2.5], "motorcycle": [2.1, 0.8]},
  "fitted": {"car": {"length": 2.12, "width": 1.85, "n": 305, "iqr": 0.77}},
  "heldout": {"보정 없음": {"mean": 1.70}, "학습 길이 · 다수결 클래스": {"mean": 0.56}}
}
```

- `dimensions`의 길이는 차체 길이가 아니라 박스 아래 가장자리를 만드는 **유효 길이**입니다. 학습 표본이 부족한 클래스는 기본값(차체 길이)이 들어갑니다.
- 학습한 가상 카메라와 높이·각도가 비슷한 CCTV에 씁니다.
- `image`(선택): 원본 프레임을 함께 저장한 경우 그 경로.
- `detection` 모듈의 추가 필드(초안): `category_id`는 프로젝트 분류 ID, `model_id`는 결과를 낸 모델 식별자입니다. `class_id`는 각 모델의 원래 ID라 두 모델을 함께 쓰면 `model_id`와 같이 해석합니다. 분류표는 [검출 모듈 안내](../detection/README.md)를 따릅니다.
- `detection` 모듈은 프레임에 `timestamp_kind`와 `inference_ms`를 추가합니다. 기본 `track_id`는 `null`이며 `--track`/`--alerts`에서는 기존 ByteTrack ID를 저장합니다. Unity 입력은 `simulation_seconds`, 녹화 영상은 `video_seconds`, 웹캠·스트림 수신 시각은 `unix_seconds`입니다.
- 신호·사고 실험의 Unity 정답에는 `signals`(차량·보행자 상태, 남은 시간), `scenario`(시드·선택 장면·샘플링 비율·물리 접촉 이벤트)가 추가됩니다. 이는 정답 전용이며 경고 엔진의 입력 근거로 사용하지 않습니다. 자세한 내용은 [실험 안내](traffic_incidents.md)를 참고합니다.
- `alerts.jsonl`은 검출·추적에서 판단한 경고를 한 줄씩 기록합니다. `alert_id`, `type`, `status=unconfirmed`, `camera_id`, `frame`, `timestamp`, `evidence`(근거 박스·클래스·추적 ID)를 포함합니다.
- 실제 CCTV 파이프라인(`CCTV` 스크립트)은 `logs/<카메라ID>_<시각>/detections.jsonl`에 이 형식으로 저장합니다. `session.json`에는 모델, 신뢰도 기준, 추적기, 캘리브레이션 파일, `timestamp_kind`(`unix_seconds` 또는 녹화 영상의 `video_seconds`)가 들어 있습니다.

## calibration/<카메라ID>.pose.json (CCTV 카메라 자세, 가상 CCTV 배치값)

`calibrate_homography.py`(기준점 6개 이상)나 `estimate_camera_pose.py --calibration`이 만듭니다.

```json
{
  "camera_id": "utic-아산향산사거리",
  "position_m": {"x_east": 8.5, "z_north": -10.0, "height": 8.0},
  "position_latlon": [36.7798099, 127.0029952],
  "origin_latlon": [36.7799, 127.0029],
  "heading_deg": 352.0, "pitch_deg": 15.0, "roll_deg": 0.0,
  "vertical_fov_deg": 45.0, "horizontal_fov_deg": 72.7, "focal_px": 1303.7, "image_size": [1920, 1080],
  "unity": {"position": [8.5, 8.0, -10.0], "euler_deg": [15.0, 352.0, 0.0], "field_of_view": 45.0, "meters_per_unit": 1.0, "ground_y": 0.0},
  "points": 12, "rmse_px": 0.0,
  "leave_one_out_std": {"height": 0.0, "heading_deg": 0.0, "pitch_deg": 0.0, "vertical_fov_deg": 0.0}
}
```

- `position_m`: 원점(`origin_latlon`, 위도·경도 모드가 아니면 입력 좌표계 원점) 기준 동(x)·북(z)·노면에서 잰 높이(m).
- `heading_deg`: 북(+z)에서 동(+x) 쪽으로 잰 카메라 방향. `pitch_deg`: 아래로 숙인 각도(양수). `roll_deg`: 좌우 기울기.
- `unity`: Unity 카메라의 `transform.position`, `transform.eulerAngles`, `fieldOfView`(세로 화각)에 그대로 넣는 값. Unity x=동, y=위, z=북이고, `meters_per_unit`이 1이 아니면 position을 그 값으로 나눈 값입니다. `ground_y`는 가상 CCTV를 놓을 장면의 노면 높이(Unity y, `--ground-y`)이며 position의 y에 더해져 있습니다.
- `leave_one_out_std`: 기준점을 하나씩 빼고 다시 구했을 때의 표준편차. 크면 기준점을 더 찍어야 합니다.
- 가정: 렌즈 중심은 화면 가운데, 정사각 픽셀, 렌즈 왜곡 없음, 기준점은 같은 노면 위.

## calibration/<카메라ID>.json (실제 CCTV 캘리브레이션)

`mapping/scripts/calibrate_homography.py`가 만들고, CCTV 파이프라인이 읽습니다.

```json
{
  "camera_id": "utic-1294",
  "image": "C:/.../captures/utic-1294_20261017_221500.png",
  "image_size": [720, 480],
  "units": "m",
  "coordinate_system": "local_enu: x=동쪽(m), z=북쪽(m), origin_latlon 기준",
  "origin_latlon": [36.78, 127.0],
  "road_heading_deg": 35.0,
  "homography_pixel_to_ground": [[...], [...], [...]],
  "fit_rmse_m": 0.08,
  "points": [
    {"id": 1, "pixel": [277.0, 108.0], "world_xz": [0.0, 0.0], "residual_m": 0.05, "loo_error_m": 0.11, "latlon": [36.78, 127.0]}
  ],
  "created_at": "2026-10-17T22:15:00"
}
```

- `homography_pixel_to_ground`: 픽셀 `[u, v, 1]`에 곱하면 `[x, z, w]`가 되고, `(x/w, z/w)`가 노면 좌표입니다. `w <= 0`이면 지평선 너머라 노면에 닿지 않습니다.
- `loo_error_m`: 그 점을 빼고 구한 Homography로 그 점을 맞혔을 때의 오차입니다. 다른 점보다 유난히 크면 잘못 찍었거나 좌표를 잘못 입력한 점입니다.
- `road_heading_deg`(선택): 도로(차로) 방향. +z(위도·경도 모드면 북쪽)에서 +x(동쪽) 쪽으로 잰 각도입니다. 편향 보정에서 차량 진행 방향을 아직 모를 때 씁니다.
- 위도·경도로 입력하지 않았으면 `origin_latlon`은 `null`이고 `coordinate_system`은 입력한 좌표계(`user`)입니다.
- 회전형(PTZ) CCTV는 화면이 바뀌면 이 행렬이 맞지 않으므로 다시 캘리브레이션합니다.
