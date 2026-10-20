# 이상민 담당: 지도 시각화·데이터베이스

2026-10-19 구현. README 역할표의 위험 위치·이동 경로 표시와 CCTV·객체·위험 이력 저장 범위입니다. 기존 백엔드·프론트엔드에 연동 기능을 추가하며 검출·추적·Homography 알고리즘은 재사용합니다.

## 저장 구조와 호환성

```mermaid
erDiagram
    cameras ||--o{ runs : contains
    runs ||--o{ frames : contains
    frames ||--o{ detections : contains
    detections ||--o| detection_coordinates : preserves
    runs ||--o| map_references : locates
    runs ||--o{ alerts : contains
    alerts ||--o{ alert_history : records
```

- 한 `run_id`는 한 카메라·한 시간 기준에 고정됩니다. 충돌하는 입력은 409이며 배열 요청은 전부 롤백합니다. 카메라마다 별도 run_id를 사용하세요. 실행 번호를 재사용하면 기존 `(run_id, frame_no)`가 교체되므로 새 수집에는 새 ID가 필요합니다.
- 경로 식별자는 `(run_id, model_id, track_id)`입니다. null track_id는 개별 점으로 표시하며 연결하지 않습니다. 시각이 역행하거나 관측 사이가 2초를 초과하면 화면의 선을 끊습니다. 이는 표시 규칙이며 추적 알고리즘의 재식별을 보장하지 않습니다.
- 기존 `detections.mapped_x/z`와 최신 프레임 API는 보정 우선 규약을 유지합니다. `detection_coordinates`는 원본/보정 두 쌍을 저장합니다. 프레임 교체 시 외래 키 CASCADE로 이전 좌표 부속 행도 제거합니다.
- 기존 DB의 원본 좌표는 이미 손실되었으므로 이력 API의 `coordinate_provenance=legacy_preferred_only`로 구분합니다. 신규 수집은 `preserved`입니다.
- `alert_history`는 상태·처리자 변경 전후와 변경 시각을 같은 트랜잭션에 남깁니다. 동일 값 재요청과 빈 PATCH는 감사 이력을 중복 생성하지 않습니다. 감사 이력은 변경부터 기록하며, 과거 처리 이력은 소급 생성하지 않습니다.
- 앱 시작 시 새 테이블 3개와 `ix_map_runs_camera_started`, `ix_map_alerts_run_timestamp` 인덱스를 멱등적으로 추가합니다. 기존 테이블의 컬럼 변경·삭제는 없습니다. 기존 SQLite에 새 테이블이 없는 상황에서 데이터를 보존하는 업그레이드 테스트를 포함합니다.
- 적용 전 앱을 멈추고 DB 파일을 백업하세요. PostgreSQL/MySQL 드라이버·이관·동시성 부하·장기 보관 정책은 운영 검증하지 않았습니다. 데이터를 자동 삭제하지 않습니다.

## API

| 메서드 | 경로 | 용도 |
| --- | --- | --- |
| GET | `/runs?camera_id=&offset=0&limit=100` | 실행 목록, `items`와 `next_offset` |
| GET | `/runs/{run_id}/frames?after_frame=-1&limit=100` | 프레임 번호 오름차순 이력, `items`와 `next_after_frame` |
| PUT | `/runs/{run_id}/map-reference` | 존재하는 실행의 ENU 기준 등록 |
| GET | `/runs/{run_id}/map?frame_limit=200&alert_limit=100` | 경로·추적 없는 점·경고·위치 근거 |
| GET | `/alerts/{id}/history?after_id=0&limit=100` | 상태/처리자 변경 이력, `items`와 `next_after_id` |

모든 limit은 1~1000입니다. 커서가 null이면 마지막 페이지입니다. 실행 목록 offset은 새 실행이 생기면 이동할 수 있으므로 소비자가 run_id로 중복을 제거해야 합니다. 프레임 조회는 수집 중 스냅샷이 아니며 뒤늦게 들어온 낮은 번호 프레임은 다시 조회해야 합니다.

지도 API는 최신 프레임 번호 N개와 최신 이벤트 시각 경고 M개를 각각 제한합니다. `frames_truncated`/`alerts_truncated`로 제한 여부를 표시합니다. 전체 검출 다운로드는 프레임 이력 API를 이용합니다. 경고는 기존 `/alerts`의 run_id/시각 필터로 조회하며 지도용 제한과 별개입니다. 경고의 동일 프레임 검출은 표시 범위 밖이어도 별도 조회합니다.

`tracks[].points`에는 `frame`, `timestamp`, `xz`, `latlon`이 있습니다. `risks[]`에는 기존 `alert`, `locations`, `location_basis`가 있습니다. 같은 실행·프레임·모델·추적 ID(클래스가 주어지면 클래스도 일치)가 유일하게 매칭될 때만 위치를 제공합니다. 누락/모호한 근거는 `unlocated`, 위치 배열은 비웁니다. 현재 객체 위치나 CCTV 설치 위치로 대체하지 않습니다. 프레임을 재수신해 교체하면 경고의 위치 연결도 교체된 프레임을 따릅니다.

## 실제 CCTV 좌표 연결

`mapping/twinsight_mapping/calibration.py`의 `latlon_to_local_xz`와 같은 WGS84 곡률 반경을 이용한 역변환입니다. **x=동쪽(m), z=북쪽(m)**이어야 합니다. 원점 반경 5km를 넘는 좌표는 근거리 근사 범위 밖으로 보고 latlon을 반환하지 않습니다.

1. 실제 검출 결과를 새 run_id로 수집합니다.
2. 해당 수집에 실제로 적용된 calibration JSON의 camera_id, `units=m`, `coordinate_system=local_enu...`, `origin_latlon=[위도, 경도]`를 확인합니다.
3. 확인한 값을 아래처럼 등록합니다. 원점 예시는 합성 시연용이며 실제 CCTV에 복사하면 안 됩니다.

```http
PUT /runs/<run_id>/map-reference
Content-Type: application/json

{"coordinate_system":"local_enu","units":"m","origin_lat":37.5665,"origin_lon":126.9780}
```

등록은 같은 값으로 재요청할 수 있습니다. 다른 원점으로 변경은 409입니다. 카메라/PTZ/캘리브레이션이 바뀌면 새 실행으로 수집하세요. API는 숫자 범위와 선언된 좌표계를 검사하지만 실제 측량 검증을 대신하지 않습니다. Unity, user, TM/UTM 좌표를 ENU라고 등록하지 마세요. 기준 미등록일 때 지역 좌표 SVG를 제공하고 단위는 미등록이라고 표시합니다.

## 시연 및 검증

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
# 별도 터미널
.\.venv\Scripts\python.exe -m http.server 5173
# 별도 터미널
.\.venv\Scripts\python.exe backend\scripts\seed_map_demo.py
.\.venv\Scripts\python.exe -m pytest backend\tests -q
node --check frontend/map.js
node --check frontend/app.js
```

`http://localhost:5173/frontend/`에서 `지도 시연 (합성 데이터)`를 선택합니다. 합성 30프레임, 차량/포트홀 경로 2개, 포트홀 경고 1개가 표시됩니다. 실제 ITS 호출이나 영상 모델은 사용하지 않습니다. 실행할 때마다 새로운 시연 run_id를 만듭니다.

1차 검토: 실행 범위·좌표 보존·이력 조회·지도 표시 구현 및 API 회귀 테스트.

2차 검토: 혼합 카메라 요청 롤백, 시간 기준 충돌, 모델별 ID 중복, 미추적 객체, 늦게 도착한 경고 근거, 이전 DB 업그레이드, 비동기 카메라 전환, 기각 필터, 좁은 화면 스크롤을 확인했습니다. 위치 매칭은 단일 프레임의 근거 위치이며 사고 지점 확정 알고리즘은 아닙니다.

기술 참고: [Leaflet 공식 시작 안내](https://leafletjs.com/examples/quick-start/). 배경 지도와 라이브러리 CDN은 네트워크가 필요합니다. Leaflet 로드 실패 시에도 지역 좌표/이력 화면은 유지합니다. OpenStreetMap 출처는 지도에 표시합니다.

실제 CCTV 측량 기준과 실제 mapped_xz 입력은 저장소에 준비되어 있지 않아 현장 위치 정확도 검증은 남아 있습니다. 이번 검증은 합성 자료·API·브라우저 동작 검증입니다. Unity/LFS 모델 에셋은 지도·DB 변경 대상에 포함하지 않았습니다.

최종 결과: 백엔드 테스트 **35개 통과**, JavaScript 파일 2개 문법 검사 통과. 브라우저에서 30프레임·경로 2개 표시, 경고 기각/기각 포함 필터와 WebSocket 재접속을 확인했습니다. 테스트 도구가 httpx 관련 deprecation warning 1개를 출력했지만 실패는 없었습니다.

[파일 점검 목록](validation/map-database-file-scan.json)은 해당 시점 프로젝트 파일 1,011개를 기록합니다. 텍스트 189개는 전체 텍스트를 자동 스캔하고 Python은 구문 분석했으며, 담당 영역과 연동 코드는 내용 검토를 수행했습니다. 모델·이미지 등 에셋 822개는 메타데이터 목록 점검이며 모든 바이너리를 의미적으로 검토했다는 뜻이 아닙니다. Git/LFS 복제가 병행 중이어서 에셋 목록은 변할 수 있습니다.

![합성 시연: 지도와 지역 좌표 경로](images/map-history-demo.png)

초기 지도 검증은 `DATABASE_URL=sqlite:///backend/data/map-review.db`로 실행했습니다. 현재 기본 서버는 PostgreSQL로 전환되었습니다([DB 안내](postgresql.md)). SQLite 시연 자료는 이관하지 않았으며, 당시 검증 화면의 위험은 실제 도로 위험이 아닙니다.
