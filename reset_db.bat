@echo off
rem Delete the temporary SQLite file the backend actually uses, plus its -wal and -shm.
cd /d "%~dp0"

set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  echo [ERROR] .venv not found. Run: python -m venv .venv
  exit /b 1
)

"%PY%" -c "import sys; from pathlib import Path; from sqlalchemy.engine.url import make_url; from backend.app.config import database_url; u=make_url(database_url()); d=u.database; ok=u.drivername.startswith('sqlite') and bool(d) and d!=':memory:'; None if ok else sys.exit('not a sqlite file'); b=Path(d); ts=[b, Path(str(b)+'-wal'), Path(str(b)+'-shm')]; [(p.unlink(), print('\uc0ad\uc81c', p)) if p.is_file() else print('\uc5c6\uc74c', p) for p in ts]"
if errorlevel 1 exit /b 1

"%PY%" backend\scripts\seed_cameras.py
exit /b %ERRORLEVEL%
