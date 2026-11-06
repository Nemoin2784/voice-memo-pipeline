@echo off
setlocal
set "PY=%~dp0..\..\.tools\python310\python.exe"
if not exist "%PY%" set "PY=python"
if defined VOICE_PYTHON set "PY=%VOICE_PYTHON%"
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
echo.
echo   Voice transcription API : http://127.0.0.1:8765
echo   LAN access              : http://THIS-PC-IP:8765   (run ipconfig to find IPv4)
echo   Ctrl+C to stop (worker exits too)
echo.
echo   python: %PY%
echo.
"%PY%" -m uvicorn app:app --host 0.0.0.0 --port 8765
echo.
pause
endlocal
