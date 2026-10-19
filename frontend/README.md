# TwinSight 관제 화면

Vite + React + TypeScript 대시보드입니다. 이전 정적 화면은 [frontend-proto](../frontend-proto/README.md)에 그대로 두었습니다.

박스는 오버레이 확인용 목업이며 실제 영상 속 물체와 위치가 맞지 않습니다. 이력 표는 `GET /detections`, 차트는 `GET /detections/stats`로 저장된 검출을 조회합니다.

## 실행

백엔드 주소는 저장소 루트 `.env`의 `VITE_API_BASE`입니다. 없으면 `http://localhost:8000`을 씁니다. 예시는 [frontend/.env.example](.env.example)에 있습니다.

저장소 루트에서 `dev.bat`을 더블클릭하면 백엔드, 이 화면, 목업 재생이 함께 뜹니다. 목업 없이 띄우려면 `dev.bat nomock`입니다.

직접 띄울 때는 저장소 루트에서 백엔드를 실행하고, `frontend`에서 `npm install` 후 `npm run dev`를 실행합니다. 주소는 http://localhost:5173 입니다. `127.0.0.1`로 열면 CORS에 막힙니다.

## 화면

- 관제: 지도의 카메라 마커와 하단 카드로 고릅니다. 펼친 카드 하나만 HLS를 요청하고, 검출 박스는 캔버스에 유지하다가 500ms 동안 새 검출이 없으면 지웁니다. 미확인 경고는 오른쪽 서랍에서 확인·기각합니다.
- 이력: 카메라·클래스·기간으로 `GET /detections`를 거르고, 클래스별·KST 1시간별 개수는 `GET /detections/stats`로 그립니다. 시각은 KST입니다.
- 오른쪽 아래 지연 패널은 검출 시각부터 캔버스에 그린 시점까지를 모읍니다. `timestamp_kind`가 `unix_seconds`가 아니면 메시지 수신 시각을 기준으로 합니다. CSV 버튼은 브라우저 콘솔에 찍습니다.
