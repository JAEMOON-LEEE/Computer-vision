import time

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.team_auth import COOKIE, TeamAuth, session

SECRET = "test-access-token-" + "x" * 40
ORIGIN = "https://team.example"


@pytest.fixture
def protected(monkeypatch):
    monkeypatch.setenv("TEAM_ACCESS_TOKEN", SECRET)
    monkeypatch.setenv("DEPLOYMENT_MODE", "cloud")
    monkeypatch.setenv("PUBLIC_BASE_URL", ORIGIN)
    app = FastAPI()
    app.add_middleware(TeamAuth)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/dashboard/")
    @app.get("/cameras")
    @app.post("/ingest")
    def private():
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(socket: WebSocket):
        await socket.accept()
        await socket.send_text("connected")
        await socket.close()

    with TestClient(app, base_url=ORIGIN) as client:
        yield client


def test_anonymous_access_and_bearer(protected):
    assert protected.get("/health").status_code == 200
    assert protected.get("/cameras").status_code == 401
    assert protected.get("/dashboard/", follow_redirects=False).headers["location"] == "/login"
    assert protected.post("/ingest", headers={"Authorization": "Bearer " + SECRET}).status_code == 200
    assert protected.post("/ingest", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_login_cookie_csrf_and_logout(protected):
    assert protected.post("/login", data={"token": SECRET}).status_code == 403
    assert protected.post("/login", data={"token": "wrong"}, headers={"Origin": ORIGIN}).status_code == 401
    login = protected.post("/login", data={"token": SECRET}, headers={"Origin": ORIGIN}, follow_redirects=False)
    assert login.status_code == 303
    assert "Secure" in login.headers["set-cookie"]
    assert "HttpOnly" in login.headers["set-cookie"]
    assert SECRET not in login.headers["set-cookie"]
    assert protected.get("/dashboard/").status_code == 200
    assert protected.post("/ingest", headers={"Origin": "https://evil.example"}).status_code == 403
    assert protected.post("/ingest", headers={"Origin": ORIGIN}).status_code == 200
    assert protected.post("/logout", headers={"Origin": ORIGIN}, follow_redirects=False).status_code == 303
    assert protected.get("/cameras").status_code == 401


def test_forged_and_expired_sessions(protected):
    for value in [session(SECRET, int(time.time()) - 1), session("wrong", int(time.time()) + 100)]:
        protected.cookies.set(COOKIE, value)
        assert protected.get("/cameras").status_code == 401


def test_websocket_auth_and_origin(protected):
    with pytest.raises(WebSocketDisconnect):
        with protected.websocket_connect("/ws"):
            pass
    with protected.websocket_connect("/ws", headers={"Authorization": "Bearer " + SECRET}) as ws:
        assert ws.receive_text() == "connected"
    protected.post("/login", data={"token": SECRET}, headers={"Origin": ORIGIN})
    with pytest.raises(WebSocketDisconnect):
        with protected.websocket_connect("wss://team.example/ws", headers={"Origin": "https://evil.example"}):
            pass
    with protected.websocket_connect("wss://team.example/ws", headers={"Origin": ORIGIN}) as ws:
        assert ws.receive_text() == "connected"


def test_cloud_requires_strong_token(monkeypatch):
    monkeypatch.setenv("DEPLOYMENT_MODE", "cloud")
    monkeypatch.delenv("TEAM_ACCESS_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TEAM_ACCESS_TOKEN"):
        TeamAuth(FastAPI())


def test_supabase_url_driver(monkeypatch):
    from backend.app.config import database_url
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres.ref:encoded%40secret@pooler.example:5432/postgres?sslmode=require")
    url = database_url()
    assert url.drivername == "postgresql+psycopg"
    assert url.password == "encoded@secret"
    assert url.query["sslmode"] == "require"


def test_managed_database_requires_token(monkeypatch):
    monkeypatch.setenv("DATABASE_SCHEMA", "twinsight")
    monkeypatch.delenv("DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("TEAM_ACCESS_TOKEN", "")
    with pytest.raises(RuntimeError, match="TEAM_ACCESS_TOKEN"):
        TeamAuth(FastAPI())
