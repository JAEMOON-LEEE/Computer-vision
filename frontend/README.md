# TwinSight 관제 화면

Vite + React + TypeScript 대시보드입니다. 이전 정적 화면은 [frontend-proto](../frontend-proto/README.md)에 그대로 두었습니다.

박스는 오버레이 확인용 목업이며 실제 영상 속 물체와 위치가 맞지 않습니다. 이력 표는 `GET /detections`, 차트는 `GET /detections/stats`로 저장된 검출을 조회합니다.

## 실행

백엔드 주소는 저장소 루트 `.env`의 `VITE_API_BASE`입니다. 없으면 `http://localhost:8000`을 씁니다. 예시는 [frontend/.env.example](.env.example)에 있습니다.

지도 타일은 `.env`에 `VITE_CARTO_KEY`가 있으면 CARTO 밝은 지도(light_all), 없으면 OpenStreetMap 기본 지도를 씁니다. 키 없이도 지도는 뜹니다. CARTO 키는 https://www.carto.com/basemaps/apikey/ 에서 이메일로 무료 발급받고, 키는 커밋하지 않습니다.

저장소 루트에서 `dev.bat`을 더블클릭하면 백엔드, 이 화면, 목업 재생이 함께 뜹니다. 목업 없이 띄우려면 `dev.bat nomock`입니다.

직접 띄울 때는 저장소 루트에서 백엔드를 실행하고, `frontend`에서 `npm install` 후 `npm run dev`를 실행합니다. 주소는 http://localhost:5173 입니다. `127.0.0.1`로 열면 CORS에 막힙니다.

## 화면

- 관제: 지도의 카메라 마커와 선택 카메라 패널로 고릅니다. 패널의 영상 하나만 HLS를 요청하고, 검출 박스는 캔버스에 유지하다가 500ms 동안 새 검출이 없으면 지웁니다. 미확인 경고는 오른쪽 서랍과 위험 이벤트 표에서 확인·기각합니다.
- 분석: 위험도 히트맵, 반복 구간, 시간대·유형 통계입니다. 캘리브레이션이 없으면 예시 좌표를 씁니다.
- 이력: 카메라·클래스·기간으로 `GET /detections`를 거르고, 클래스별·KST 1시간별 개수는 `GET /detections/stats`로 그립니다. 시각은 KST입니다.

저장소 루트 `.env`의 `VITE_DEMO_TWIN=1`이면 위치·반복 구간처럼 아직 없는 값을 예시로 채웁니다. `0`이거나 없으면 그 자리는 "데이터 없음"입니다.
- 오른쪽 아래 지연 패널은 검출 시각부터 캔버스에 그린 시점까지를 모읍니다. `timestamp_kind`가 `unix_seconds`가 아니면 메시지 수신 시각을 기준으로 합니다. CSV 버튼은 브라우저 콘솔에 찍습니다.


## Supabase DB 관리

상단 **DB 관리** 메뉴에서 12개 테이블의 건수·레코드·JSON 상세를 확인합니다. ID 검색은 부분 일치이며 한 페이지는 25건입니다.
CCTV 등록/수정 후 관제 카메라 목록을 갱신합니다. 분석 실행의 지도 기준점을 등록하면 관제 화면에서 해당 실행의 상대 좌표를 지도 위치로 변환할 때 사용합니다.
경고 확인·기각은 DB에 저장하고 처리 이력을 남깁니다. 원시 검출 결과와 산출물 관계는 조회용입니다.

기본 API는 같은 출처의 `/api`입니다. `VITE_API_BASE`에는 DB 주소가 아닌 HTTP API 주소만 넣습니다. DB URL·DB 비밀번호·팀 접속 키를 `VITE_` 변수에 넣지 마세요.
운영 빌드 경로는 `/dashboard/`이며 FastAPI가 빌드 파일과 API를 함께 제공합니다. 실행/로그인 절차는 `backend/README.md`의 Supabase 항목을 따릅니다.
Vite 개발 서버는 기존 백엔드 포트 8000으로 `/api`, `/login`, `/logout`을 전달합니다.
