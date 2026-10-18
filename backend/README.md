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
- 위경도 변환, ITS `road_type`, 스트림 갱신 주기, 경고 상태 되돌리기, 검출 이력 보관 기간.
