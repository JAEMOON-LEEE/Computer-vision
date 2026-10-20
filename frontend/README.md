# TwinSight 관제 화면

현재는 정적 HTML 시제품이며 Vite + React + TypeScript 대시보드로 전환할 예정입니다. 박스는 오버레이 확인용 목업이며 실제 영상 속 물체와 위치가 맞지 않습니다.

CCTV 영상을 재생하고, 백엔드 WebSocket으로 받은 검출 상자를 영상 위에 겹쳐 보여 줍니다. 경고는 오른쪽에서 확인·기각할 수 있습니다.

영상 아래 지도·이력 패널은 CCTV 설치 위치, 실행별 이동 경로, 경고 근거 위치를 구분합니다. 실행을 선택해 과거 기록을 볼 수 있고 WebSocket 수신 시 최대 초당 한 번 갱신합니다. Leaflet 1.9.4와 OpenStreetMap 타일은 인터넷 연결이 필요합니다. CDN이 막혀도 지역 좌표 SVG와 이력은 조회할 수 있습니다.

ITS·영상·검출 모델 없이 시연하려면 백엔드를 실행한 뒤 아래 명령을 실행하고 `지도 시연 (합성 데이터)` 카메라를 선택하세요.

```powershell
.\.venv\Scripts\python.exe backend\scripts\seed_map_demo.py
```

합성 데이터는 실제 위험이나 측량 결과가 아닙니다. 지도 기준을 등록하지 않은 실행은 지역 좌표만 표시합니다. 경고 기각 시 지도에서 숨겨지고 `기각 경고 포함`으로 다시 볼 수 있습니다. 계약과 제약은 [지도·DB 안내](../docs/map_database.md)에 있습니다.

공용 서버에서는 `/dashboard/`를 열면 API·지도·WebSocket이 같은 서버에 연결됩니다. 별도 개발 서버(5173 포트)는 같은 호스트의 8000 포트를 사용하며 `localhost`와 `127.0.0.1`을 허용합니다. 다른 출처는 백엔드 `CORS_ORIGINS`에 명시하세요. `file://`로 열지 마세요.

## 실행

저장소 루트에서 정적 서버를 띄웁니다. 이미 5173 포트에서 저장소 루트를 보고 있다면 다시 띄우지 않아도 됩니다.

```powershell
.\.venv\Scripts\python.exe -m http.server 5173
```

다른 터미널에서 백엔드를 띄웁니다.

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

브라우저에서 http://localhost:5173/frontend/ 를 엽니다.

## 확인 순서

1. 위처럼 백엔드와 이 페이지를 연다. 왼쪽에서 카메라를 고르거나 `재생`을 누른다. 이 동작이 ITS 카메라면 스트림 주소 갱신으로 호출 한도를 쓸 수 있다.
2. 실시간 연결이 `실시간 연결됨`으로 바뀌는지 본다.
3. 오버레이 동작 확인용 목업을 만들어 재생하고, 영상 위에 박스가 움직이는지 본다. 이 박스는 실제 영상 속 물체와 위치가 맞지 않는다.

```powershell
.\.venv\Scripts\python.exe backend\scripts\make_mock_detections.py
.\.venv\Scripts\python.exe backend\scripts\replay_jsonl.py --detections backend\data\mock\its-cc4277cc18\detections.jsonl --alerts backend\data\mock\its-cc4277cc18\alerts.jsonl --speed 1 --loop
```

대시보드에서 카메라 `its-cc4277cc18`을 선택한 상태여야 박스가 그 영상 위에 그려진다. `--loop`는 반복마다 실행 ID를 바꿔 같은 경고가 중복으로 버려지지 않게 한다.
