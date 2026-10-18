"""detections.jsonl과 alerts.jsonl을 시간 순으로 API에 다시 넣는다.

예 (저장소 루트):
    .\\.venv\\Scripts\\python.exe backend\\scripts\\replay_jsonl.py --alerts docs\\validation\\pothole-alert.jsonl --speed 5
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def load_events(path: str | None, kind: str, seq_start: int) -> tuple[list[tuple], int]:
    if not path:
        return [], seq_start
    file_path = Path(path)
    if not file_path.is_file():
        raise SystemExit(f"파일이 없습니다: {file_path}")
    events: list[tuple] = []
    seq = seq_start
    with file_path.open(encoding="utf-8-sig") as handle:
        for line_no, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                body = json.loads(text)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{file_path}:{line_no} JSON 해석 실패: {exc}") from exc
            if "timestamp" not in body:
                raise SystemExit(f"{file_path}:{line_no} 에 timestamp가 없습니다")
            events.append((float(body["timestamp"]), seq, kind, body))
            seq += 1
    return events, seq


def default_run_id(detections: str | None, alerts: str | None) -> str:
    """입력 파일이 있는 폴더 이름. 검출 파일을 우선한다."""
    source = Path(detections or alerts).resolve()
    return source.parent.name or "replay"


def play_once(client: httpx.Client, events: list[tuple], run_id: str, speed: float) -> tuple[int, int]:
    previous: float | None = None
    detections = alerts = 0
    for timestamp, _seq, kind, body in events:
        if previous is not None:
            gap = (timestamp - previous) / speed
            if gap > 0:
                time.sleep(gap)
        previous = timestamp
        path = "/ingest/detections" if kind == "detections" else "/ingest/alerts"
        response = client.post(path, params={"run_id": run_id}, json=body)
        if response.status_code >= 400:
            raise SystemExit(f"{path} 실패 ({response.status_code}): {response.text}")
        if kind == "detections":
            detections += 1
            print(f"[검출] run={run_id} frame={body.get('frame')} t={timestamp}", flush=True)
        else:
            alerts += 1
            print(f"[경고] run={run_id} {body.get('alert_id')} {body.get('type')}", flush=True)
    return detections, alerts


def main() -> int:
    parser = argparse.ArgumentParser(description="검출·경고 JSONL을 TwinSight API로 재생합니다")
    parser.add_argument("--detections", help="detections.jsonl 경로")
    parser.add_argument("--alerts", help="alerts.jsonl 경로")
    parser.add_argument("--api", default="http://localhost:8000", help="API 주소")
    parser.add_argument("--run-id", default=None, help="실행 ID. 기본값은 입력 폴더 이름")
    parser.add_argument("--speed", type=float, default=1.0, help="1이면 기록된 시간 간격 그대로")
    parser.add_argument("--loop", action="store_true", help="반복할 때마다 run_id 뒤에 -1, -2를 붙인다")
    args = parser.parse_args()

    if not args.detections and not args.alerts:
        parser.error("--detections 또는 --alerts 중 하나 이상이 필요합니다")
    if args.speed <= 0:
        parser.error("--speed는 0보다 커야 합니다")

    base_run_id = args.run_id or default_run_id(args.detections, args.alerts)
    events, _seq = load_events(args.detections, "detections", 0)
    alert_events, _seq = load_events(args.alerts, "alerts", len(events))
    events.extend(alert_events)
    events.sort(key=lambda item: (item[0], item[1]))
    if not events:
        raise SystemExit("재생할 레코드가 없습니다")

    api = args.api.rstrip("/")
    try:
        with httpx.Client(base_url=api, timeout=30.0) as client:
            iteration = 0
            while True:
                iteration += 1
                run_id = f"{base_run_id}-{iteration}" if args.loop else base_run_id
                detections, alerts = play_once(client, events, run_id, args.speed)
                print(f"재생 완료 run={run_id} 검출 {detections}건, 경고 {alerts}건", flush=True)
                if not args.loop:
                    break
    except KeyboardInterrupt:
        print("\n재생을 중단했습니다.", flush=True)
        return 0
    except httpx.HTTPError as exc:
        print(f"API에 연결하지 못했습니다: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
