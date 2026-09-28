@echo off
rem Runs setup.ps1 without changing your PowerShell execution policy.
rem "-ExecutionPolicy Bypass" applies to this one PowerShell process only.
rem Usage: setup.cmd            (set up)
rem        setup.cmd --check    (read-only health check)
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set "CODE=%ERRORLEVEL%"
rem When double-clicked, keep the window open so the result can be read.
if not defined CI echo %CMDCMDLINE% | findstr /i /c:"%~nx0" >nul && (echo. & pause)
exit /b %CODE%
