@echo off
rem PEER for pyRevit - install / repair. No key needed: sign in later in Revit (PEER -> Account).
rem Keep install.ps1 next to this file. No PEER code and no keys are inside these two files.
setlocal
set "PEER_URL=__PEER_SERVICE_URL__"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Url "%PEER_URL%" %*
echo.
pause
exit /b %errorlevel%
