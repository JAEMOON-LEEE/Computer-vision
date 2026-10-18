# TwinSight 백엔드

CCTV 검출 결과(`detections.jsonl`)와 경고(`alerts.jsonl`)를 받아 저장하고, REST와 WebSocket으로 관제 화면에 전달합니다.

데이터베이스는 임시 SQLite입니다. 정식 DB로 바꿀 때는 저장소 루트 `.env`의 `DATABASE_URL`만 바꾸면 됩니다. 기본 파일은 `backend/data/twinsight.db`이며, 이 폴더와 `.env`는 git에 올리지 않습니다.

명령은 저장소 루트에서 실행합니다. PowerShell 실행 정책 때문에 `activate`가 막힐 수 있어, 가상환경의 파이썬을 직접 부릅니다.

## 설치

```powershell
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```

## 실행

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

브라우저에서 http://localhost:8000/docs 를 열면 REST 요청 형식과 응답을 확인할 수 있습니다. 실시간 이벤트는 WebSocket `ws://localhost:8000/ws` 로 받습니다. 이 경로는 HTTP가 아니라서 Swagger의 Try it out 목록에는 없습니다. 프론트 개발 서버(http://localhost:5173)에서의 호출은 CORS로 허용합니다. 프로세스 확인은 `GET /health` 입니다.

## 카메라 가져오기

ITS 교차로 후보는 `backend/data/its/candidates_its.json`에 있어야 합니다. 파일이 없으면 먼저 목록을 받습니다.

```powershell
.\.venv\Scripts\python.exe backend\scripts\fetch_its_cctv.py
```

서버를 띄운 뒤 `/docs`에서 `POST /cameras/import-its`를 실행합니다. 파일이 없으면 404와 함께 `fetch_its_cctv.py를 먼저 실행하세요`가 돌아옵니다.

`stream_url`은 서명 주소라 만료됩니다. 받은 시각을 `stream_fetched_at`에 같이 저장합니다. 후보의 `road_type`은 임시 스키마에 없어 저장하지 않습니다.

카메라는 `POST /cameras`로 직접 넣거나 고칠 수 있습니다. 같은 `camera_id`면 덮어씁니다.

## 목업 재생

검출·경고 JSONL을 기록된 시간 간격으로 API에 넣습니다. `--run-id`를 생략하면 입력 파일이 있는 폴더 이름을 실행 ID로 씁니다. `--loop`이면 반복마다 그 이름 뒤에 `-1`, `-2`를 붙여, 같은 경고 번호가 중복으로 버려지지 않게 합니다.

```powershell
.\.venv\Scripts\python.exe backend\scripts\replay_jsonl.py --alerts docs\validation\pothole-alert.jsonl --speed 5
```

검출 파일과 경고 파일을 함께 줄 수도 있습니다.

```powershell
.\.venv\Scripts\python.exe backend\scripts\replay_jsonl.py --detections out\demo\detections.jsonl --alerts out\demo\alerts.jsonl --speed 2
```

오버레이 동작 확인용 목업은 화면을 가로지르는 차량·보행자와 제자리 포트홀을 만듭니다. 박스 위치는 실제 영상 속 물체와 맞지 않습니다.

```powershell
.\.venv\Scripts\python.exe backend\scripts\make_mock_detections.py
.\.venv\Scripts\python.exe backend\scripts\replay_jsonl.py --detections backend\data\mock\its-cc4277cc18\detections.jsonl --alerts backend\data\mock\its-cc4277cc18\alerts.jsonl --speed 1 --loop
```

관제 화면에서 이 재생을 보는 방법은 [frontend/README.md](../frontend/README.md)에 있습니다.

## 검출 결과 실시간 연결

검출이 `runs/detection/<실행시각>/`에 쓰는 jsonl을 끝나는 줄부터 API로 넘깁니다. `alerts.jsonl`이 아직 없어도 생길 때까지 기다리고, `summary.json`이 생긴 뒤 더 읽을 줄이 없으면 `실행 종료`를 찍고 멈춥니다. `--run-id`를 생략하면 폴더 이름을 실행 ID로 씁니다.

```powershell
.\.venv\Scripts\python.exe backend\scripts\follow_detections.py --run-dir runs\detection\20261018_120000
```

이미 쌓인 줄을 건너뛰려면 `--no-from-start`를 붙입니다. 서버 연결이 3회 실패하면 그 줄은 `backend/data/failed_<run_id>.jsonl`에 남고 다음 줄로 진행합니다.

WebSocket으로 들어오는 이벤트를 보려면 서버와 다른 터미널에서:

```powershell
.\.venv\Scripts\python.exe backend\scripts\ws_watch.py
```

`--raw`면 JSON 원문입니다. 연결이 끊기면 3초 후 다시 붙습니다.

## 스트림 주소

`GET /cameras/{camera_id}/stream`이 재생 주소를 줍니다. ITS가 아닌 카메라는 저장된 주소를 그대로 돌려주고, 없으면 404입니다. ITS는 `stream_fetched_at`이 없거나 `STREAM_TTL_MINUTES`(기본 30분)가 지났으면 다시 받아 저장합니다. 갱신에 실패하면 기존 주소와 `warning`을 돌려줍니다. 같은 카메라는 5분에 한 번만 ITS를 호출합니다. 이 호출은 월 한도를 사용합니다.

## API 명세

팀원용 설명과 예시는 [docs/api/README.md](../docs/api/README.md), 스키마 파일은 [docs/api/openapi.json](../docs/api/openapi.json)입니다. 스키마를 다시 쓰려면:

```powershell
.\.venv\Scripts\python.exe backend\scripts\export_openapi.py
```

## 경고 확인

`/docs`에서 `GET /alerts`를 호출합니다. 응답의 `id`는 서버가 붙인 정수이고, `alert_id`는 검출 모듈이 준 문자열입니다. `alert_id`는 실행마다 1부터 다시 시작하므로 `run_id`와 함께 봐야 합니다.

상태 변경은 `PATCH /alerts/{id}`에 `status`(`confirmed` 또는 `dismissed`)와 `handled_by`를 보냅니다. 실시간 수신은 `WS /ws`입니다.

가장 최근 검출 상자는 `GET /cameras/{camera_id}/detections/latest`입니다. 여기서의 최근은 서버가 받은 시각(`received_at`) 기준입니다. `mapped_xz`에는 보정 좌표(`mapped_xz_corrected`)가 있으면 그 값을, 없으면 보정 전 값을 넣습니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest backend\tests -v
```

테스트는 호출할 때마다 임시 SQLite 파일을 만들므로 `backend/data/twinsight.db`를 건드리지 않습니다.

## 이상민과 맞출 것

`backend/app/models.py` 상단의 임시 스키마입니다. 테이블을 앱 시작 시 `create_all`로 만듭니다. 컬럼을 바꾸면 기존 `twinsight.db`는 자동으로 마이그레이션되지 않으니 파일을 지우거나, 정식 DB에서는 마이그레이션 도구로 바꿀지 정해야 합니다.

- `Run`이 필요한지. `track_id`와 `alert_id` 번호는 실행 안에서만 유효하고, 경고 고유 키는 `(run_id, alert_id)`입니다.
- 프레임에 카메라 ID를 중복 저장할지. 지금은 실행을 통해 카메라에 연결합니다.
- `mapped_xz`와 `mapped_xz_corrected`를 한 쌍만 저장하는 현재 방식(보정값 우선)을 유지할지.
- 위경도 변환, ITS `road_type`, 경고 상태 되돌리기, 검출 이력 보관 기간. 스트림 주소는 일단 `STREAM_TTL_MINUTES`(기본 30분)로 다시 받습니다.

## 한 번에 실행

저장소 루트의 [dev.bat](../dev.bat)을 더블클릭하면 백엔드, 관제 화면, 목업 재생 창이 각각 뜹니다. 목업 없이 띄우려면 `dev.bat nomock`를 실행합니다. ITS 키는 저장소 루트 `.env`의 `ITS_API_KEY`에 넣습니다.
