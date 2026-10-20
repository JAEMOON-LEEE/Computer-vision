# TwinSight 백엔드

CCTV 검출 결과(`detections.jsonl`)와 경고(`alerts.jsonl`)를 받아 저장하고, REST와 WebSocket으로 관제 화면에 전달합니다.

기본 데이터베이스는 PostgreSQL 17.11입니다. 루트 `.env`의 `POSTGRES_*`로 연결하며, [설치·실행·SQLite 이관 안내](../docs/postgresql.md)를 먼저 확인하세요. SQLite는 명시적 URL과 임시 테스트용으로 유지합니다.

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

## 지도·DB 구현 (이상민)

전체 프로젝트 산출물 관리도 추가했습니다. CCTV 정보 수집부터 좌표·가상환경·데이터셋·학습 모델·평가 결과를 `/catalog`에서 연결하고 파일 해시와 로그를 보존합니다. 팀별 등록 절차, ITS 키 위치, 프론트엔드 연동 API는 [프로젝트 데이터 관리](../docs/project_data.md)에 있습니다.

실행별 이력 조회·좌표 원본 보존·경고 처리 감사 이력·지도 기준 등록을 추가했습니다. API·스키마 관계·검증과 실제 CCTV 연동 조건은 [지도·DB 안내](../docs/map_database.md)를 참고하세요.

- `Run`은 유지합니다. 카메라 또는 시간 기준이 다른 입력은 HTTP 409로 거절하고 요청 전체를 롤백합니다.
- 기존 검출 응답의 `mapped_xz`는 보정 우선 규약을 유지합니다. 새 `detection_coordinates` 테이블에는 입력 두 쌍을 따로 보존합니다.
- 기존 DB에는 새 테이블 3개와 조회 인덱스 2개를 추가합니다. 기존 행·컬럼은 삭제하지 않습니다. 적용 전 서버를 멈추고 DB 백업을 보관하세요. 기존 좌표의 원본은 복원할 수 없습니다.
- 위경도는 실행별로 등록한 미터 단위 지역 ENU 기준만 사용합니다. ITS 카메라 좌표를 객체 원점으로 자동 대입하지 않습니다.
- `road_type`, 보관 기간 자동 삭제, 운영 DB 이관, 상태를 `unconfirmed`로 되돌리는 정책은 아직 추가하지 않았습니다.

## 한 번에 실행

저장소 루트의 [dev.bat](../dev.bat)을 더블클릭하면 백엔드, 관제 화면, 목업 재생 창이 각각 뜹니다. 목업 없이 띄우려면 `dev.bat nomock`를 실행합니다. ITS 키는 저장소 루트 `.env`의 `ITS_API_KEY`에 넣습니다.
