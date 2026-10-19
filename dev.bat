@echo off
rem TwinSight dev launcher: backend + frontend + mock replay in 3 windows
rem Usage: double-click dev.bat, or run "dev.bat nomock" to skip mock replay
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe
set CAM=its-cc4277cc18
set MOCK=backend\data\mock\%CAM%

if not exist "%PY%" (
  echo [ERROR] .venv not found. Run: python -m venv .venv
  pause
  exit /b 1
)

echo [1/3] Backend  http://localhost:8000/docs
start "TwinSight API" cmd /k "cd /d "%~dp0" && %PY% -m uvicorn backend.app.main:app --reload"

if exist "frontend\package.json" (
  if not exist "frontend\node_modules" (
    echo     installing frontend packages first...
    pushd frontend
    call npm install
    popd
  )
  echo [2/3] Frontend http://localhost:5173
  start "TwinSight Web" cmd /k "cd /d "%~dp0frontend" && npm run dev"
) else (
  echo [2/3] frontend\package.json 이 없습니다
)

if /i "%1"=="nomock" (
  echo [3/3] mock replay skipped
  goto open
)

rem wait for the backend to come up before replaying
timeout /t 5 /nobreak >nul

if not exist "%MOCK%\detections.jsonl" (
  if exist "backend\scripts\make_mock_detections.py" (
    echo     generating mock detections for %CAM%...
    %PY% backend\scripts\make_mock_detections.py --camera-id %CAM%
  )
)

if exist "%MOCK%\detections.jsonl" (
  echo [3/3] Mock replay for %CAM% (loop)
  start "TwinSight Mock" cmd /k "cd /d "%~dp0" && %PY% backend\scripts\replay_jsonl.py --detections %MOCK%\detections.jsonl --alerts %MOCK%\alerts.jsonl --speed 1 --loop --stamp-now"
) else (
  echo [3/3] mock data not found - skipped
)

:open
timeout /t 3 /nobreak >nul
if exist "frontend\package.json" (start "" http://localhost:5173) else (start "" http://localhost:8000/docs)
echo.
echo Done. Close each window (or Ctrl+C in it) to stop.
