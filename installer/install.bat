@echo off
rem PEER for pyRevit - install / repair. Needs your personal PEER key (or sends an access request).
rem Keep install.ps1 next to this file. No PEER code and no keys are inside these two files.
setlocal
set "PEER_URL=__PEER_SERVICE_URL__"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Url "%PEER_URL%" %*
echo.
pause
exit /b %errorlevel%
