@echo off
cd /d "%~dp0backend"

if not exist ".venv" (
    echo [1/3] Creating virtual environment...
    python -m venv .venv
)

echo [2/3] Installing dependencies...
.venv\Scripts\pip install -r requirements.txt --quiet

echo [3/3] Initializing database...
.venv\Scripts\python init_db.py

echo.
echo Starting FastAPI backend on http://localhost:8000
.venv\Scripts\uvicorn main:app --reload --host 0.0.0.0 --port 8000
