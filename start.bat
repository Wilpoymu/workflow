@echo off
title Workflow Services
setlocal

cd /d "%~dp0"

echo ========================================
echo   Workflow — Starting Services
echo ========================================
echo.

:: ── Backend ────────────────────────────────
echo [BACKEND] Checking Python dependencies...
cd /d "%~dp0backend"
python -c "import fastapi,uvicorn,httpx,curl_cffi" 2>nul
if %ERRORLEVEL% neq 0 (
    echo [BACKEND] Installing dependencies...
    pip install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to install backend dependencies.
        pause & exit /b 1
    )
    echo [BACKEND] Installation complete.
) else (
    echo [BACKEND] Dependencies OK.
)
echo.

:: ── Frontend ────────────────────────────────
echo [FRONTEND] Setting up...
python "%~dp0backend\setup_frontend.py"
if %ERRORLEVEL% neq 0 (
    pause & exit /b 1
)
echo.

:: ── Build extension ────────────────────────
echo [EXTENSION] Building Chrome extension...
cd /d "%~dp0extension"
bun run build >nul 2>&1
if exist ".output\chrome-mv3\manifest.json" (
    echo [EXTENSION] Build OK ^(.output\chrome-mv3^)
) else (
    echo [EXTENSION] Build skipped
)
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
echo Opening browser...
timeout /t 3 /nobreak >nul
start http://localhost:5173

echo.
echo   Close each window to stop the service.
echo.
pause
