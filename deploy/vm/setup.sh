#!/usr/bin/env bash
# Ubuntu VM(Oracle Cloud / AWS)에서 한 번 실행: Docker 설치, 방화벽 열기, 저장소 받기.
# 사용: curl -fsSL https://raw.githubusercontent.com/JAEMOON-LEEE/Computer-vision/deploy/render/deploy/vm/setup.sh | bash
set -euo pipefail
BRANCH="${BRANCH:-deploy/render}"
REPO="${REPO:-https://github.com/JAEMOON-LEEE/Computer-vision.git}"
DIR="$HOME/Computer-vision"

echo "== 1/4 Docker 설치"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
fi

# 메모리 1GB짜리 VM(E2.1.Micro 등)에서도 이미지 빌드가 되도록 스왑 2GB를 만든다.
if [ "$(awk '/MemTotal/{print $2}' /proc/meminfo)" -lt 3000000 ] && ! swapon --show | grep -q /swapfile; then
  echo "== 메모리가 작아 스왑 2GB 추가"
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
  grep -q /swapfile /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

echo "== 2/4 VM 안쪽 방화벽에서 80/443 열기 (Oracle Ubuntu 이미지는 기본으로 막혀 있음)"
if sudo iptables -L INPUT -n 2>/dev/null | grep -q "REJECT"; then
  for port in 80 443; do
    sudo iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null || \
      sudo iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
  done
  if command -v netfilter-persistent >/dev/null; then sudo netfilter-persistent save; fi
fi

echo "== 3/4 저장소 받기 ($BRANCH, 대용량 LFS 파일은 받지 않음)"
export GIT_LFS_SKIP_SMUDGE=1
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch --depth 1 origin "$BRANCH" && git -C "$DIR" checkout -B "$BRANCH" FETCH_HEAD
else
  git clone --depth 1 --branch "$BRANCH" "$REPO" "$DIR"
fi

echo "== 4/4 설정 파일 준비"
cd "$DIR/deploy/vm"
[ -f .env ] || cp .env.example .env
IP="$(curl -fsS https://api.ipify.org || true)"
if [ -n "$IP" ] && ! grep -q '^SITE_ADDRESS=.\+' .env; then
  HOST="${IP//./-}.sslip.io"
  sed -i "s|^SITE_ADDRESS=.*|SITE_ADDRESS=$HOST|; s|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://$HOST|" .env
fi
cat <<MSG

준비 끝. 다음을 진행하세요.
  1) nano $DIR/deploy/vm/.env   → 비어 있는 값(TEAM_ACCESS_TOKEN, ITS_API_KEY, DATABASE_URL 등) 채우기
  2) cd $DIR/deploy/vm && sudo docker compose up -d --build
  3) 접속 주소: https://$(grep '^SITE_ADDRESS=' .env | cut -d= -f2)
MSG
