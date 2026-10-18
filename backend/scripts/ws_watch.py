"""WebSocket으로 들어오는 검출·경고를 한 줄씩 보여 준다.

예 (저장소 루트, 서버가 떠 있을 때):
    .\\.venv\\Scripts\\python.exe backend\\scripts\\ws_watch.py
    .\\.venv\\Scripts\\python.exe backend\\scripts\\ws_watch.py --raw
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter

import websockets


def format_event(message: dict) -> str:
    kind = message.get("type")
    if kind == "detections":
        frame = message.get("frame") or {}
        boxes = frame.get("detections") or []
        counts = Counter(item.get("class_name") or "?" for item in boxes)
        summary = ", ".join(f"{name} {count}" for name, count in counts.items()) or "-"
        return f"[검출] {message.get('camera_id')} / {message.get('run_id')} / {frame.get('frame')} / {len(boxes)} / {summary}"
    if kind == "alert":
        alert = message.get("alert") or {}
        return f"[경고] {alert.get('id')} / {alert.get('type')} / {alert.get('camera_id')} / {alert.get('message')}"
    if kind == "alert_updated":
        alert = message.get("alert") or {}
        handled = alert.get("handled_by") or "-"
        return f"[변경] {alert.get('id')} / {alert.get('status')} / {handled}"
    return json.dumps(message, ensure_ascii=False)


async def watch(url: str, raw: bool) -> None:
    while True:
        try:
            async with websockets.connect(url) as socket:
                print(f"연결됨 {url}", flush=True)
                async for incoming in socket:
                    text = incoming if isinstance(incoming, str) else incoming.decode("utf-8")
                    if raw:
                        print(text, flush=True)
                        continue
                    try:
                        message = json.loads(text)
                    except json.JSONDecodeError:
                        print(text, flush=True)
                        continue
                    print(format_event(message) if isinstance(message, dict) else text, flush=True)
        except (websockets.ConnectionClosed, OSError, websockets.WebSocketException) as exc:
            print(f"연결이 끊겼습니다 ({exc}). 3초 후 재접속합니다.", flush=True)
            await asyncio.sleep(3)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="TwinSight WebSocket 이벤트를 출력합니다")
    parser.add_argument("--url", default="ws://localhost:8000/ws", help="WebSocket 주소")
    parser.add_argument("--raw", action="store_true", help="JSON 원문을 출력한다")
    args = parser.parse_args()
    try:
        asyncio.run(watch(args.url, args.raw))
    except KeyboardInterrupt:
        print("\n감시를 중단했습니다.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
