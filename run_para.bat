@echo off
chcp 65001 >nul
setlocal
set "PY=%~dp0..\.tools\python310\python.exe"
if not exist "%PY%" set "PY=python"
if defined VOICE_PYTHON set "PY=%VOICE_PYTHON%"
set PYTHONIOENCODING=utf-8
"%PY%" "%~dp0scripts\transcribe_para.py" %*
set RC=%ERRORLEVEL%
echo.
pause
endlocal & exit /b %RC%
