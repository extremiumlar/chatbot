@echo off
REM Django backend (admin panel + API) ni ishga tushiradi.
REM Admin: http://127.0.0.1:8010/admin/   |   API: http://127.0.0.1:8010/api/layouts/
cd /d "%~dp0backend"
"..\.venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8010
echo.
pause >nul
