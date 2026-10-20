"""TwinSight FastAPI 앱.

저장소 루트에서 실행한다.
    .\\.venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db import init_db, get_db
from backend.app.routers import alerts, cameras, catalog, history, ingest, ws


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
    allow_origins=[value.strip() for value in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if value.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(cameras.router)
app.include_router(ingest.router)
app.include_router(alerts.router)
app.include_router(ws.router)
app.include_router(history.router)
app.include_router(catalog.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok", "database": "connected"}


@app.get("/", include_in_schema=False)
def dashboard_redirect():
    return RedirectResponse("/dashboard/")


app.mount("/dashboard", StaticFiles(directory=Path(__file__).resolve().parents[2] / "frontend", html=True), name="dashboard")
