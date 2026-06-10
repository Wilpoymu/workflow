@echo off
title Workflow Services

cd /d "%~dp0"

echo ========================================
echo   Workflow — Starting Services
echo ========================================
echo.

:: ── Backend validation ──────────────────────
echo [BACKEND] Checking dependencies...
cd /d "%~dp0backend"
python validate.py
if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Backend dependencies missing.
    echo   Run: pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)
echo [BACKEND] Dependencies OK
echo.

:: ── Frontend validation ─────────────────────
echo [FRONTEND] Checking dependencies...
cd /d "%~dp0frontend"
if not exist "node_modules" (
    echo [WARN] node_modules not found.
    echo   Run: bun install
    echo.
    pause
    exit /b 1
)
if not exist "node_modules\vite" (
    echo [WARN] vite not found in node_modules.
    echo   Run: bun install
    echo.
    pause
    exit /b 1
)
echo [FRONTEND] Dependencies OK
echo.

:: ── Start services ─────────────────────────
cd /d "%~dp0"

echo [1/2] Starting Backend (FastAPI :8000)...
start "Workflow Backend" cmd /k "cd /d "%~dp0backend" && python -m uvicorn app.main:app --reload"

echo [2/2] Starting Frontend (Vite :5173)...
start "Workflow Frontend" cmd /k "cd /d "%~dp0frontend" && bun run dev"

echo.
echo ========================================
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo ========================================
echo.
echo   Close each window to stop the service.
echo.
pause
