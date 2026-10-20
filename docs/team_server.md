# 친구 PC를 TwinSight 팀 공용 서버로 만들기

친구 PC에 PostgreSQL과 FastAPI를 실행하고, 모델 실행 프로그램은 `http://127.0.0.1:8000`으로 결과를 보냅니다. 다른 팀원은 팀 전용 HTTPS 주소로 같은 API와 대시보드를 이용합니다. GPU는 모델이 사용하며 DB/API 컨테이너는 GPU를 요구하지 않습니다. PC가 꺼지거나 절전 상태면 팀 접속도 중단됩니다.

## 1. 친구 PC 준비

이 저장소 또는 전달받은 서버 ZIP을 친구 PC의 일반 폴더(예: `C:\TwinSightServer`)에 풉니다. 필요한 파일은 `Dockerfile.server`, `compose.server.yaml`, `deploy`, `backend`, `frontend`입니다. ZIP에는 기존 DB·비밀번호·모델·영상이 포함되지 않습니다.

[Docker 공식 설치 안내](https://docs.docker.com/compose/install/)에 따라 Docker와 Compose를 설치합니다. Windows는 [Docker Desktop 설치 조건](https://docs.docker.com/desktop/setup/install/windows-install/)을 확인하고 Linux 컨테이너를 사용합니다. Python은 모델 학습에 사용하는 Python을 사용할 수 있습니다.

프로젝트 루트에서 실행합니다(Windows PowerShell / Linux 공통).

```sh
python backend/scripts/setup_team_server.py
docker compose --env-file .env.server -f compose.server.yaml up -d --build --wait
docker compose --env-file .env.server -f compose.server.yaml ps
```

설정 생성기는 두 계정의 임의 비밀번호를 자동 생성하며, 기존 `.env.server`가 있으면 보존합니다. `ITS_API_KEY=`에는 재문이 전달한 ITS 키를 입력합니다. 기존 이 PC의 `.env`를 복사할 필요는 없습니다. 컨테이너에는 별도의 DB가 만들어지며, 기존 SQLite/PostgreSQL 자료는 자동 복사되지 않습니다.

친구 PC 브라우저에서 다음을 확인합니다.

- `http://127.0.0.1:8000/ready`: `database: connected`
- `http://127.0.0.1:8000/dashboard/`: 대시보드
- `http://127.0.0.1:8000/docs`: API 문서 및 요청 시험

처음에는 DB가 비어 있어 카메라·결과가 없는 것이 정상입니다. API 시작 시 테이블을 생성합니다. 호스트의 8000 포트를 이미 사용 중이면 `.env.server`의 `API_PORT`를 변경하고 접속 URL도 맞춥니다.

## 2. 각자 집에서도 접속하기

접속 환경이 아직 확정되지 않아, 기본 구성은 외부로 직접 공개하지 않고 localhost에만 연결합니다. PostgreSQL 포트는 호스트에 노출하지 않습니다.

원격 팀 접속은 [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve)를 이용할 수 있습니다. 친구와 팀원 PC에 Tailscale을 설치하고 **팀원만 가입된 팀 네트워크(tailnet)**에 연결합니다. 팀 관리자 계정으로 접근 정책을 확인하고 이 서버 접근을 해당 팀원으로 제한합니다. 현재 API에는 개별 사용자 로그인/역할 구분이 없으므로 접속 가능한 팀원은 자료를 등록·변경할 수 있습니다.

친구 PC에서 실행합니다.

```sh
tailscale serve --bg http://127.0.0.1:8000
tailscale serve status
```

명령이 표시하는 실제 `https://...ts.net` 주소를 팀원에게 전달합니다. 최초 HTTPS 활성화가 필요하면 명령이 안내하는 계정 설정을 완료합니다. 팀원들은 Tailscale 연결 후 다음 주소를 사용합니다.

- 대시보드: `https://표시된-서버-주소/dashboard/`
- API 문서: `https://표시된-서버-주소/docs`
- 등록 도구 `--api`: `https://표시된-서버-주소` (뒤에 `/docs`를 붙이지 않음)

Serve는 tailnet 내부 접속용이며 공개 인터넷용 Funnel과 다릅니다. 이 구성에서는 공유기 포트 포워딩이나 DB 포트 공개가 필요하지 않습니다. 기존에 Serve로 다른 서비스를 제공 중인 PC에서는 먼저 `tailscale serve status`로 설정을 확인합니다. 이 단계는 친구 PC의 로그인·설정이 필요해 아직 실행하지 않았습니다.

## 3. 모델 결과 연결

모델 프로그램과 서버가 같은 PC라면 다음처럼 기존 JSONL 결과를 등록합니다. 모델 실행 자체는 기존 담당자 코드를 그대로 사용합니다.

```sh
python backend/scripts/replay_jsonl.py --detections 결과폴더/detections.jsonl --alerts 결과폴더/alerts.jsonl --run-id 고유한실행ID --api http://127.0.0.1:8000
```

서버 ZIP에는 간단한 API 클라이언트 도구도 포함되어 있습니다. 호스트 Python에 라이브러리가 없다면 `python -m pip install httpx`가 필요합니다. `alerts.jsonl`이 없으면 해당 옵션을 생략합니다. 다른 팀원 PC에서는 `--api`를 위 HTTPS 주소로 바꿉니다. 학습 자료·모델·평가 로그는 [자료 등록 안내](project_data.md)의 `catalog.py prepare/register`를 사용합니다.

DB는 모델/영상 원본을 자동 업로드하지 않습니다. 원본 파일은 팀 공유 저장소에 보관하고 파일 경로·해시·실행 관계를 DB에 등록합니다. 기존 PC의 절대 경로는 친구 PC에서 그대로 열리지 않으므로 공유 경로를 맞춰야 합니다.

## 4. 운영과 백업

```sh
# 상태와 로그
docker compose --env-file .env.server -f compose.server.yaml ps
docker compose --env-file .env.server -f compose.server.yaml logs --tail 100 api
# 정지 (데이터 볼륨 보존)
docker compose --env-file .env.server -f compose.server.yaml down
# 재시작
docker compose --env-file .env.server -f compose.server.yaml up -d --wait
```

`down -v`는 DB를 삭제하므로 사용하지 않습니다. Docker가 실행되어 있어야 자동 재시작 정책이 작동합니다. Windows에서는 Docker Desktop 로그인 시 실행 여부와 PC 절전 설정을 확인합니다. 학습과 함께 실행할 때 RAM·디스크 사용량을 확인하고, 학습 프로그램이 메모리를 모두 점유하면 서버를 별도 PC로 분리합니다.

백업은 컨테이너 안에서 만든 뒤 복사하면 Windows 셸에서도 바이너리가 손상되지 않습니다.

```sh
docker compose --env-file .env.server -f compose.server.yaml exec -T postgres pg_dump -U twinsight_admin -d twinsight -Fc -f /tmp/twinsight.dump
docker compose --env-file .env.server -f compose.server.yaml cp postgres:/tmp/twinsight.dump ./twinsight-backup.dump
```

백업 파일은 날짜를 붙여 별도 저장소에 보관하세요. `.env.server`와 모델/영상 원본도 별도로 보관해야 합니다. 기존 DB 복원은 빈 대상 DB에서 진행해야 하므로 팀이 사용하기 전에 이관 대상을 먼저 확정합니다. 초기화된 DB 비밀번호는 `.env.server` 편집만으로 바뀌지 않습니다.

API는 WebSocket 연결을 프로세스 메모리에서 관리하므로 현재 `workers=1`입니다. 여러 프로세스로 늘리려면 공유 메시지 전달 구성이 먼저 필요합니다.

## 검증 범위

로컬 PostgreSQL에서 API 회귀 및 서버 준비 상태·대시보드 제공 테스트를 실행합니다. HTTPS 주소에서 API와 WebSocket 주소 생성도 별도 점검합니다. 이 작업 PC에는 Docker가 없어 이미지 빌드·컨테이너 기동은 검증하지 못했습니다. 친구 PC에서 위 `up --wait`, `/ready`, 팀원 원격 접속을 확인하면 설치 완료입니다.
