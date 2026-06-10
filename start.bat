@echo off
title Workflow Services

cd /d "%~dp0"

echo ========================================
echo   Workflow — Starting Services
echo ========================================
echo.

:: ── Backend installation ────────────────────
echo [BACKEND] Checking Python dependencies...
cd /d "%~dp0backend"

python -c "import fastapi, uvicorn, pydantic, httpx, curl_cffi" 2>nul
if %ERRORLEVEL% neq 0 (
    echo [BACKEND] Installing dependencies...
    pip install -r requirements.txt
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to install backend dependencies.
        pause
        exit /b 1
    )
    echo [BACKEND] Installation complete.
) else (
    echo [BACKEND] Dependencies OK.
)
echo.

:: ── Frontend installation ───────────────────
echo [FRONTEND] Checking dependencies...

:: Check Node.js
node --version >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Node.js is not installed. Install it from https://nodejs.org
    pause
    exit /b 1
)

:: Detect package manager: bun > npm
set "PM=npm"
bun --version >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PM=bun"
    echo [FRONTEND] Using bun
) else (
    npm --version >nul 2>nul
    if %ERRORLEVEL% equ 0 (
        echo [FRONTEND] Using npm
    ) else (
        echo [ERROR] npm not found even though Node.js is installed.
        pause
        exit /b 1
    )
)

echo [FRONTEND] Using %PM%

cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo [FRONTEND] Installing dependencies...
    if "%PM%"=="bun" (
        bun install
    ) else (
        npm install
    )
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Failed to install frontend dependencies.
        pause
        exit /b 1
    )
    echo [FRONTEND] Installation complete.
) else (
    echo [FRONTEND] Dependencies OK.
)

:: Build extension
echo.
echo [EXTENSION] Building Chrome extension...
cd /d "%~dp0extension"
if "%PM%"=="bun" (
    bun run build >nul 2>&1
) else (
    call npx --yes wxt build >nul 2>&1
)
if exist ".output\chrome-mv3\manifest.json" (
    echo [EXTENSION] Build OK ^(.output\chrome-mv3^)
) else (
    echo [EXTENSION] Build skipped (not critical)
)
echo.

:: ── Start services ─────────────────────────
cd /d "%~dp0"

echo [1/2] Starting Backend (FastAPI :8000)...
start "Workflow Backend" cmd /k "cd /d "%~dp0backend" && python -m uvicorn app.main:app --reload"

echo [2/2] Starting Frontend (Vite :5173)...
if "%PM%"=="bun" (
    start "Workflow Frontend" cmd /k "cd /d "%~dp0frontend" && bun run dev"
) else (
    start "Workflow Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"
)

echo.
echo ========================================
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo ========================================
echo.

:: Open browser after a short delay (let services start)
echo Opening browser...
timeout /t 3 /nobreak >nul
start http://localhost:5173

echo.
echo   Close each window to stop the service.
echo.
pause
