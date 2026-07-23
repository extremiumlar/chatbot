@echo off
REM Userbot'ni to'xtatadi — FAQAT userbot.py jarayonini topib o'chiradi,
REM kompyuterdagi boshqa python dasturlariga tegmaydi.
REM
REM   stop.bat            — BARCHA userbot nusxalarini to'xtatadi (hamma akkaunt)
REM   stop.bat shahnoza   — FAQAT "shahnoza" sessiyasini to'xtatadi, qolganlari davom etadi
if "%~1"=="" (
    wmic process where "name like 'python%%' and commandline like '%%userbot%%'" call terminate >nul 2>&1
    echo Barcha userbot nusxalari to'xtatildi (agar ishlayotgan bo'lsa).
) else (
    wmic process where "name like 'python%%' and commandline like '%%userbot%%' and commandline like '%%--session %1%%'" call terminate >nul 2>&1
    echo '%1' sessiyasi to'xtatildi (agar ishlayotgan bo'lsa).
)
echo Oynani yopish uchun biror tugma bosing...
pause >nul
