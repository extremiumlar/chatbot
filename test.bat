@echo off
REM Botni terminalда, Telegram'siz sinash (savol yozib javob olasiz).
cd /d "%~dp0"
".venv\Scripts\python.exe" chat.py
echo.
pause >nul
