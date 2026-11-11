# 저장 결과 DB 운영

2026-11-11 기준 기존 `twinsight` 12개 테이블에 다음 3개 테이블을 추가했다.
이 문서의 API는 기존 팀 접근 인증을 사용하며 DB 비밀번호를 브라우저에 전달하지 않는다.

| 테이블 | 목적 | 주요 키 |
|---|---|---|
| `calibration_versions` | 확인된 카메라 보정 파일의 버전·해상도·좌표계·파라미터·SHA-256 | `calibration_id`, `(camera_id, version)` 고유 |
| `experiment_bindings` | 저장 로그 스트림과 실험 산출물·보정 버전의 명시적 연결 | `(record_id, stream)` 기본 키 |
| `catalog_audit` | 산출물 INSERT/UPDATE/DELETE, 보정·연결 INSERT 이력 | `id` |

`catalog_records.updated_at`도 추가했다. 과거 324개 산출물의 수정 시점은 알 수 없으므로 NULL로 남겼다. 이후 변경부터 DB 트리거가 기록한다.

## 적용 순서와 권한

`supabase/migrations/20261111012313_catalog_governance.sql`은 **기존 twinsight 스키마와 역할이 있는 DB**에 적용하는 추가 마이그레이션이다. 빈 DB 전체를 생성하는 기준 스키마가 아니다. 관리자가 마이그레이션을 먼저 적용한 뒤 백엔드를 재시작한다. 운영 환경은 `DATABASE_AUTO_CREATE=false`를 유지한다.

새 테이블은 RLS를 사용하며 `anon`, `authenticated`에는 접근 권한이 없다. 기존 `twinsight_backend` 역할은 보정/연결을 SELECT·INSERT할 수 있고 이력은 SELECT만 가능하다. 보정/연결을 수정·삭제하는 API는 제공하지 않는다. 기존 결과에 사용한 보정을 바꾸려면 새 결과 산출물과 새 버전을 등록한다. 잘못 등록한 메타데이터는 관리자가 별도 검토 후 정정한다.

감사 트리거만 private schema의 SECURITY DEFINER로 실행하여 클라이언트에 이력 쓰기 권한을 주지 않는다. 검색 경로는 고정하고 공개 EXECUTE 권한은 제거했다. 기록되는 `database_actor`는 PostgreSQL 로그인 계정이다. 팀원들이 같은 DB 계정을 공유하면 개인을 구분할 수 없다. 감사 범위는 위 세 테이블의 명시된 작업이며, 관리자 작업·TRUNCATE·파일/로그 테이블 전체 변경 이력을 대체하지 않는다. 큰 `details` 원문은 이력에 복제하지 않고 변경 식별용 MD5만 기록한다. 파일 무결성 확인에는 SHA-256을 사용한다.

## API

- `GET /api/database/saved-results/search?q=&limit=25&offset=0`: 이름/ID 부분 검색, 최대 100개. 반환값은 `items`, `total`, `limit`, `offset`. 큰 summary는 포함하지 않는다.
- `GET /api/database/saved-results/record?record_id=...`: 선택한 작업 summary, 수정 시점, 보정 연결 조회.
- `GET /api/database/saved-results/frame?record_id=...&source=ground_truth&offset=0`: 기존 프레임 조회.
- `GET /api/database/tables/{name}`: DB 관리 화면에서 새 테이블도 조회 가능.
- `POST /api/database/calibrations`: 보정 버전 등록.
- `POST /api/database/experiment-bindings`: 정확한 로그 스트림 단위의 연결 등록.

기존 `GET /api/database/saved-results` 응답은 호환성을 위해 유지한다. 새 대시보드는 검색 API로 25개씩 불러오고 작업 요약을 펼칠 때만 상세 내용을 조회한다.

보정 등록 예시(값은 예시이며 실제 파일 검증 없이 등록하지 않는다):

```json
{
  "calibration_id": "camera-a-v1",
  "camera_id": "camera-a",
  "version": "v1",
  "image_width": 720,
  "image_height": 480,
  "coordinate_system": "unity_xz_m",
  "parameters": {"description": "실제 검증된 보정 파라미터로 교체"},
  "source_sha256": "원본 보정 파일의 소문자 SHA-256 64자리로 교체"
}
```

좌표계는 `unity_xz_m` 또는 `local_east_north_m`이다. 해시는 등록자가 원본 파일에서 계산해야 한다. 현재 API는 메타데이터 저장 기능이며 임의 파라미터로 좌표 변환을 자동 실행하지 않는다.

연결 본문에는 `record_id`, 정확한 `stream`, `experiment_id`, `camera_id`, `image_width`, `image_height`, `calibration_id`를 보낸다. `calibration_id`는 보정 없는 원본 결과라면 NULL일 수 있다. 스트림의 **모든 프레임**이 같은 카메라와 해상도인지 검사하며 보정 버전의 카메라·해상도도 일치해야 한다. API와 PostgreSQL 트리거에서 모두 확인한다. 기존 결과는 근거 없이 자동 연결하지 않았다. 가상환경 정답 좌표는 실제 위경도와 구분해서 표시한다.

## 백업과 복구

저장소 밖의 비공개 폴더에 백업한다. 백업에는 팀 데이터가 포함되므로 Git에 올리지 않는다.

```powershell
python backend/scripts/backup_catalog.py --env-file <비공개-env-경로> --pg-bin <PostgreSQL17-bin-경로> --output <새-백업-폴더>
```

동일한 REPEATABLE READ 스냅샷으로 테이블 덤프와 바이너리를 추출한다. `schema-data.dump`는 스키마·테이블·정책을 포함하지만 글로벌 역할/비밀번호와 Large Object 내용은 포함하지 않는다. Large Object는 `large-object-<oid>.bin`으로 별도 저장한다. `manifest.json`은 행 수, OID, 크기, SHA-256을 기록하며 전체 성공 시에만 생성된다. 카탈로그에 없는 소유 Large Object가 발견되면 불완전한 백업으로 실패한다.

복원은 격리된 PostgreSQL에 필요한 역할을 먼저 생성하고 `pg_restore --no-owner --no-privileges --exit-on-error`로 덤프를 복원한다. 그 다음 **클라이언트에서** 각 바이너리를 읽고 `lo_create(원본 OID)`와 `lo_put(OID, offset, bytes)`로 복구한다. OID가 충돌하는 기존 DB에 덮어쓰지 않는다. 테이블 행 수와 복원된 `lo_get` 내용의 SHA-256을 manifest와 비교한다. 원격 서버 파일 읽기 기능은 사용하지 않는다. 운영 복구 시에는 원래 역할 소유권·권한도 별도로 복원해야 한다.

2026-11-11 실제 복구 검증: 기존 12개 테이블 행 수 일치, 바이너리 3개/338,429,312바이트 해시 일치. 산출물 324, 파일 30,643, 로그 21,325, 부모 관계 510개를 확인했다. 나머지 8개 테이블은 0개였다.

## 검증

`python -m pytest backend/tests -q`와 `frontend`의 `npm run build`를 실행한다.
`backend/tests/catalog_governance_postgres.sql`은 마이그레이션 적용 후 backend 로그인으로 실행하는 PostgreSQL 검증이다. 감사 기록, 무변경 UPDATE, 카메라/해상도 불일치, 수정 금지, 비공개 권한을 검사하고 마지막에 ROLLBACK한다. 테스트 시퀀스 번호는 증가할 수 있다.
