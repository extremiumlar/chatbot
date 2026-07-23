@echo off
REM Nurli diyor userbot'ni bitta bosishда ishga tushiradi (venv python bilan).
REM
REM Bir nechta Telegram akkaunt (lichka) ulamoqchi bo'lsangiz, har biriga
REM ALOHIDA nom bering va ALOHIDA oynada ishga tushiring:
REM     start.bat            (asosiy akkaunt, .env dagi TELEGRAM_SESSION)
REM     start.bat shahnoza   (2-akkaunt)
REM     start.bat dilnoza    (3-akkaunt)
REM Har biri o'z sessiya fayliga (storage\<nom>.session) va o'z logiga
REM (storage\userbot_<nom>.log) yozadi; bitta umumiy bazadan (baza/bilim/
REM planirovka) foydalanadi. Bir xil nomni ikki marta ishga tushirib
REM bo'lmaydi (himoya bor) — turli nomlar esa parallel ishlayveradi.
cd /d "%~dp0"
if "%~1"=="" (
    ".venv\Scripts\python.exe" userbot.py
) else (
    ".venv\Scripts\python.exe" userbot.py --session %1
)
echo.
echo Bot to'xtadi. Oynani yopish uchun biror tugma bosing...
pause >nul
