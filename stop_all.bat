@echo off
REM Butun tizimni to'xtatadi: backend (Django) + BARCHA Telegram akkauntlar.
REM Faqat shu loyihaga tegishli jarayonlarni topib o'chiradi.
cd /d "%~dp0"

echo Telegram akkauntlar to'xtatilmoqda...
wmic process where "name like 'python%%' and commandline like '%%userbot%%'" call terminate >nul 2>&1

echo Backend (Django) to'xtatilmoqda...
wmic process where "name like 'python%%' and commandline like '%%manage.py%%runserver%%'" call terminate >nul 2>&1

echo.
echo Barcha komponentlar to'xtatildi (agar ishlayotgan bo'lsa).
echo Oynani yopish uchun biror tugma bosing...
pause >nul
