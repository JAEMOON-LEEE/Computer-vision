"""replay_jsonl의 시각 덮어쓰기, 경고 생략, 주의 출력을 확인한다."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx


def load_replay():
    path = Path(__file__).resolve().parents[1] / "scripts" / "replay_jsonl.py"
    spec = importlib.util.spec_from_file_location("replay_jsonl", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self.payload = {} if payload is None else payload
        self.text = text

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self, get_status=200, get_error=None, alert_payload=None):
        self.posts = []
        self.gets = []
        self.get_status = get_status
        self.get_error = get_error
        self.alert_payload = {"ignored": []} if alert_payload is None else alert_payload

    def get(self, path):
        self.gets.append(path)
        if self.get_error is not None:
            raise self.get_error
        return FakeResponse(self.get_status)

    def post(self, path, params=None, json=None):
        self.posts.append((path, params, json))
        payload = self.alert_payload if path == "/ingest/alerts" else {}
        return FakeResponse(200, payload)


def detection(frame=1, timestamp=10.0, kind="video_seconds", camera="cam-a"):
    return {
        "camera_id": camera,
        "frame": frame,
        "timestamp": timestamp,
        "timestamp_kind": kind,
        "width": 100,
        "height": 80,
        "detections": [],
    }


def alert(timestamp=12.0, camera="cam-a", alert_id="cam-a:1"):
    return {
        "alert_id": alert_id,
        "camera_id": camera,
        "frame": 2,
        "timestamp": timestamp,
        "type": "road_damage",
        "severity": "warning",
        "status": "unconfirmed",
        "message": "포트홀",
        "evidence": [],
        "basis": "visual_detections_and_motion",
    }


def test_stamp_now_rewrites_detection_and_alert_timestamps(monkeypatch, capsys):
    replay = load_replay()
    sleeps = []
    monkeypatch.setattr(replay.time, "sleep", lambda gap: sleeps.append(gap))
    clock = {"t": 1000.0}

    def now():
        clock["t"] += 5
        return clock["t"]

    monkeypatch.setattr(replay.time, "time", now)
    det = detection()
    al = alert()
    events = [(10.0, 0, "detections", det), (12.0, 1, "alerts", al)]
    client = FakeClient()
    detections, alerts = replay.play_once(client, events, "run-1", 1.0, True)
    assert (detections, alerts) == (1, 1)
    assert sleeps == [2.0]
    assert client.posts[0][0] == "/ingest/detections"
    assert client.posts[0][2]["timestamp"] == 1005.0
    assert client.posts[0][2]["timestamp_kind"] == "unix_seconds"
    assert client.posts[1][0] == "/ingest/alerts"
    assert client.posts[1][2]["timestamp"] == 1010.0
    assert det["timestamp"] == 10.0
    assert al["timestamp"] == 12.0
    assert "t=1010.0" in capsys.readouterr().out


def test_skip_alerts_keeps_file_timestamp_gaps(monkeypatch):
    replay = load_replay()
    sleeps = []
    monkeypatch.setattr(replay.time, "sleep", lambda gap: sleeps.append(gap))
    events = [(10.0, 0, "detections", detection()), (12.0, 1, "alerts", alert())]
    client = FakeClient()
    detections, alerts = replay.play_once(client, events, "run-1", 1.0, False, send_alerts=False)
    assert (detections, alerts) == (1, 0)
    assert sleeps == [2.0]
    assert [item[0] for item in client.posts] == ["/ingest/detections"]


def test_non_unix_timestamp_kind_warns_once(monkeypatch, capsys):
    replay = load_replay()
    monkeypatch.setattr(replay.time, "sleep", lambda gap: None)
    events = [
        (1.0, 0, "detections", detection(kind="video_seconds")),
        (2.0, 1, "detections", detection(frame=2, timestamp=2.0, kind="video_seconds")),
    ]
    replay.play_once(FakeClient(), events, "run-1", 1.0, False)
    assert capsys.readouterr().out.count("timestamp_kind=video_seconds") == 1


def test_unix_timestamp_kind_stays_quiet(monkeypatch, capsys):
    replay = load_replay()
    monkeypatch.setattr(replay.time, "sleep", lambda gap: None)
    events = [(1.0, 0, "detections", detection(kind="unix_seconds"))]
    replay.play_once(FakeClient(), events, "run-1", 1.0, False)
    assert "timestamp_kind=" not in capsys.readouterr().out


def test_missing_camera_warns_once_and_still_sends(monkeypatch, capsys):
    replay = load_replay()
    monkeypatch.setattr(replay.time, "sleep", lambda gap: None)
    events = [
        (1.0, 0, "detections", detection(kind="unix_seconds")),
        (2.0, 1, "detections", detection(frame=2, timestamp=2.0, kind="unix_seconds")),
    ]
    client = FakeClient(get_status=404)
    replay.play_once(client, events, "run-1", 1.0, False)
    out = capsys.readouterr().out
    assert out.count("카메라 목록에 없는 camera_id: cam-a") == 1
    assert client.gets == ["/cameras/cam-a"]
    assert len(client.posts) == 2


def test_camera_check_failure_still_sends(monkeypatch):
    replay = load_replay()
    monkeypatch.setattr(replay.time, "sleep", lambda gap: None)
    client = FakeClient(get_error=httpx.ConnectError("down"))
    detections, _alerts = replay.play_once(
        client,
        [(1.0, 0, "detections", detection(kind="unix_seconds"))],
        "run-1",
        1.0,
        False,
    )
    assert detections == 1
    assert len(client.posts) == 1


def test_ignored_alert_ids_are_printed(monkeypatch, capsys):
    replay = load_replay()
    monkeypatch.setattr(replay.time, "sleep", lambda gap: None)
    client = FakeClient(alert_payload={"ignored": ["cam-a:1"]})
    replay.play_once(client, [(1.0, 0, "alerts", alert(timestamp=1.0))], "run-1", 1.0, True)
    assert "run_id=run-1 에서 이미 있는 alert_id라 무시됨: ['cam-a:1']" in capsys.readouterr().out


def _loop_posts(replay, monkeypatch, tmp_path, extra_args):
    det_path = tmp_path / "detections.jsonl"
    alert_path = tmp_path / "alerts.jsonl"
    det_path.write_text(json.dumps(detection(kind="unix_seconds"), ensure_ascii=False) + "\n", encoding="utf-8")
    alert_path.write_text(json.dumps(alert(), ensure_ascii=False) + "\n", encoding="utf-8")
    posts = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path):
            return FakeResponse()

        def post(self, path, params=None, json=None):
            posts.append((path, params["run_id"]))
            return FakeResponse(payload={"ignored": []})

    calls = {"n": 0}
    real = replay.play_once

    def wrapped(*args, **kwargs):
        result = real(*args, **kwargs)
        calls["n"] += 1
        if calls["n"] >= 2:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(replay.httpx, "Client", Client)
    monkeypatch.setattr(replay.time, "sleep", lambda *_args: None)
    monkeypatch.setattr(replay.time, "time", lambda: 50.0)
    monkeypatch.setattr(replay, "play_once", wrapped)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "replay_jsonl.py",
            "--detections",
            str(det_path),
            "--alerts",
            str(alert_path),
            "--run-id",
            "demo",
            "--loop",
            *extra_args,
        ],
    )
    assert replay.main() == 0
    return posts


def test_alerts_first_loop_only_skips_later_alerts(monkeypatch, tmp_path):
    replay = load_replay()
    posts = _loop_posts(replay, monkeypatch, tmp_path, ["--alerts-first-loop-only"])
    assert [item for item in posts if item[0] == "/ingest/alerts"] == [("/ingest/alerts", "demo-1")]
    assert [item for item in posts if item[0] == "/ingest/detections"] == [
        ("/ingest/detections", "demo-1"),
        ("/ingest/detections", "demo-2"),
    ]


def test_loop_sends_alerts_every_pass_by_default(monkeypatch, tmp_path):
    replay = load_replay()
    posts = _loop_posts(replay, monkeypatch, tmp_path, [])
    assert [item for item in posts if item[0] == "/ingest/alerts"] == [
        ("/ingest/alerts", "demo-1"),
        ("/ingest/alerts", "demo-2"),
    ]
