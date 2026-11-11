# Render 배포 (단일 서버)

FastAPI 하나가 React 대시보드(`/dashboard/`), API(`/api/...`), WebSocket(`/api/ws`)을 같은 주소로 제공합니다. DB는 Supabase(`twinsight` 스키마)를 씁니다.

```
브라우저 → https://<서비스이름>.onrender.com
           ├ /login          팀 접속 키 로그인
           ├ /dashboard/     React 화면
           └ /api, /api/ws   API·실시간
                 ↓ Session pooler
           Supabase PostgreSQL
```

같은 출처라서 CORS·쿠키·WebSocket 설정을 따로 할 필요가 없습니다.

## 파일

| 파일 | 역할 |
|---|---|
| `Dockerfile` | 1단계 Node로 `frontend` 빌드 → 2단계 Python 3.14에 `backend/app`과 `frontend/dist` 복사 |
| `.dockerignore` | 모델·영상·Unity 파일 등은 이미지에 넣지 않음 |
| `render.yaml` | Render Blueprint (무료 플랜, 싱가포르, `/health` 상태 확인) |

## 1. 서비스 만들기

1. Render 가입 후 GitHub 연결 → **New → Blueprint** → 이 저장소 선택. `render.yaml`을 읽어 `twinsight` 웹 서비스를 만듭니다.
2. 처음 만들 때 비밀값을 입력합니다 (Git에는 넣지 않음).

| 이름 | 값 |
|---|---|
| `DATABASE_URL` | Supabase **Connect → Session pooler** 주소. `postgresql+psycopg://<앱계정>.<프로젝트>:<URL인코딩한 비밀번호>@<pooler 호스트>:5432/postgres?sslmode=require` |
| `TEAM_ACCESS_TOKEN` | 32자 이상 무작위 값. `python -c "import secrets; print(secrets.token_urlsafe(36))"` |
| `ITS_API_KEY` | ITS 인증키 |
| `VITE_CARTO_KEY` | (선택) CARTO 지도 키. 비우면 OpenStreetMap |

`DEPLOYMENT_MODE=cloud`, `DATABASE_SCHEMA=twinsight`, `DATABASE_AUTO_CREATE=false`는 `render.yaml`에 이미 들어 있습니다. `PUBLIC_BASE_URL`은 Render가 넣어 주는 `RENDER_EXTERNAL_URL`을 그대로 씁니다.

- `postgres` 관리자 계정이 아니라 `twinsight_backend` 권한을 받은 앱 계정을 씁니다 (`docs/map_database.md` 참고).
- `VITE_CARTO_KEY`는 빌드 때 화면에 들어가므로 바꾸면 **Manual Deploy**를 다시 해야 합니다.
- `autoDeploy: false`라서 main에 push해도 자동 배포되지 않습니다. Render 화면에서 **Manual Deploy**를 누릅니다.

### DB 연결 수

`twinsight_app` 역할에는 동시 연결 한도가 있고 팀원 PC 백엔드와 Render 서버가 함께 씁니다. 서버 하나는 최대 `DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW`개(Render 기본 2+1=3)를 열고, 배포 중에는 새·이전 서버가 잠시 동시에 뜹니다. 시작 로그에 `too many connections for role "twinsight_app"`이 나오면 관리자 계정으로 확인합니다.

```sql
SELECT rolconnlimit FROM pg_roles WHERE rolname = 'twinsight_app';
SELECT application_name, count(*) FROM pg_stat_activity WHERE usename = 'twinsight_app' GROUP BY 1;
ALTER ROLE twinsight_app CONNECTION LIMIT 20;  -- 필요 시
```

## 2. 배포 후 확인 순서

1. `https://<주소>/health` → `{"status":"ok"}`
2. `https://<주소>/` → 로그인 화면 → 팀 접속 키 입력 → `/dashboard/`
3. 상단 연결 표시가 "실시간 연결됨"인지 (WebSocket)
4. 카메라 마커가 보이는지. 비어 있으면 Supabase `cameras`에 카메라가 없는 것이므로 DB 관리 화면에서 등록하거나 로컬에서 `DATABASE_URL`을 Supabase로 두고 `seed_cameras.py`를 실행합니다.
5. **ITS 확인 (중요)**: `https://<주소>/api/cameras/its-cc4277cc18/stream`
   - 정상이면 스트림 주소가 옵니다. 주소가 `http://`로 시작하면 https 화면에서 영상이 차단되므로 백엔드 HLS 중계가 필요합니다.
   - 실패하면 Render(해외 서버)에서 ITS 접속이 막힌 것일 수 있습니다. 이때는 국내 PC에서 Cloudflare Tunnel로 띄우는 방법으로 바꿉니다.

## 3. 검출 결과 보내기

팀 로그인이 켜진 서버에는 Bearer 키가 필요합니다. `replay_jsonl.py`, `follow_detections.py`는 환경변수 `TEAM_ACCESS_TOKEN`이 있으면 자동으로 붙입니다.

```powershell
$env:TEAM_ACCESS_TOKEN = "<팀 접속 키>"
python backend/scripts/replay_jsonl.py --detections 결과/detections.jsonl --alerts 결과/alerts.jsonl --run-id <고유ID> --api https://<주소>
```

`--api`에는 `/api`를 붙이지 않습니다 (기존 경로도 그대로 제공됨).

## 참고

- 무료 플랜은 한동안 접속이 없으면 잠들어 첫 접속이 30초~1분 걸릴 수 있습니다. 발표 전에 미리 한 번 열어 둡니다.
- 서버 디스크는 재배포 때 초기화됩니다. 모든 데이터는 Supabase에 저장됩니다.
- 로컬에서 같은 이미지 확인: `docker build -t twinsight .` → `docker run --env-file .env -p 8000:8000 twinsight`
- 무료 플랜 조건은 바뀔 수 있으니 Render 요금 페이지에서 확인합니다.
