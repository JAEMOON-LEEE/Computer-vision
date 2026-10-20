"""follow_detections의 줄 읽기, 미완성 줄 보류, 종료 판단을 확인한다."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx


def load_follow():
    path = Path(__file__).resolve().parents[1] / "scripts" / "follow_detections.py"
    spec = importlib.util.spec_from_file_location("follow_detections", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code


class FakeClient:
    def __init__(self):
        self.posts = []

    def post(self, path, params=None, json=None):
        self.posts.append((path, params, json))
        return FakeResponse()


class DownClient:
    def __init__(self, succeed_on=None):
        self.calls = 0
        self.succeed_on = succeed_on

    def post(self, path, params=None, json=None):
        self.calls += 1
        if self.succeed_on is not None and self.calls >= self.succeed_on:
            return FakeResponse()
        raise httpx.ConnectError("down")


def detection_line(frame=12, boxes=1):
    body = {
        "camera_id": "cam",
        "frame": frame,
        "timestamp": 1.0,
        "timestamp_kind": "unix_seconds",
        "width": 100,
        "height": 80,
        "inference_ms": 3.0,
        "detections": [
            {
                "class_name": "car",
                "class_id": 2,
                "category_id": 1,
                "model_id": "primary",
                "bbox_xyxy": [0, 0, 1, 1],
                "confidence": 0.5,
                "track_id": 1,
                "ground_point_px": [0.5, 1],
            }
            for _ in range(boxes)
        ],
    }
    return json.dumps(body, ensure_ascii=False)


def test_tail_holds_partial_line(tmp_path):
    follow = load_follow()
    path = tmp_path / "detections.jsonl"
    path.write_bytes("{\"frame\": 1}".encode())
    reader = follow.TailReader(path, from_start=True)
    assert reader.read_lines() == []
    assert reader.pending.startswith("{")

    with path.open("ab") as handle:
        handle.write(b"\n{\"frame\": 2}\n{\"frame\": 3}")
    assert reader.read_lines() == ['{"frame": 1}', '{"frame": 2}']
    assert reader.pending == '{"frame": 3}'
    assert reader.read_lines() == []

    with path.open("ab") as handle:
        handle.write(b"\n")
    assert reader.read_lines() == ['{"frame": 3}']
    assert reader.pending == ""


def test_tail_from_start_false_skips_existing(tmp_path):
    follow = load_follow()
    path = tmp_path / "detections.jsonl"
    path.write_text('{"frame": 1}\n{"frame": 2}\n', encoding="utf-8")
    reader = follow.TailReader(path, from_start=False)
    assert reader.read_lines() == []
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"frame": 3}\n')
    assert reader.read_lines() == ['{"frame": 3}']


def test_publish_waits_for_summary_and_partial_line(tmp_path):
    follow = load_follow()
    run_dir = tmp_path / "run-a"
    run_dir.mkdir()
    detections_path = run_dir / "detections.jsonl"
    detections_path.write_bytes((detection_line(frame=12, boxes=3) + "\n").encode())
    client = FakeClient()
    detections = follow.TailReader(detections_path)
    alerts = follow.TailReader(run_dir / "alerts.jsonl")

    assert follow.publish_available(run_dir, detections, alerts, client, "run-a", pause=0) is False
    assert client.posts[0][0] == "/ingest/detections"
    assert client.posts[0][1] == {"run_id": "run-a"}
    assert client.posts[0][2]["frame"] == 12
    assert len(client.posts[0][2]["detections"]) == 3

    with detections_path.open("ab") as handle:
        handle.write(b'{"frame":')
    (run_dir / "summary.json").write_text("{}", encoding="utf-8")
    assert follow.publish_available(run_dir, detections, alerts, client, "run-a", pause=0) is False

    with detections_path.open("ab") as handle:
        handle.write(b"99}\n")
    (run_dir / "alerts.jsonl").write_bytes(
        (json.dumps({"alert_id": "cam:1", "type": "road_damage", "message": "포트홀"}, ensure_ascii=False) + "\n").encode()
    )
    assert follow.publish_available(run_dir, detections, alerts, client, "run-a", pause=0) is True
    kinds = [item[0] for item in client.posts]
    assert "/ingest/alerts" in kinds
    alert = next(item[2] for item in client.posts if item[0] == "/ingest/alerts")
    assert alert["type"] == "road_damage"


def test_unknown_camera_is_warned_once(capsys):
    follow = load_follow()

    class Client(FakeClient):
        def __init__(self):
            super().__init__()
            self.gets = []

        def get(self, path):
            self.gets.append(path)
            return FakeResponse(404)

    client = Client()
    checked: set[str] = set()
    follow.publish_line(client, "detections", detection_line(frame=1), "run-a", pause=0, checked=checked)
    follow.publish_line(client, "detections", detection_line(frame=2), "run-a", pause=0, checked=checked)
    out = capsys.readouterr().out
    assert out.count("카메라 목록에 없는 camera_id: cam") == 1
    assert client.gets == ["/cameras/cam"]
    assert len(client.posts) == 2


def test_camera_check_failure_still_publishes():
    follow = load_follow()

    class Client(FakeClient):
        def get(self, path):
            raise httpx.ConnectError("down")

    client = Client()
    follow.publish_line(client, "detections", detection_line(), "run-a", pause=0)
    assert client.posts[0][0] == "/ingest/detections"


def test_ignored_alert_ids_are_printed(capsys):
    follow = load_follow()

    class Response(FakeResponse):
        def json(self):
            return {"ignored": ["cam:1"]}

    class Client(FakeClient):
        def get(self, path):
            return FakeResponse()

        def post(self, path, params=None, json=None):
            self.posts.append((path, params, json))
            return Response()

    line = json.dumps({"alert_id": "cam:1", "camera_id": "cam", "type": "road_damage"}, ensure_ascii=False)
    follow.publish_line(Client(), "alerts", line, "run-a", pause=0)
    assert "run_id=run-a 에서 이미 있는 alert_id라 무시됨: ['cam:1']" in capsys.readouterr().out


def test_deliver_retries_then_records_failure(tmp_path, monkeypatch, capsys):
    follow = load_follow()
    monkeypatch.setattr(follow, "REPO_ROOT", tmp_path)
    flaky = DownClient(succeed_on=3)
    line = detection_line()
    assert follow.deliver(flaky, "detections", json.loads(line), line, "demo", attempts=3, pause=0) is True
    assert flaky.calls == 3

    down = DownClient()
    assert follow.deliver(down, "alerts", {"type": "road_damage"}, "{\"type\": \"road_damage\"}", "demo", attempts=3, pause=0) is False
    assert down.calls == 3
    failed = (tmp_path / "backend" / "data" / "failed_demo.jsonl").read_text(encoding="utf-8")
    saved = json.loads(failed.strip())
    assert saved["kind"] == "alerts"
    assert "road_damage" in saved["line"]
    assert "전송 실패" in capsys.readouterr().out
