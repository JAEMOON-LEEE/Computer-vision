"""TwinSight FastAPI 앱.

저장소 루트에서 실행한다.
    .\\.venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import logging

from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from backend.app.team_auth import TeamAuth

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.db import init_db
from backend.app.routers import alerts, cameras, database, detections, ingest, ws


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="TwinSight API",
    description=(
        "CCTV 검출·경고를 저장하고 관제 화면으로 전달한다. "
        "데이터베이스는 저장소 루트 .env의 DATABASE_URL로 교체한다."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(TeamAuth)

app.include_router(database.router)
app.include_router(cameras.router)
app.include_router(detections.router)
app.include_router(ingest.router)
app.include_router(alerts.router)
app.include_router(ws.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


# Same-origin API for the built dashboard and Vite proxy; preserve existing clients.
for router in (cameras.router, detections.router, ingest.router, alerts.router, ws.router, database.router):
    app.include_router(router, prefix="/api")


@app.exception_handler(SQLAlchemyError)
async def database_error(_request, exc):
    logging.getLogger(__name__).error("Database operation failed: %s", type(exc).__name__)
    return JSONResponse({"detail": "DB 요청에 실패했습니다. 연결 상태를 확인하고 다시 시도하세요."}, status_code=503)


DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if (DIST / "assets").is_dir():
    app.mount("/dashboard/assets", StaticFiles(directory=DIST / "assets"), name="dashboard-assets")


@app.get("/", include_in_schema=False)
def home():
    return RedirectResponse("/dashboard/")


@app.get("/dashboard", include_in_schema=False)
@app.get("/dashboard/", include_in_schema=False)
@app.get("/dashboard/{route:path}", include_in_schema=False)
def dashboard(route: str = ""):
    if route not in ("", "history", "analysis", "database"):
        return JSONResponse({"detail": "페이지를 찾을 수 없습니다"}, status_code=404)
    if not (DIST / "index.html").is_file():
        return JSONResponse({"detail": "frontend에서 npm ci와 npm run build를 먼저 실행하세요"}, status_code=503)
    return FileResponse(DIST / "index.html", headers={"Cache-Control": "no-cache"})
