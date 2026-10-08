@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0creator-autonomous-reels-local-r40.ps1" %*
exit /b %ERRORLEVEL%
