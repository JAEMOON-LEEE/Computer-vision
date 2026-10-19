"""저장소 시드 JSON으로 카메라를 등록한다. ITS API는 호출하지 않는다.

시드가 있으면 그 파일을 쓴다. 없고 로컬 후보 JSON만 있으면 주소와 키를 뺀 시드를 만든 뒤 등록한다.

예 (저장소 루트):
    .\\.venv\\Scripts\\python.exe backend\\scripts\\seed_cameras.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SEED_PATH = ROOT / "backend" / "seeds" / "cameras_its.json"
CANDIDATES_PATH = ROOT / "backend" / "data" / "its" / "candidates_its.json"
PUBLIC_FIELDS = ("camera_id", "name", "source", "lat", "lon")


def _env_key() -> str:
    """시드에 인증키가 섞였는지 비교만 한다. 값은 출력하지 않는다."""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("ITS_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def assert_no_secrets(text: str) -> None:
    lowered = text.lower()
    for token in ("stream_url", "cctvurl", "apikey", "api_key", "http://", "https://"):
        if token in lowered:
            raise SystemExit("시드에 스트림 주소나 키가 있습니다. 등록을 멈춥니다.")
    key = _env_key()
    if key and key in text:
        raise SystemExit("시드에 인증키가 있습니다. 등록을 멈춥니다.")


def public_record(item: dict) -> dict:
    """등록에 쓰는 필드만 남긴다. 스트림 주소는 넣지 않는다."""
    if not isinstance(item, dict) or not item.get("camera_id"):
        raise SystemExit("시드 항목에 camera_id가 없습니다")
    lat = item.get("lat")
    lon = item.get("lon")
    try:
        lat_value = None if lat in (None, "") else float(lat)
        lon_value = None if lon in (None, "") else float(lon)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"위경도를 해석할 수 없습니다: {item.get('camera_id')}") from exc
    return {
        "camera_id": str(item["camera_id"]),
        "name": item.get("name") or str(item["camera_id"]),
        "source": item.get("source") or "ITS",
        "lat": lat_value,
        "lon": lon_value,
    }


def _read_array(path: Path) -> list:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"JSON을 해석할 수 없습니다: {path.name}") from exc
    if not isinstance(raw, list):
        raise SystemExit(f"{path.name}은 배열이어야 합니다")
    return raw


def write_seed(records: list[dict]) -> None:
    text = json.dumps([{key: row[key] for key in PUBLIC_FIELDS} for row in records], ensure_ascii=False, indent=2) + "\n"
    assert_no_secrets(text)
    SEED_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEED_PATH.write_text(text, encoding="utf-8")


def load_records() -> list[dict]:
    if SEED_PATH.is_file():
        assert_no_secrets(SEED_PATH.read_text(encoding="utf-8"))
        return [public_record(item) for item in _read_array(SEED_PATH)]
    if CANDIDATES_PATH.is_file():
        records = [public_record(item) for item in _read_array(CANDIDATES_PATH)]
        write_seed(records)
        return records
    raise SystemExit("시드 파일이 없습니다: backend/seeds/cameras_its.json")


def register(records: list[dict]) -> int:
    from backend.app.db import SessionLocal, init_db
    from backend.app.routers.cameras import upsert_camera

    init_db()
    if SessionLocal is None:
        raise SystemExit("DB 세션을 만들지 못했습니다")
    with SessionLocal() as db:
        for item in records:
            upsert_camera(
                db,
                item["camera_id"],
                {
                    "name": item["name"],
                    "source": item["source"],
                    "lat": item["lat"],
                    "lon": item["lon"],
                    "stream_url": None,
                    "stream_fetched_at": None,
                },
            )
        db.commit()
    return len(records)


def main() -> None:
    count = register(load_records())
    print(f"카메라 {count}대 등록")


if __name__ == "__main__":
    main()
