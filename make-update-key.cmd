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
rem The key needs only the cryptography library (and what it uses): install
rem just those, pinned and hash-checked from requirements.lock, into .venv.
rem Not the whole lock: some of it has no ready-made build for the newest
rem Python yet, and pip can't build those without a compiler.
echo Installing what this needs into .venv (once)...
if not exist ".venv\Scripts\python.exe" %PY% -m venv .venv
set "PY=.venv\Scripts\python.exe"
"%PY%" scripts\make_update_key.py --requirements > ".venv\update-key-requirements.txt"
"%PY%" -m pip install --quiet --only-binary=:all: --require-hashes -r ".venv\update-key-requirements.txt"
if errorlevel 1 (
    echo Couldn't install the cryptography library for this Python.
    echo Install Python 3.13 from https://www.python.org/downloads/ ^(tick "Add python.exe to PATH"^),
    echo delete the .venv folder here, then double-click this file again.
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
