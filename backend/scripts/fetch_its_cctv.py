"""ITS(국가교통정보센터) CCTV 목록을 한 번 받아서 저장하고 교차로 후보를 뽑는다.

호출 1번 = 월 호출 한도 1건. 목록은 이 스크립트로 가끔만 받고,
팀원은 저장된 JSON 파일을 같이 쓴다. 영상 재생(cctvurl 접속)은 별도 호출이 아니다.

사용법 (저장소 루트에서):
    python backend/scripts/fetch_its_cctv.py                 # 서울·경기 국도
    python backend/scripts/fetch_its_cctv.py --type ex       # 고속도로
    python backend/scripts/fetch_its_cctv.py --bbox 126.8 127.2 37.4 37.7
    python backend/scripts/fetch_its_cctv.py --offline       # 호출 없이 저장된 파일만 다시 필터

인증키: 저장소 루트의 .env 파일에 ITS_API_KEY=발급키 (깃허브에 올리지 않음)
출처 표기: 국토교통부 국가교통정보센터(ITS), 공공누리 제1유형
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "backend" / "data" / "its"
ENDPOINT = "https://openapi.its.go.kr:9443/cctvInfo"
DEFAULT_BBOX = (126.5, 127.6, 37.0, 37.95)  # minX, maxX, minY, maxY (서울·경기)
CANDIDATE_PATTERN = r"교차로|사거리|오거리|삼거리|IC|JC"


def load_key() -> str:
    key = os.environ.get("ITS_API_KEY")
    env_file = ROOT / ".env"
    if not key and env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ITS_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not key or not key.isascii() or "여기에" in key:
        sys.exit(f"인증키가 비어 있거나 예시 문구 그대로입니다. {env_file} 의 ITS_API_KEY= 뒤에 발급받은 키를 넣어주세요.")
    return key


def parse(text: str) -> list[dict]:
    """JSON으로 오면 JSON, XML로 오면 XML로 읽어 CCTV 목록을 돌려준다."""
    try:
        body = json.loads(text)
        data = body.get("response", {}).get("data", [])
        return data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        pass
    root = ET.fromstring(text)
    items = []
    for node in root.iter("data"):
        item = {child.tag: (child.text or "").strip() for child in node}
        if item:
            items.append(item)
    return items


def log_call(type_: str, bbox, count: int) -> int:
    """호출 기록을 남기고 이번 달 호출 수를 돌려준다."""
    log = OUT_DIR / "call_log.txt"
    now = dt.datetime.now()
    with log.open("a", encoding="utf-8") as f:
        f.write(f"{now:%Y-%m-%d %H:%M:%S}\ttype={type_}\tbbox={bbox}\tresults={count}\n")
    month = f"{now:%Y-%m}"
    return sum(1 for line in log.read_text(encoding="utf-8").splitlines() if line.startswith(month))


def main() -> None:
    ap = argparse.ArgumentParser(description="ITS CCTV 목록 받기")
    ap.add_argument("--type", default="its", choices=["its", "ex"], help="its=국도, ex=고속도로")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("MINX", "MAXX", "MINY", "MAXY"),
                    default=DEFAULT_BBOX, help="경도 최소·최대, 위도 최소·최대")
    ap.add_argument("--offline", action="store_true", help="API 호출 없이 저장된 목록만 다시 필터")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    list_path = OUT_DIR / f"cctv_{args.type}.json"

    if args.offline:
        if not list_path.exists():
            sys.exit(f"{list_path} 가 없습니다. 먼저 --offline 없이 한 번 실행하세요.")
        items = json.loads(list_path.read_text(encoding="utf-8"))
    else:
        min_x, max_x, min_y, max_y = args.bbox
        params = {"apiKey": load_key(), "type": args.type, "cctvType": 1,
                  "minX": min_x, "maxX": max_x, "minY": min_y, "maxY": max_y, "getType": "json"}
        url = f"{ENDPOINT}?{urllib.parse.urlencode(params)}"
        try:
            with urllib.request.urlopen(url, timeout=30) as res:
                text = res.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:500]
            hint = {401: "인증 실패: 키 오타, 승인 전 키, CCTV 서비스 미신청 여부를 확인하세요."}.get(e.code, "")
            sys.exit(f"HTTP {e.code} {hint}\n서버 응답: {body}")
        (OUT_DIR / f"cctv_{args.type}_raw.txt").write_text(text, encoding="utf-8")
        try:
            items = parse(text)
        except ET.ParseError:
            sys.exit(f"응답을 해석하지 못했습니다. {OUT_DIR / f'cctv_{args.type}_raw.txt'} 를 확인하세요.")
        list_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        used = log_call(args.type, args.bbox, len(items))
        print(f"[호출 완료] 이번 달 이 PC에서 {used}건 사용")

    print(f"전체 {len(items)}개 -> {list_path}")
    hits = [c for c in items if re.search(CANDIDATE_PATTERN, c.get("cctvname", ""))]
    candidates = [{
        # URL 경로에 그대로 쓸 수 있도록 이름 해시로 고정 ID 생성 (이름이 같으면 항상 같은 ID)
        "camera_id": "its-" + hashlib.sha1(c.get("cctvname", "").encode("utf-8")).hexdigest()[:10],
        "name": c.get("cctvname"),
        "source": "ITS",
        "road_type": args.type,
        "lat": float(c["coordy"]) if c.get("coordy") else None,
        "lon": float(c["coordx"]) if c.get("coordx") else None,
        "stream_url": c.get("cctvurl"),
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
    } for c in hits]
    cand_path = OUT_DIR / f"candidates_{args.type}.json"
    cand_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2), encoding="utf-8")

    for c in candidates:
        print(f"  {c['name']:<32} {c['lat']}, {c['lon']}")
    print(f"교차로 후보 {len(candidates)}개 -> {cand_path}")
    print("stream_url 은 만료될 수 있습니다. VLC(미디어 > 네트워크 스트림 열기)로 확인하세요.")


if __name__ == "__main__":
    main()
