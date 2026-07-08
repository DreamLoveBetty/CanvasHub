@echo off
chcp 65001 >nul
setlocal EnableExtensions

title CanvasHub Launcher
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

if "%CANVASHUB_MAIN_PORT%"=="" set "CANVASHUB_MAIN_PORT=18463"
if "%CHATGPT_POOL_HOST%"=="" set "CHATGPT_POOL_HOST=127.0.0.1"
if "%CHATGPT_POOL_PORT%"=="" set "CHATGPT_POOL_PORT=18080"

rem Force UTF-8 for Python processes launched with redirected logs.
rem Without this, Windows may default stdout/stderr to GBK and crash on emoji/non-ASCII logs.
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "MINIAPP_PORT=%CANVASHUB_MAIN_PORT%"
set "PORT=%CANVASHUB_MAIN_PORT%"

set "VENV_DIR=%ROOT%\.venv"
set "PY=%VENV_DIR%\Scripts\python.exe"
set "LOG_DIR=%ROOT%\data\windows-start"
set "CANVASHUB_ROOT=%ROOT%"
set "CANVASHUB_LOG_DIR=%LOG_DIR%"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>nul

echo.
echo ===============================================
echo   CanvasHub Windows one-click launcher
echo ===============================================
echo Project: %ROOT%
echo Main:    http://127.0.0.1:%CANVASHUB_MAIN_PORT%/desktop.html
echo Sidecar: http://%CHATGPT_POOL_HOST%:%CHATGPT_POOL_PORT%/health
echo Logs:    %LOG_DIR%
echo.

call :ensure_python || goto :fail
call :ensure_venv || goto :fail
set "CANVASHUB_PY=%PY%"
call :ensure_settings || goto :fail
call :ensure_deps || goto :fail
call :ensure_sidecar_auth_key || goto :fail

"%PY%" -X utf8 "%ROOT%\windows_launcher.py" start
if errorlevel 1 goto :fail

echo.
echo Done. CanvasHub is running in background processes.
echo To stop it, double-click stop-windows.bat.
echo.
pause
exit /b 0

:ensure_python
if exist "%PY%" exit /b 0
where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set "BASE_PY=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python was not found. Install Python 3.10+ from https://www.python.org/downloads/windows/
    exit /b 1
  )
  set "BASE_PY=python"
)
%BASE_PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Python 3.10+ is required.
  exit /b 1
)
exit /b 0

:ensure_venv
if exist "%PY%" exit /b 0
echo Creating virtual environment...
%BASE_PY% -m venv "%VENV_DIR%"
if errorlevel 1 exit /b 1
exit /b 0

:ensure_settings
if not exist "%ROOT%\settings.json" (
  if exist "%ROOT%\settings.example.json" (
    echo Creating local settings.json from settings.example.json...
    copy "%ROOT%\settings.example.json" "%ROOT%\settings.json" >nul
  ) else (
    echo settings.example.json was not found.
    exit /b 1
  )
)
exit /b 0

:ensure_deps
"%PY%" -c "import requests, PIL, fitz, fastapi, uvicorn, curl_cffi" >nul 2>nul
if not errorlevel 1 exit /b 0
echo Installing Python dependencies. First run may take a few minutes...
"%PY%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1
"%PY%" -m pip install -r "%ROOT%\requirements.txt"
if errorlevel 1 exit /b 1
"%PY%" -m pip install -r "%ROOT%\sidecars\chatgpt_pool\requirements.txt"
if errorlevel 1 exit /b 1
exit /b 0

:ensure_sidecar_auth_key
"%PY%" -X utf8 -c "from backend.app_config import get_chatgpt_pool_config; get_chatgpt_pool_config(ensure_auth_key=True)" >nul 2>>"%LOG_DIR%\bootstrap.err.log"
if errorlevel 1 (
  echo Failed to initialize sidecar auth key. See %LOG_DIR%\bootstrap.err.log
  exit /b 1
)
exit /b 0

:fail
echo.
echo Startup failed. Check logs in: %LOG_DIR%
echo If no service log exists, copy this whole window output and send it back.
echo.
pause
exit /b 1
