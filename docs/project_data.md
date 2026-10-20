# 프로젝트 데이터 관리 — 이상민 담당

이 시스템은 팀원이 생성한 결과를 연결해 보관하고 찾기 위한 카탈로그입니다. 모델 학습·객체 추적·도로 인식·가상환경 구성은 각 담당자의 기존 모듈이 수행합니다. 카탈로그는 그 결과의 출처, 설정, 지표, 파일 목록과 로그를 수집합니다.

## 팀 작업과 저장 대상

| 담당/단계 | 자료 종류(kind) | 주요 저장 내용 |
| --- | --- | --- |
| 재문 API 확보 → 상민 CCTV 수집 | `cctv_info` | 카메라 ID, 이름, 위경도, 해상도, PTZ 여부, 출처 |
| 우준 좌표 확보 | `calibration` | 좌표계·단위·원점, 기준점, Homography, 검증 오차 JSON |
| 진규·재헌 가상환경 설정 | `simulation` | Unity 씬·설정 파일, 가상 카메라 위치·회전, 사용 에셋 버전 |
| 가상환경 데이터 생성 | `capture` | camera.json, control_points.json, ground_truth.jsonl, 이미지 목록 |
| 학습 자료 준비 | `dataset` | provenance.json, dataset.yaml, 분할·라벨·클래스 정보, 이미지/라벨 해시 |
| 진규 모델 학습 | `training`, `model` | 학습 설정, results.csv 요약, 모델 가중치·해시, .log |
| 재헌 객체 추적·우준 도로 인식 | `detection`, `road_recognition` | 추적/도로 인식 결과, 세션 정보, 기존 검출 실행 ID |
| 구매한 CCTV로 성능 확인 | `evaluation` | 사용 모델, 시험 입력, 지표·결과 파일·오류 로그 |

각 자료의 `parents`에 사용한 이전 자료의 ID를 넣습니다. 예: 모델 → 학습 → 데이터셋 → 촬영 → 가상환경 → 캘리브레이션 → CCTV 정보. 다수의 입력 카메라/세션으로 만든 데이터셋은 여러 parents를 가집니다. 카메라 전체를 하나로 임의 지정하지 말고 `camera_id=null`로 두고 부모 관계를 통해 확인합니다.

`data_origin`은 `real`, `synthetic`, `mixed`, `unspecified` 중 등록자가 명시합니다. 가상환경 평가 수치를 실제 CCTV 평가 수치로 바꾸어 표시하지 않습니다. 부모 관계는 자료 사용 관계이며, 형식 검증만으로 현장 정확성이나 라벨 검수 완료를 증명하지 않습니다.

## DB와 파일 보관의 구분

- 기본 DB: PostgreSQL 17.11. `.env`의 `POSTGRES_*` 설정을 사용합니다. [DB 설정·이관](postgresql.md)을 참고하세요.
- 기존 카메라·검출·경고 테이블에 `catalog_records`, `catalog_parents`, `catalog_files`, `catalog_logs` 4개를 추가합니다. 앱 시작 시 생성하며 기존 테이블 데이터는 삭제하지 않습니다.
- 이미지·영상·모델 자체는 원래 폴더에 유지합니다. DB에는 상대 경로, 파일 크기, SHA-256, 역할을 저장합니다. `prepare` 도구는 `details.storage`에 원본 루트도 기록합니다. 다른 PC에서는 공유 폴더나 동일 자료 복사본에 접근할 수 있어야 합니다.
- DB 백업만으로 이미지/모델이 백업되지 않습니다. DB, 등록 manifest, 원본 폴더를 함께 보관해야 합니다. 파일 서버·오브젝트 스토리지 업로드는 아직 구현하지 않았습니다.
- `details`에는 JSON 설정·지표를 최대 512KiB 저장합니다. 큰 정답 JSONL·CSV는 파일로 등록합니다. `results.csv`는 마지막 행의 지표와 행 수를 요약하고, 전체 epoch 곡선은 원본 CSV에 남습니다.
- 로그는 `(record_id, stream, line_no)`로 중복을 제거합니다. 메시지 한 줄 최대 16,384자입니다. 외부 시각 정보가 없는 텍스트 로그에 시각을 만들어 붙이지 않습니다.

## CCTV API와 키 위치

ITS 키는 저장소 루트 **`.env`**의 아래 위치에 넣습니다. 이 파일은 Git에서 제외됩니다.

```dotenv
ITS_API_KEY=
STREAM_TTL_MINUTES=30
```

`ITS_API_KEY=` 뒤에 발급 키를 넣고 서버를 재시작합니다. 키를 채팅·등록 manifest·학습 로그에 적지 마세요. 다른 CCTV 제공처의 API는 재문 님에게 전달받은 명세에 맞춰 어댑터를 추가해야 하며 ITS 키와 동일하다고 가정하지 않습니다.

```powershell
.\.venv\Scripts\python.exe backend\scripts\fetch_its_cctv.py
# 서버 실행 후 Swagger에서 POST /cameras/import-its 호출
```

`POST /cameras`와 `/cameras/import-its`가 성공하면 비밀값을 제외한 CCTV 정보 스냅샷을 자동 등록합니다. ITS 가져오기는 `road_type`도 스냅샷에 남깁니다. 같은 내용은 중복 생성하지 않으며 위치·설정이 달라지면 다른 스냅샷 ID가 생깁니다. 이는 고유 상태 목록이며 모든 요청의 발생 순서를 기록하는 접근 로그는 아닙니다. 스트림 주소·API 키는 카탈로그에 복제하지 않습니다. 기존 검출 수신으로 자동 생성되는 `unknown` 카메라의 실정보 수집 완료를 주장하지 않습니다.

카탈로그 자체에는 외부 API 키가 필요 없습니다. 로컬 개발 서버 주소는 `http://localhost:8000`, API 탐색은 `http://localhost:8000/docs`입니다. 현재 서버는 인증 없는 로컬 개발용이며 다중 사용자 운영 인증·권한은 별도 작업입니다.

## 파일 등록 절차

backend/requirements.txt 환경에서 실행합니다. 검출용 PyTorch/Unity 설치 없이 등록 도구를 사용할 수 있습니다.

```powershell
# 1. 팀원이 생성한 결과 폴더를 검사하고 해시가 고정된 manifest 생성
.\.venv\Scripts\python.exe backend\scripts\catalog.py prepare --folder "datasets/scenario-safe" --record-id dataset-scenario-v1 --kind dataset --title "합성 위험물 데이터셋 v1" --owner "이상민" --origin synthetic --status completed --out "backend/data/dataset-scenario-v1.json"

# 2. 파일 내용이 manifest 작성 이후 변하지 않았는지 확인
.\.venv\Scripts\python.exe backend\scripts\catalog.py verify --manifest "backend/data/dataset-scenario-v1.json"

# 3. DB에 등록 (로컬 서버 실행 필요)
.\.venv\Scripts\python.exe backend\scripts\catalog.py register --manifest "backend/data/dataset-scenario-v1.json"
```

위 데이터셋 경로는 **예시**입니다. 이 PC에 아직 원본 데이터셋이 없으면 생성/전달받은 실제 폴더로 바꿔야 합니다. output manifest의 상위 폴더는 먼저 만들어 두세요.

학습 결과를 연결할 때:

```powershell
.\.venv\Scripts\python.exe backend\scripts\catalog.py prepare --folder "runs/detection/train_실행시각" --record-id training-scenario-v1 --kind training --title "합성 위험물 학습 v1" --owner "이상민" --origin synthetic --status completed --parent dataset-scenario-v1 --out "backend/data/training-scenario-v1.json"
.\.venv\Scripts\python.exe backend\scripts\catalog.py register --manifest "backend/data/training-scenario-v1.json"
```

`--parent`는 여러 번 지정할 수 있습니다. `--camera-id`는 이미 등록된 카메라 ID입니다. 검출 결과는 `--detection-run-id`와 일치하는 `--camera-id`를 함께 지정하면 기존 `/runs` 이력과 연결됩니다. 카탈로그 등록은 검출 JSONL을 `/ingest`로 재생하는 동작과 다릅니다. 실제 프레임 조회가 필요하면 기존 follow/replay 도구도 사용하세요.

`prepare`는 지정한 폴더 아래 파일을 재귀적으로 등록하므로 **개별 결과 폴더**를 지정하세요. `.env`, `.git`, `.venv` 등은 제외합니다. 로그/보고서 내용까지 자동으로 모든 비밀값을 판별하는 도구는 아니므로 등록 전 검토하세요. `camera.json`, `control_points.json`, `provenance.json`, `session.json`, `summary.json`, `metrics.json`, `dataset-check.json`은 파일당 128KiB 이하일 때 details.reports에 복사합니다. .log 파일은 본문도 수집합니다. 그 밖의 calibration/config JSON도 파일·해시로 보존하며, 필요한 검색 필드는 등록 전에 manifest의 details에 명시할 수 있습니다.

학습 프로그램의 표준 출력은 자동 저장되지 않습니다. 학습 담당자가 `.log`로 저장해 결과 폴더에 두면 수집됩니다. 이미 지나간 콘솔 로그를 복원하거나 학습을 대신 실행하지 않습니다.

## 버전·재시도 규칙

- `record_id`는 영문/숫자/점/밑줄/하이픈으로 최대 128자입니다. 제목·담당자는 한글을 사용할 수 있습니다.
- 같은 ID, 같은 내용 재등록은 성공합니다. 다른 설정·지표·부모 관계는 409입니다. 새 버전 ID로 등록하고 이전 버전을 parent로 연결하세요.
- `status`는 등록 당시의 스냅샷 상태입니다. running에서 completed로 덮어쓰는 작업 관리 기능은 없습니다. 완료 시 새 ID로 스냅샷을 등록하세요. 기록이 없다는 이유로 실패/완료를 추정하지 않습니다.
- 부모 자료를 먼저 등록해야 합니다. 부모 관계는 생성 후 변경 불가이므로 자기 참조와 순환을 막습니다. 원본 자료가 없는 경우 부모 관계를 만들어내지 말고 details에 누락 이유를 남기세요.
- 파일과 로그는 API 요청 한 번에 최대 500건, CLI는 200건 단위로 보냅니다. 각 요청은 원자적이지만 폴더 전체 등록은 여러 트랜잭션입니다. 중간 실패 시 같은 manifest로 재실행하면 이어서 등록됩니다. 실패한 실행을 전체 등록 완료로 간주하지 마세요.
- 파일 해시는 manifest 작성 시 고정합니다. 내용이 달라지면 등록을 중단합니다. 로그는 검증한 임시 복사본을 등록하여 업로드 도중 내용이 바뀌지 않게 합니다. 파일을 계속 쓰는 실행 대신 종료된 실행 또는 별도 스냅샷 폴더를 등록하세요.

## 재문 님 프론트엔드 연동 API

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| POST | `/catalog/records` | 버전별 자료 정보·부모 관계 등록 |
| GET | `/catalog/records?kind=&camera_id=&owner=&data_origin=&after_id=&limit=100` | 목록/필터, ID 오름차순 페이지 |
| GET | `/catalog/records/{id}` | 설정·지표·파일 루트·부모 ID 상세 |
| GET | `/catalog/records/{id}/lineage?direction=ancestors` | 원본 자료까지 추적 |
| GET | `/catalog/records/{id}/lineage?direction=descendants` | 이 자료를 사용한 후속 결과 |
| POST/GET | `/catalog/records/{id}/files` | 파일 메타데이터 등록/조회 |
| POST/GET | `/catalog/records/{id}/logs` | 로그 본문 등록/조회 |

목록은 `items`와 `next_after_id`를 반환하며, 커서가 null이면 끝입니다. files/logs의 커서는 서버 정수 ID, records의 커서는 문자열 record_id입니다. 로그는 `stream`으로도 필터링할 수 있습니다. 파일/로그 순서는 수신 ID 순서이므로 원본 순서가 필요하면 stream·line_no로 정렬하세요. lineage는 기본 200개 노드 제한이며 `truncated`가 true면 전체 관계가 아닙니다. 목록 조회/내보내기는 라이브 DB 전체의 일관된 시점 스냅샷은 아니므로 완료된 등록 건을 대상으로 사용하세요.

```powershell
.\.venv\Scripts\python.exe backend\scripts\catalog.py export --record-id training-scenario-v1 --out "out/training-scenario-v1-export"
```

새 폴더에 record.json, files.jsonl, logs.jsonl을 내보냅니다. `export-complete.json`이 있어야 내보내기가 끝난 것입니다. 원본 모델/이미지 바이트는 포함되지 않습니다. 기존 폴더를 덮어쓰지 않습니다.

## 이번에 실제 등록한 자료와 검증

`register_shared_results.py`는 저장소에 실제 존재하는 `scenario-hazards.pt`와 합성 test 보고서를 등록합니다. 모델 SHA-256이 MODEL_CARD와 일치하는지 먼저 확인합니다. 원본 데이터셋과 학습 실행 폴더는 없으므로 학습 기록을 새로 만들어내지 않았고, 재학습·재평가를 수행했다고 표시하지 않았습니다.

```powershell
.\.venv\Scripts\python.exe backend\scripts\register_shared_results.py
.\.venv\Scripts\python.exe -m pytest backend\tests -q
```

실제 등록 ID:

- `model-scenario-hazards-8e2e0be792f5`
- `evaluation-scenario-hazards-a945f0355a01` → 위 모델을 부모로 연결

1차 검증은 기존 API 회귀, 자료 단계 연결, 페이지 조회, 실제 파일 등록/내보내기를 확인합니다. 2차 검증은 데이터 출처 구분, 카메라/검출 실행 불일치, 순환 방지, 중복/충돌 롤백, 파일 경로 이탈, 파일 변경, 잘못된 로그의 사전 차단, 이전 DB 업그레이드와 원본 보존을 확인합니다. SQLite와 PostgreSQL에서 API 회귀를 검증했습니다. PostgreSQL 이관의 보존/롤백/ID 검증도 완료했으며, 운영 부하 검증과 MySQL 지원은 포함하지 않습니다.
