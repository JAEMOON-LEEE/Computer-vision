# PostgreSQL 사용 및 이관

현재 기본 DB는 PostgreSQL 17.11입니다. 모델의 GPU 추론 자체는 DB 없이 가능하고, CCTV 정보·검출/추적 결과·위험 이력·학습 산출물 및 로그를 함께 관리할 때 백엔드 API를 사용합니다. MySQL은 이번 변경에서 연결하지 않았습니다.

## 이 PC에서 실행

공식 EDB Windows 바이너리를 사용자 홈 `.twinsight/postgresql-17/pgsql`에 설치했습니다. 데이터는 같은 폴더의 `data`에 있으며 OneDrive 밖에 있습니다. Windows 서비스/부팅 자동 시작은 등록하지 않았습니다. 재부팅 후 저장소 루트에서 다음 명령을 실행합니다.

```powershell
powershell -ExecutionPolicy Bypass -File backend/scripts/postgres_local.ps1 start
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

`status`, `stop` 인자로 상태 확인과 종료가 가능합니다. 현재 기본 포트는 5432입니다. 네이티브 서버와 Docker 서버를 같은 포트에서 동시에 실행하지 마세요.

루트 `.env`에는 생성된 전용 계정 비밀번호가 설정되어 있습니다. 앱 계정 `twinsight`는 DB 소유자이며 슈퍼유저가 아닙니다. 관리자 비밀번호는 사용자 홈 `.twinsight/postgresql-17/credentials.json`에 보관합니다. 공유/커밋하지 마세요.

| 설정 | 용도 |
| --- | --- |
| `POSTGRES_HOST`, `POSTGRES_PORT` | DB 서버 주소, 포트 |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | DB 이름, 계정, 비밀번호 |
| `DATABASE_URL` | 선택적 전체 연결 URL. 값이 있으면 위 설정보다 우선 |
| `ITS_API_KEY` | 재문이 전달한 ITS API 키 입력 위치. DB 연결과 별개 |

기본값은 `127.0.0.1:5432`, DB/사용자 이름은 `twinsight`입니다. 설정 변경 후 API를 재시작합니다.

## 팀원 PC / 새 서버에서 Docker로 구성

Docker 설치 후 `.env.example`을 `.env`로 복사하고 `POSTGRES_PASSWORD`를 채웁니다. 이미 설정된 `.env`를 덮어쓰지 마세요.

```powershell
docker compose up -d postgres
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Docker 데이터는 named volume에 유지됩니다. `docker compose down`으로 정지할 수 있습니다. `down -v`는 DB 데이터를 삭제하므로 사용하지 마세요. Compose의 초기 계정은 개발용 슈퍼유저입니다. 공용 운영 서버에서는 앱 계정을 별도로 분리해야 합니다. 초기화된 volume의 비밀번호는 `.env` 수정만으로 변경되지 않습니다.

각자 Docker를 띄우면 각자 별도 DB가 만들어집니다. **공동 저장소로 쓰려면 한 서버의 API를 함께 사용해야 합니다.** 팀원은 [산출물 등록 도구](project_data.md)의 `--api`에 공용 API 주소를 지정합니다. 현재 설치는 이 PC의 localhost 연결까지만 완료되었으며, 외부 공개·인증·방화벽 설정은 포함하지 않습니다. 모델/영상 파일은 공유 파일 저장소에 두고 DB에는 위치와 해시를 저장합니다.

## SQLite 이관과 검증

API 및 모든 쓰기 작업을 중지하고, `.env`가 **빈 대상 PostgreSQL DB**를 가리키는지 확인한 후 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m backend.scripts.migrate_sqlite --source backend/data/twinsight.db
```

SQLite backup API로 원본의 일관된 복사본을 `backend/data/backups/`에 보관하고, 그 복사본에서 읽습니다. 대상 테이블 잠금, 외래 키 순서 삽입, 테이블별 행 수/내용 SHA-256 비교, 자동 증가 시퀀스 복구 후 커밋합니다. 대상에 데이터가 있거나 원본 스키마가 다르면 중단하며 기존 자료를 덮어쓰지 않습니다. 보고서도 같은 백업 폴더에 저장합니다. 이관은 테이블 단위로 메모리에 적재하므로 대규모 프레임 이력에는 별도 배치 이관이 필요합니다.

SQLite의 시간대 없는 `created_at` 등은 기존 코드의 UTC로 해석합니다. `stream_fetched_at`은 기본 Asia/Seoul이며, 다른 지역에서 수집했다면 `--stream-timezone`으로 실제 원본 시간대를 지정해야 합니다.

2026-10-19 이 PC에서는 12개 테이블 검증을 완료했습니다. 실제 저장된 모델/평가 2건, 파일 메타데이터 4건, 부모 관계 1건을 옮겼으며 CCTV/검출/로그 이력은 원래 비어 있습니다. `map-review.db`의 시연 자료는 이관하지 않았습니다. 원본 `twinsight.db`와 별도 백업을 모두 유지합니다.

## 테스트와 백업

기본 `python -m pytest backend/tests -q`는 임시 SQLite를 사용합니다. PostgreSQL 통합 검증은 `TEST_DATABASE_URL`에 `postgresql+psycopg://...` 연결 URL을 환경 변수로 지정하여 같은 명령을 실행합니다. 테스트마다 임의 스키마를 생성/삭제하며 운영 테이블을 사용하지 않습니다. 테스트 계정에 스키마 생성 권한이 필요합니다. 이관 테스트는 PostgreSQL에서만 실행됩니다.

현재 API 회귀 52개와 이관 2개를 PostgreSQL에서 검증했습니다. 이관 테스트는 자동 증가 ID, 한글 및 시간 보존, 중복 이관 차단, 외래 키 오류 전체 롤백을 검사합니다. 동시 쓰기 부하·운영 장애 복구 테스트는 수행하지 않았습니다. Docker 구성은 제공했으나 이 PC에는 Docker가 없어 컨테이너 실행 검증은 하지 않았습니다.

주기적인 DB 백업은 `pg_dump -h 127.0.0.1 -U twinsight -d twinsight -Fc -f backup.dump`로 생성하고 별도 저장소에 보관합니다. 이 PC의 실행 파일은 사용자 홈 `.twinsight/postgresql-17/pgsql/bin/pg_dump.exe`입니다. 비밀번호는 프롬프트에서 입력합니다. 복원은 빈 DB에 `pg_restore`로 진행하고 별도 검증해야 합니다. DB 백업에는 원본 영상/모델 파일이 포함되지 않습니다.

참고: [EDB 공식 Windows 바이너리](https://www.enterprisedb.com/download-postgresql-binaries), [SQLAlchemy PostgreSQL psycopg 연결](https://docs.sqlalchemy.org/en/21/dialects/postgresql.html#module-sqlalchemy.dialects.postgresql.psycopg).
