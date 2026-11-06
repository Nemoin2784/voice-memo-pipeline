@echo off
setlocal
net session >nul 2>&1
if errorlevel 1 (
  echo.
  echo   Requesting administrator rights - click "Yes" on the UAC prompt...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo.
echo   Removing inbound BLOCK rules for python.exe and adding allow rules...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix_firewall.ps1"
echo.
echo   Look for "Expect: NO row with Action=Block." above.
echo   If a Block row is still listed, the removal did not work.
echo.
pause
endlocal
