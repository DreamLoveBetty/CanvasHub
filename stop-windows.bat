@echo off
chcp 65001 >nul
setlocal EnableExtensions

title Stop CanvasHub
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"

if "%CANVASHUB_MAIN_PORT%"=="" set "CANVASHUB_MAIN_PORT=18463"
if "%CHATGPT_POOL_PORT%"=="" set "CHATGPT_POOL_PORT=18080"
set "VENV_DIR=%ROOT%\.venv"
set "PY=%VENV_DIR%\Scripts\python.exe"
set "LOG_DIR=%ROOT%\data\windows-start"

echo Stopping CanvasHub background processes...

if exist "%PY%" (
  "%PY%" -X utf8 "%ROOT%\windows_launcher.py" stop
)

call :kill_by_port %CANVASHUB_MAIN_PORT%
call :kill_by_port %CHATGPT_POOL_PORT%

echo Done.
pause
exit /b 0

:kill_by_port
for /f "tokens=5" %%P in ('netstat -ano -p tcp ^| findstr /R /C:":%~1 .*LISTENING"') do (
  taskkill /PID %%P /T /F >nul 2>nul
)
exit /b 0
