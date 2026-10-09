@echo off
rem Makes the update-signing key in one go (docs/releases.md):
rem saves the private half as the GitHub secret MCSC_UPDATE_SIGNING_KEY
rem and writes the public half into agent\signing.py for you to commit.
rem Needs Python and the GitHub CLI (gh), signed in. Asks before replacing a key.
setlocal
cd /d "%~dp0"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys" >nul 2>nul && set "PY=python"
if not defined PY (
    echo Python isn't installed. Install it from https://www.python.org/downloads/
    echo ^(tick "Add python.exe to PATH"^), then double-click this file again.
    set "CODE=1"
    goto :done
)
%PY% -c "import cryptography" >nul 2>nul && goto :run
rem The key is made with the app's own libraries: install them into .venv,
rem the same place setup.cmd puts them.
echo Installing what this needs into .venv (once)...
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
set "PY=.venv\Scripts\python.exe"
"%PY%" -m pip install --quiet --require-hashes -r requirements.lock
if errorlevel 1 (
    echo Couldn't install the libraries. Run setup.cmd once, then try again.
    set "CODE=1"
    goto :done
)
:run
%PY% scripts\make_update_key.py --github
set "CODE=%ERRORLEVEL%"
:done
rem When double-clicked, keep the window open so the result can be read.
if not defined CI echo %CMDCMDLINE% | findstr /i /c:"%~nx0" >nul && (echo. & pause)
exit /b %CODE%
