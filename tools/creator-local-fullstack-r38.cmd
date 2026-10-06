@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0creator-local-fullstack-r38.ps1" %*
exit /b %ERRORLEVEL%
