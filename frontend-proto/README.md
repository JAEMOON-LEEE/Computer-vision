# TwinSight 관제 화면

현재는 정적 HTML 시제품이며, frontend/ 의 React 대시보드로 전환했고, 이 폴더는 보존용입니다. 박스는 오버레이 확인용 목업이며 실제 영상 속 물체와 위치가 맞지 않습니다.

CCTV 영상을 재생하고, 백엔드 WebSocket으로 받은 검출 상자를 영상 위에 겹쳐 보여 줍니다. 경고는 오른쪽에서 확인·기각할 수 있습니다.

페이지 주소의 출발지는 `http://localhost:5173` 이어야 합니다. 백엔드 CORS가 이 주소만 허용합니다. `file://` 이나 `127.0.0.1`로 열면 목록과 영상이 막힙니다.

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
