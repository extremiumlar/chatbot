@echo off
REM Butun tizimni BITTA buyruq bilan ishga tushiradi:
REM   1) Django backend (admin panel + API, 8010-port)
REM   2) Telegram akkaunt "hisob2"
REM   3) Telegram akkaunt "hisob3"
REM
REM Har biri ALOHIDA oynada ochiladi (nomlangan) — birortasini yopsangiz
REM boshqalar ishlashda davom etadi. Yangi akkaunt qo'shsangiz, pastga
REM yana bitta "start" qatorini qo'shing (masalan hisob4 uchun).
cd /d "%~dp0"

echo Backend (Django) ishga tushirilmoqda...
start "Nurli diyor - Backend" cmd /k "%~dp0start_backend.bat"

echo Backend ochilishini kutamiz (3 soniya)...
timeout /t 3 /nobreak >nul

echo Telegram akkaunt: hisob2...
start "Nurli diyor - hisob2" cmd /k "%~dp0start.bat" hisob2

echo Telegram akkaunt: hisob3...
start "Nurli diyor - hisob3" cmd /k "%~dp0start.bat" hisob3

echo.
echo Uchala komponent uchun alohida oyna ochildi:
echo   - Nurli diyor - Backend
echo   - Nurli diyor - hisob2
echo   - Nurli diyor - hisob3
echo Bu oynani yopishingiz mumkin — boshqalar ishlashda davom etadi.
echo Hammasini to'xtatish uchun: stop_all.bat
echo.
pause >nul
