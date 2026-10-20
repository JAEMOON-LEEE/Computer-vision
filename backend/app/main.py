"""TwinSight FastAPI 앱.

저장소 루트에서 실행한다.
    .\\.venv\\Scripts\\python.exe -m uvicorn backend.app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.db import init_db
from backend.app.routers import alerts, cameras, detections, ingest, ws


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

app.include_router(cameras.router)
app.include_router(detections.router)
app.include_router(ingest.router)
app.include_router(alerts.router)
app.include_router(ws.router)


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok"}
