"""Shared team login for the hosted prototype, including WebSocket protection.

The same high-entropy secret is used as a machine-client Bearer token.
This is shared access, not per-user authorization or a replacement for Supabase Auth.
"""
import hashlib
import hmac
from http.cookies import SimpleCookie
import os
import time
from urllib.parse import parse_qs, urlsplit

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

COOKIE = "twinsight_session"
LIFETIME = 12 * 60 * 60
LOGIN = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>TwinSight 팀 로그인</title>
<body style="background:#101827;color:#eee;font:16px system-ui;max-width:420px;margin:12vh auto;padding:24px">
<h1>TwinSight</h1><p>팀에서 전달받은 접속 키를 입력하세요.</p>
<form method="post" action="/login">
<label>팀 접속 키 <input name="token" type="password" required autocomplete="current-password"
style="width:100%;box-sizing:border-box;padding:12px;margin:16px 0"></label>
<button style="padding:12px" type="submit">대시보드 열기</button></form></body></html>"""


def session(secret, expires):
    payload = str(expires)
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return payload + "." + sig


def valid_cookie(secret, value):
    try:
        expires = int(value.split(".", 1)[0])
        return int(time.time()) < expires <= int(time.time()) + LIFETIME and hmac.compare_digest(
            value, session(secret, expires))
    except (ValueError, TypeError):
        return False


class TeamAuth:
    def __init__(self, app):
        self.app = app
        self.secret = os.getenv("TEAM_ACCESS_TOKEN", "")
        self.cloud = os.getenv("DEPLOYMENT_MODE") == "cloud"
        if (self.cloud or self.secret or os.getenv("DATABASE_SCHEMA")) and len(self.secret) < 32:
            raise RuntimeError("TEAM_ACCESS_TOKEN must contain at least 32 characters")
        self.public_url = os.getenv("PUBLIC_BASE_URL") or os.getenv("RENDER_EXTERNAL_URL")

    async def __call__(self, scope, receive, send):
        kind, path = scope["type"], scope.get("path", "")
        if kind not in ("http", "websocket") or not self.secret:
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        origin = headers.get(b"origin", b"").decode()
        if self.public_url:
            target = urlsplit(self.public_url)
            expected_origin = f"{target.scheme}://{target.netloc}"
        else:
            scheme = "https" if self.cloud or scope["scheme"] in ("https", "wss") else "http"
            expected_origin = scheme + "://" + headers.get(b"host", b"").decode()
        same_origin = origin == expected_origin
        auth = headers.get(b"authorization", b"").decode()
        bearer = hmac.compare_digest(auth.encode(), ("Bearer " + self.secret).encode())
        cookies = SimpleCookie()
        try:
            cookies.load(headers.get(b"cookie", b"").decode())
            value = cookies[COOKIE].value if COOKIE in cookies else ""
        except Exception:
            value = ""
        cookie_ok = valid_cookie(self.secret, value)

        if kind == "websocket":
            if not bearer and not (cookie_ok and same_origin):
                return await send({"type": "websocket.close", "code": 1008})
            return await self.app(scope, receive, send)
        method = scope["method"]
        if path in ("/health", "/ready") and method in ("GET", "HEAD"):
            return await self.app(scope, receive, send)
        if path == "/login" and method == "GET":
            return await HTMLResponse(LOGIN, headers={"Cache-Control": "no-store"})(scope, receive, send)
        if path == "/login" and method == "POST":
            if not same_origin:
                return await JSONResponse({"detail": "Invalid origin"}, status_code=403)(scope, receive, send)
            request = Request(scope, receive)
            body = b""
            async for chunk in request.stream():
                body += chunk
                if len(body) > 4096:
                    return await JSONResponse({"detail": "Too large"}, status_code=413)(scope, receive, send)
            supplied = parse_qs(body.decode(errors="replace")).get("token", [""])[0]
            if not hmac.compare_digest(supplied.encode(), self.secret.encode()):
                return await HTMLResponse(LOGIN, status_code=401, headers={"Cache-Control": "no-store"})(scope, receive, send)
            response = RedirectResponse("/dashboard/", status_code=303)
            response.headers["Cache-Control"] = "no-store"
            response.set_cookie(COOKIE, session(self.secret, int(time.time()) + LIFETIME),
                                max_age=LIFETIME, httponly=True, secure=self.cloud or scope["scheme"] == "https", samesite="strict")
            return await response(scope, receive, send)
        if not bearer and not cookie_ok:
            response = (RedirectResponse("/login", status_code=303)
                        if method == "GET" and (path == "/" or path.startswith(("/dashboard", "/docs", "/redoc")))
                        else JSONResponse({"detail": "Team authentication required"}, status_code=401))
            return await response(scope, receive, send)
        if not bearer and method not in ("GET", "HEAD", "OPTIONS") and not same_origin:
            return await JSONResponse({"detail": "Invalid origin"}, status_code=403)(scope, receive, send)
        if path == "/logout" and method == "POST":
            response = RedirectResponse("/login", status_code=303)
            response.delete_cookie(COOKIE, secure=self.cloud or scope["scheme"] == "https", httponly=True, samesite="strict")
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)
