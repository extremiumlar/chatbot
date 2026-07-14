@echo off
REM Userbot'ni to'xtatadi — FAQAT userbot.py jarayonini topib o'chiradi,
REM kompyuterdagi boshqa python dasturlariga tegmaydi.
wmic process where "name like 'python%%' and commandline like '%%userbot%%'" call terminate >nul 2>&1
echo Bot to'xtatildi (agar ishlayotgan bo'lsa).
echo Oynani yopish uchun biror tugma bosing...
pause >nul
