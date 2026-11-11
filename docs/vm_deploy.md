# 한국 VM 배포 (Oracle Cloud 무료 / AWS 서울)

Render(싱가포르)에서는 ITS API가 응답하지 않고(`ITS 호출에 실패했습니다: timed out`), ITS 영상 주소가 `http://`라서 https 화면에서 재생되지 않습니다. 한국 리전 VM 한 대에서 서버를 돌리고, 서버가 영상을 중계(`STREAM_PROXY=1`)하면 둘 다 해결됩니다. DB는 지금 Supabase를 그대로 씁니다.

```
브라우저 ─https→ 한국 VM
                  ├ caddy (자동 HTTPS, sslip.io 주소)
                  └ app (FastAPI + React)
                       ├ /api/cameras/{id}/hls/...  → http://cctvsec.ktict.co.kr (ITS 영상 중계)
                       └ DATABASE_URL               → Supabase (Session pooler)
```

## 1. VM 만들기 (Oracle Cloud 기준)

1. 가입할 때 **홈 리전을 South Korea Central (Seoul) 또는 South Korea North (Chuncheon)** 으로 고른다. 무료 VM은 홈 리전에서만 만들 수 있고 나중에 바꿀 수 없다.
2. 콘솔 → Compute → Instances → **Create instance**
   - Image: **Canonical Ubuntu 24.04**
   - Shape: **Always Free-eligible** 표시가 있는 것만. `VM.Standard.A1.Flex`(ARM, 권장) 또는 `VM.Standard.E2.1.Micro`
   - Networking: 새 VCN, **Assign a public IPv4 address** 켜기
   - SSH keys: **Save private key**로 키 파일(.key) 내려받기
3. 인스턴스 → 연결된 서브넷 → **Security List → Add Ingress Rules**
   - Source CIDR `0.0.0.0/0`, TCP, 포트 `80` / 같은 방식으로 `443`
4. 인스턴스 상세에서 **Public IP** 를 적어 둔다.

"Out of capacity"가 뜨면 다른 Availability Domain을 고르거나 잠시 뒤 다시 시도한다. 계속 안 되면 AWS 서울(EC2 t4g.small, Ubuntu)로 같은 단계를 진행한다(보안 그룹에서 80/443 허용).

## 2. 서버 설치

Windows PowerShell에서 접속:

```powershell
ssh -i C:\경로\ssh-key.key ubuntu@<Public IP>
```

VM 안에서:

```bash
curl -fsSL https://raw.githubusercontent.com/JAEMOON-LEEE/Computer-vision/deploy/render/deploy/vm/setup.sh | bash
```

Docker 설치, VM 안쪽 방화벽(80/443) 열기, 저장소 받기, `.env` 준비, sslip.io 주소 자동 기록까지 한다.

## 3. 설정 채우고 실행

```bash
nano ~/Computer-vision/deploy/vm/.env
```

| 이름 | 값 |
|---|---|
| `SITE_ADDRESS`, `PUBLIC_BASE_URL` | setup.sh가 채움 (예: `158-180-1-2.sslip.io`, `https://158-180-1-2.sslip.io`) |
| `TEAM_ACCESS_TOKEN` | 팀 접속 키 (Render와 같게 써도 됨) |
| `ITS_API_KEY` | ITS 인증키 |
| `DATABASE_URL` | Supabase Session pooler 주소 (Render와 같음) |
| `VITE_CARTO_KEY` | 선택 |

나머지(`STREAM_PROXY=1`, 연결 수 2+1 등)는 기본값 그대로 둔다. 저장(Ctrl+O, Enter) 후 종료(Ctrl+X).

```bash
cd ~/Computer-vision/deploy/vm
sudo docker compose up -d --build      # 처음 빌드는 5~15분
sudo docker compose logs -f app        # "Uvicorn running" 확인 후 Ctrl+C
```

## 4. 확인

1. `https://<SITE_ADDRESS>/health` → `{"status":"ok"}`
2. `https://<SITE_ADDRESS>/` → 로그인 → 대시보드, 카메라 263대
3. 카메라 카드를 펼쳐 영상 재생 확인. 안 되면 `https://<SITE_ADDRESS>/api/cameras/its-cc4277cc18/stream` 이 `/api/cameras/.../hls/index.m3u8` 를 주는지, 그 주소가 `#EXTM3U` 로 시작하는 내용을 주는지 본다.

## 업데이트

```bash
cd ~/Computer-vision && git fetch --depth 1 origin deploy/render && git checkout -B deploy/render FETCH_HEAD
cd deploy/vm && sudo docker compose up -d --build
```

## 참고

- 인증서는 Caddy가 Let's Encrypt로 자동 발급·갱신한다. 80/443이 밖에서 열려 있어야 한다(Security List + VM 안쪽 방화벽 둘 다).
- Render 서버를 계속 켜 두면 Supabase 연결을 함께 쓴다(각 최대 3개). `twinsight_app` 한도 20 안에서 충분하지만 안 쓰면 Render는 Suspend 해 둔다.
- 검출 PC에서 결과 보내기: `$env:TEAM_ACCESS_TOKEN="…"; python backend/scripts/replay_jsonl.py ... --api https://<SITE_ADDRESS>`
- ITS 영상 토큰이 "주소를 받은 IP"에서만 재생되는 방식이어도 같은 VM이 주소를 받고 영상도 받으므로 문제없다.
