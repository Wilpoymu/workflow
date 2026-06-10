@echo off
title Workflow — Build Extension

cd /d "%~dp0extension"

echo ========================================
echo   Building Chrome Extension
echo ========================================
echo.

:: Detect package manager
set "PM=npm"
where bun >nul 2>nul
if %ERRORLEVEL% equ 0 (
    set "PM=bun"
    echo [OK] Using bun
) else (
    echo [OK] Using npm
)
echo.

:: Install deps if needed
if not exist "node_modules" (
    echo Installing dependencies...
    if "%PM%"=="bun" (
        bun install
    ) else (
        npm install
    )
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Install failed.
        pause
        exit /b 1
    )
    echo.
)

:: Build
echo Building...
if "%PM%"=="bun" (
    bun run build
) else (
    npx wxt build
)

if %ERRORLEVEL% equ 0 (
    echo.
    echo ========================================
    echo   Build complete!
    echo   Output: extension\.output\chrome-mv3\
    echo ========================================
    echo.
    echo   Load in Chrome:
    echo   1. chrome://extensions
    echo   2. Enable "Developer mode"
    echo   3. "Load unpacked" → select:
    echo      extension\.output\chrome-mv3\
    echo.
) else (
    echo [ERROR] Build failed.
)

pause
