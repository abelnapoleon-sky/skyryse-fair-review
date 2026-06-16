@echo off
title FAIR Review Server - keep this window open
cd /d "%~dp0"
echo ================================================================
echo   Skyryse FAIR Review
echo   Starting the server. Keep this window OPEN while you work.
echo   When you are done, close this window or press Ctrl+C.
echo ----------------------------------------------------------------
echo   Then open your browser to:  http://127.0.0.1:8000
echo ================================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_secure.ps1"
echo.
echo Server stopped. You can close this window.
pause
