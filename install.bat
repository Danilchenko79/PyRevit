@echo off
rem PEER extension for pyRevit - install / update
rem Clones https://github.com/Danilchenko79/PyRevit (branch main) into
rem %APPDATA%\pyRevit\Extensions\PEER.extension and turns on pyRevit auto-update,
rem so every Revit start pulls the latest version from GitHub.
rem Git is NOT required: pyRevit has its own built-in git.

setlocal
set "EXT_NAME=PEER"
set "REPO_URL=https://github.com/Danilchenko79/PyRevit.git"
set "BRANCH=main"
set "EXT_DIR=%APPDATA%\pyRevit\Extensions\%EXT_NAME%.extension"

rem --- find pyRevit CLI ---
set "PYREVIT="
where pyrevit >nul 2>nul && set "PYREVIT=pyrevit"
if not defined PYREVIT if exist "%APPDATA%\pyRevit-Master\bin\pyrevit.exe" set "PYREVIT=%APPDATA%\pyRevit-Master\bin\pyrevit.exe"
if not defined PYREVIT if exist "%ProgramFiles%\pyRevit-Master\bin\pyrevit.exe" set "PYREVIT=%ProgramFiles%\pyRevit-Master\bin\pyrevit.exe"
if not defined PYREVIT if exist "%ProgramFiles%\pyRevit CLI\pyrevit.exe" set "PYREVIT=%ProgramFiles%\pyRevit CLI\pyrevit.exe"
if not defined PYREVIT (
    echo.
    echo [ERROR] pyRevit is not installed on this computer.
    echo Install pyRevit first: https://github.com/pyrevitlabs/pyRevit/releases
    echo Then run this file again.
    goto :fail
)

rem --- install or update ---
if exist "%EXT_DIR%\.git" goto :update
if exist "%EXT_DIR%" (
    echo.
    echo [ERROR] Folder already exists but was not installed from GitHub:
    echo   %EXT_DIR%
    echo Close Revit, delete this folder and run this file again.
    goto :fail
)

echo Installing %EXT_NAME% from %REPO_URL% ...
"%PYREVIT%" extend ui %EXT_NAME% %REPO_URL% --branch=%BRANCH%
if errorlevel 1 goto :neterr
goto :config

:update
echo %EXT_NAME% is already installed. Updating...
"%PYREVIT%" extensions update %EXT_NAME%
if errorlevel 1 goto :neterr

:config
rem --- auto-update on every Revit start ---
"%PYREVIT%" configs checkupdates enable
"%PYREVIT%" configs autoupdate enable

echo.
echo [OK] %EXT_NAME% is installed. Restart Revit - the PEER tab will appear.
echo Updates will be downloaded automatically when Revit starts.
echo.
pause
exit /b 0

:neterr
echo.
echo [ERROR] Could not download from GitHub.
echo Check that github.com opens in your browser (internet / company proxy).
:fail
echo.
pause
exit /b 1
