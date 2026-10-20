# TwinSight API

검출 결과와 경고를 백엔드에 넣고, 대시보드·지도·디지털 트윈이 조회하거나 WebSocket으로 받는 계약입니다. 기계가 읽을 스키마는 같은 폴더의 [openapi.json](openapi.json)입니다. 서버를 띄운 뒤 http://localhost:8000/docs 에서도 확인할 수 있습니다.

명령은 저장소 루트에서 실행합니다.

## 서버 실행

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

동작 확인은 `GET /health` 입니다. 스키마 파일을 다시 만들 때는 서버 없이 다음을 실행합니다.

```powershell
.\.venv\Scripts\python.exe backend\scripts\export_openapi.py
```

## 엔드포인트

| 메서드 | 경로 | 설명 | 누가 쓰는지 |
| --- | --- | --- | --- |
| GET | `/health` | 프로세스가 떠 있는지 | 모두 |
| GET | `/cameras` | 카메라 목록 | 대시보드, 지도 |
| POST | `/cameras` | 카메라 등록·수정 (같은 `camera_id`면 덮어씀) | 대시보드 |
| GET | `/cameras/{camera_id}` | 카메라 하나 | 대시보드, 지도, 트윈 |
| POST | `/cameras/import-its` | `candidates_its.json`을 카메라로 넣기 | 대시보드 |
| GET | `/cameras/{camera_id}/stream` | 재생 주소. ITS이고 받은 지 오래되면 갱신 | 대시보드, 트윈 |
| GET | `/cameras/{camera_id}/detections/latest` | 가장 최근 프레임과 상자 (`width`, `height` 포함) | 대시보드 |
| GET | `/detections` | 검출 상자 이력. 카메라·클래스·기간·페이지 | 대시보드 |
| GET | `/detections/stats` | 같은 필터의 클래스별·KST 1시간별 개수 | 대시보드 |
| POST | `/ingest/detections?run_id=` | 검출 프레임 하나 또는 배열 | 검출 모듈 |
| POST | `/ingest/alerts?run_id=` | 경고 하나 또는 배열 | 검출 모듈 |
| GET | `/alerts` | 경고 목록. 이벤트 시각이 최근인 것부터 | 대시보드 |
| PATCH | `/alerts/{id}` | 확인·기각. `{id}`는 서버 정수 | 대시보드 |
| WS | `/ws` | 검출·경고·상태 변경을 즉시 수신 | 대시보드, 지도, 트윈 |

`run_id`를 생략하면 `{camera_id}-default`가 됩니다. 프론트 개발 서버 `http://localhost:5173` 에서의 브라우저 호출은 CORS로 허용합니다.

`GET /cameras`의 각 항목에는 `lat`(위도), `lon`(경도)이 있습니다. ITS 목록을 가져오면 `candidates_its.json`의 좌표가 이 필드로 저장됩니다. 좌표가 없는 카메라는 `null`입니다.

## 검출 한 줄

`detections.jsonl`의 한 줄이자 `POST /ingest/detections` 본문입니다. 모르는 필드는 무시합니다. `mapped_xz`는 매핑을 거친 뒤에만 있고, 없어도 저장됩니다. 보정 좌표가 있으면 그 값을 우선 저장합니다.

```json
{
  "camera_id": "utic-1294",
  "frame": 12,
  "timestamp": 1760688000.4,
  "timestamp_kind": "unix_seconds",
  "width": 720,
  "height": 480,
  "inference_ms": 12.5,
  "detections": [
    {
      "class_name": "car",
      "class_id": 2,
      "category_id": 1,
      "model_id": "primary",
      "bbox_xyxy": [310.0, 340.5, 335.1, 385.0],
      "confidence": 0.87,
      "track_id": 15,
      "ground_point_px": [322.55, 385.0]
    }
  ],
  "image": "frames/000012.jpg",
  "alert_ids": ["utic-1294:1"]
}
```

`timestamp_kind`는 `simulation_seconds`, `video_seconds`, `unix_seconds`, `unspecified` 중 하나입니다. `category_id`는 검출 모듈 규약 그대로입니다 (person 0, car 1, truck 2, bus 3, motorcycle 4, bicycle 5, pothole 6, crack 7, debris 8, barrier 9).

## 검출 이력

`GET /detections?camera_id=&class_name=&from=&to=&limit=500&offset=0`

한 항목은 검출 상자 하나입니다. 프레임 필드는 검출 메시지와 같고, `run_id`를 함께 줍니다. `total`은 이번 페이지가 아니라 필터에 맞는 전체 개수입니다. 정렬은 `timestamp`가 큰 것부터입니다.

`class_name`은 반복할 수 있습니다. `from`과 `to`는 오프셋이 있는 ISO8601이고, Unix 초로 바꿔 `timestamp`와 비교합니다. `limit` 기본값은 500이고 최대 5000입니다.

```json
{
  "total": 1,
  "items": [
    {
      "camera_id": "utic-1294",
      "run_id": "utic-1294-default",
      "frame": 12,
      "timestamp": 1760688000.4,
      "timestamp_kind": "unix_seconds",
      "width": 720,
      "height": 480,
      "inference_ms": 12.5,
      "image": "frames/000012.jpg",
      "class_name": "car",
      "class_id": 2,
      "category_id": 1,
      "model_id": "primary",
      "bbox_xyxy": [310.0, 340.5, 335.1, 385.0],
      "confidence": 0.87,
      "track_id": 15,
      "ground_point_px": [322.55, 385.0],
      "mapped_xz": null
    }
  ]
}
```

`GET /detections/stats`는 같은 `camera_id`, `class_name`, `from`, `to`를 받습니다. `by_hour`는 `unix_seconds`만 KST 정시로 묶고, 시각은 `+09:00` 오프셋입니다.

```json
{
  "by_class": [{"class_name": "car", "count": 4}],
  "by_hour": [{"hour": "2026-10-19T15:00:00+09:00", "count": 4}]
}
```

## 경고 한 줄

`alerts.jsonl`의 한 줄이자 `POST /ingest/alerts` 본문입니다.

```json
{
  "alert_id": "fixed-pothole-warning:1",
  "camera_id": "fixed-pothole-warning",
  "frame": 2,
  "timestamp": 15.491779327392578,
  "type": "road_damage",
  "severity": "warning",
  "status": "unconfirmed",
  "message": "Persistent pothole detected on the road",
  "evidence": [
    {
      "class_name": "pothole",
      "track_id": 1,
      "model_id": "road",
      "bbox_xyxy": [516.065, 223.148, 554.186, 262.568],
      "confidence": 0.595433
    }
  ],
  "basis": "visual_detections_and_motion"
}
```

## 경고 조회 응답

`GET /alerts?camera_id=&run_id=&type=&status=&from_ts=&to_ts=&limit=100`

`id`는 서버가 붙인 정수입니다. `alert_id`와 다릅니다.

```json
[
  {
    "id": 1,
    "run_id": "20261018_120000_000000",
    "alert_id": "fixed-pothole-warning:1",
    "camera_id": "fixed-pothole-warning",
    "frame": 2,
    "timestamp": 15.491779327392578,
    "type": "road_damage",
    "severity": "warning",
    "status": "unconfirmed",
    "message": "Persistent pothole detected on the road",
    "evidence": [],
    "basis": "visual_detections_and_motion",
    "created_at": "2026-10-18T11:00:00+00:00",
    "updated_at": "2026-10-18T11:00:00+00:00",
    "handled_by": null
  }
]
```

상태 변경은 `PATCH /alerts/1`에 `{"status": "confirmed", "handled_by": "dashboard"}` 를 보냅니다. `status`는 `confirmed` 또는 `dismissed`입니다.

스트림 주소는 `GET /cameras/{camera_id}/stream` 입니다.

```json
{
  "camera_id": "its-abc",
  "stream_url": "https://...",
  "stream_fetched_at": "2026-10-18T20:00:00+09:00",
  "refreshed": true,
  "warning": null
}
```

ITS 카메라만 갱신합니다. 기본 유효 시간은 30분(`STREAM_TTL_MINUTES`)이고, 같은 카메라는 5분에 한 번만 ITS를 호출합니다. 갱신에 실패하면 저장돼 있던 주소를 `refreshed: false`와 `warning`으로 돌려줍니다. ITS 호출은 월 한도를 쓰므로 반복해서 시험하지 않습니다.

## WebSocket

주소는 `ws://localhost:8000/ws` 입니다. Swagger의 Try it out에는 나오지 않습니다. 오는 메시지는 세 가지입니다.

검출:

```json
{"type": "detections", "camera_id": "utic-1294", "run_id": "demo", "frame": {"camera_id": "utic-1294", "frame": 12, "detections": []}}
```

새 경고 (`id`는 서버 정수):

```json
{"type": "alert", "alert": {"id": 1, "run_id": "demo", "alert_id": "utic-1294:1", "camera_id": "utic-1294", "type": "road_damage", "status": "unconfirmed", "message": "..."}}
```

상태 변경:

```json
{"type": "alert_updated", "alert": {"id": 1, "status": "confirmed", "handled_by": "dashboard"}}
```

사람이 읽으려면 서버가 떠 있는 터미널과 따로:

```powershell
.\.venv\Scripts\python.exe backend\scripts\ws_watch.py
```

## 검출 모듈 연동

1. 검출을 빈 출력 폴더로 실행합니다. `--alerts`를 켜야 `alerts.jsonl`이 생깁니다. `--camera-id`는 카메라 목록의 `camera_id`와 맞춥니다.

```powershell
python -m detection predict --source <영상 또는 스트림> --camera-id <카메라ID> --alerts --out runs\detection\demo
```

2. 그 폴더를 백엔드가 따라 읽게 합니다. `run_id`를 생략하면 폴더 이름이 실행 ID가 됩니다.

```powershell
.\.venv\Scripts\python.exe backend\scripts\follow_detections.py --run-dir runs\detection\demo
```

이미 쌓인 줄을 건너뛰려면 `--no-from-start`를 붙입니다. 검출이 끝나 `summary.json`이 생기고 더 읽을 줄이 없으면 follow가 `실행 종료`를 찍고 멈춥니다.

같은 카메라로 다시 실행할 때는 `run_id`를 다르게 줘야 경고가 저장됩니다.
녹화 영상은 `--camera-id`를 카메라 목록의 ID로 맞춥니다.
녹화 영상은 재생 시 `--stamp-now`를 씁니다.

## 주의

- 경고의 고유 키는 `(run_id, alert_id)`입니다. `alert_id`는 `카메라ID:번호`이고 실행마다 1부터 다시 시작합니다.
- `PATCH /alerts/{id}`의 `id`는 조회 응답에 있는 서버 정수입니다. `alert_id` 문자열이 아닙니다.
- `track_id`는 그 실행(`run_id`) 안에서만 같은 물체를 가리킵니다.
