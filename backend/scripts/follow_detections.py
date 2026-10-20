"""검출 출력 폴더의 jsonl을 따라 읽어 API로 보낸다.

detections.jsonl은 프레임마다 바로 기록된다. alerts.jsonl은 --alerts일 때만 생기므로
파일이 없어도 기다린다. summary.json이 생기고 더 읽을 줄이 없으면 실행이 끝난 것이다.

예 (저장소 루트, 서버가 떠 있을 때):
    .\\.venv\\Scripts\\python.exe backend\\scripts\\follow_detections.py --run-dir runs\\detection\\20261018_120000
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]


class TailReader:
    """파일 끝에 붙는 완전한 줄만 읽고, 줄바꿈 전 조각은 다음 폴링까지 들고 있는다."""

    def __init__(self, path: Path, from_start: bool = True):
        self.path = path
        self.offset = 0
        self.pending = ""
        # from_start가 아니면 처음 볼 때 파일 끝으로 이동해 이후 줄만 읽는다.
        self._positioned = from_start

    def read_lines(self) -> list[str]:
        if not self.path.is_file():
            return []
        size = self.path.stat().st_size
        if not self._positioned:
            self.offset = size
            self._positioned = True
            return []
        if size < self.offset:
            self.offset = 0
            self.pending = ""
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            raw = handle.read()
            start = self.offset
            self.offset = handle.tell()
        if not raw:
            return []
        text = raw.decode("utf-8-sig" if start == 0 else "utf-8", errors="replace")
        combined = self.pending + text
        if combined.endswith("\n"):
            self.pending = ""
            chunks = combined.split("\n")[:-1]
        else:
            chunks = combined.split("\n")
            self.pending = chunks[-1]
            chunks = chunks[:-1]
        lines = []
        for chunk in chunks:
            line = chunk[:-1] if chunk.endswith("\r") else chunk
            if line.strip():
                lines.append(line)
        return lines


def safe_run_id(run_id: str) -> str:
    return run_id.replace("/", "_").replace("\\", "_").replace(":", "_")


def failed_log_path(run_id: str) -> Path:
    return REPO_ROOT / "backend" / "data" / f"failed_{safe_run_id(run_id)}.jsonl"


def append_failed(run_id: str, kind: str, line: str) -> None:
    path = failed_log_path(run_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"kind": kind, "line": line}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def warn_missing_camera(client, camera_id: str | None, checked: set[str]) -> None:
    """카메라 목록에 없으면 한 번만 알린다. 확인 요청이 실패해도 전송은 계속한다."""
    if not camera_id or camera_id in checked:
        return
    checked.add(camera_id)
    try:
        response = client.get("/cameras/" + quote(str(camera_id), safe=""))
    except Exception:
        return
    if getattr(response, "status_code", None) == 404:
        print(
            f"[주의] 카메라 목록에 없는 camera_id: {camera_id}. "
            "지도에 표시되지 않습니다. 검출 실행 시 --camera-id를 카메라 목록의 ID로 맞추세요.",
            flush=True,
        )


def warn_ignored_alerts(response, run_id: str) -> None:
    try:
        body = response.json()
    except Exception:
        return
    ignored = body.get("ignored") if isinstance(body, dict) else None
    if ignored:
        print(f"[주의] run_id={run_id} 에서 이미 있는 alert_id라 무시됨: {ignored}", flush=True)


def deliver(client, kind: str, payload: dict, line: str, run_id: str, attempts: int = 3, pause: float = 0.5) -> bool:
    """연결 실패면 3회까지 다시 보내고, 그래도 안 되면 실패 줄로 남긴다."""
    path = "/ingest/detections" if kind == "detections" else "/ingest/alerts"
    for attempt in range(1, attempts + 1):
        try:
            response = client.post(path, params={"run_id": run_id}, json=payload)
            if response.status_code < 400:
                if kind == "alerts":
                    warn_ignored_alerts(response, run_id)
                return True
            if response.status_code < 500:
                break
        except httpx.HTTPError:
            pass
        if attempt < attempts and pause:
            time.sleep(pause)
    append_failed(run_id, kind, line)
    print(f"전송 실패, 기록함: {kind} {failed_log_path(run_id).name}", flush=True)
    return False


def progress_line(kind: str, payload: dict) -> str:
    if kind == "detections":
        boxes = payload.get("detections") or []
        return f"[검출] frame={payload.get('frame')} boxes={len(boxes)}"
    return f"[경고] {payload.get('type')} {payload.get('message', '')}".rstrip()


def publish_line(client, kind: str, line: str, run_id: str, attempts: int = 3, pause: float = 0.5,
                 checked: set[str] | None = None) -> None:
    if checked is None:
        checked = set()
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        print(f"JSON 해석 실패: {line[:80]}", flush=True)
        append_failed(run_id, kind, line)
        return
    if not isinstance(payload, dict):
        append_failed(run_id, kind, line)
        return
    camera_id = payload.get("camera_id")
    warn_missing_camera(client, str(camera_id) if camera_id else None, checked)
    if deliver(client, kind, payload, line, run_id, attempts=attempts, pause=pause):
        print(progress_line(kind, payload), flush=True)


def publish_available(run_dir: Path, detections: TailReader, alerts: TailReader, client, run_id: str,
                      attempts: int = 3, pause: float = 0.5, checked: set[str] | None = None) -> bool:
    """새로 생긴 줄을 보낸다. 실행이 끝났으면 True."""
    if checked is None:
        checked = set()
    pairs = (("detections", detections), ("alerts", alerts))
    for kind, reader in pairs:
        for line in reader.read_lines():
            publish_line(client, kind, line, run_id, attempts=attempts, pause=pause, checked=checked)
    if not (run_dir / "summary.json").is_file():
        return False
    extra = False
    for kind, reader in pairs:
        lines = reader.read_lines()
        extra = extra or bool(lines)
        for line in lines:
            publish_line(client, kind, line, run_id, attempts=attempts, pause=pause, checked=checked)
    if extra or detections.pending or alerts.pending:
        return False
    print("실행 종료", flush=True)
    return True


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="검출 jsonl을 따라 API로 보냅니다")
    parser.add_argument("--run-dir", required=True, help="검출 출력 폴더")
    parser.add_argument("--api", default="http://localhost:8000", help="API 주소")
    parser.add_argument("--run-id", default=None, help="실행 ID. 기본값은 폴더 이름")
    parser.add_argument("--poll", type=float, default=0.5, help="확인 간격(초)")
    parser.add_argument("--from-start", action=argparse.BooleanOptionalAction, default=True,
                        help="처음부터 읽는다. --no-from-start면 지금 이후 줄만")
    args = parser.parse_args()
    if args.poll <= 0:
        parser.error("--poll은 0보다 커야 합니다")
    run_dir = Path(args.run_dir)
    if not run_dir.is_dir():
        print(f"폴더가 없습니다: {run_dir}", file=sys.stderr)
        return 1
    run_id = args.run_id or run_dir.name
    detections = TailReader(run_dir / "detections.jsonl", from_start=args.from_start)
    alerts = TailReader(run_dir / "alerts.jsonl", from_start=args.from_start)
    api = args.api.rstrip("/")
    try:
        with httpx.Client(base_url=api, timeout=30.0) as client:
            checked: set[str] = set()
            while True:
                if publish_available(run_dir, detections, alerts, client, run_id, checked=checked):
                    return 0
                time.sleep(args.poll)
    except KeyboardInterrupt:
        print("\n따라 읽기를 중단했습니다.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
