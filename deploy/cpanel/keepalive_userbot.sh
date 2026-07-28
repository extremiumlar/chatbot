#!/bin/bash
# cPanel shared hosting'da systemd yo'q (root/sudo huquqi yo'q, CageFS
# jail) — bu skript cron orqali har 2-3 daqiqada ishga tushib, agar
# berilgan sessiya (akkaunt) uchun userbot.py ishlamayotgan bo'lsa uni
# qayta ishga tushiradi. Bu systemd'ning "Restart=always" xususiyatining
# qo'lda yasalgan muqobili (deploy/nurli-bot.service o'rniga).
#
# Sozlash (crontab -e):
#   */3 * * * * bash ~/chatbot/deploy/cpanel/keepalive_userbot.sh hisob2
#   */3 * * * * bash ~/chatbot/deploy/cpanel/keepalive_userbot.sh hisob3
#
# DIQQAT: bu rasmiy qo'llab-quvvatlanadigan usul emas (systemd/gunicorn'dan
# farqli) — hosting uzoq muddat ishlaydigan begona jarayonlarni keyinchalik
# tozalab tashlasa, jarayon bir muddat o'chib qolishi mumkin (cron uni
# tezda qayta tiklaydi, lekin oraliqda xabar o'tkazib yuborilishi mumkin).
set -e

SESSION="$1"
if [ -z "$SESSION" ]; then
    echo "Usage: keepalive_userbot.sh <session_name>" >&2
    exit 1
fi

ROOT="$HOME/chatbot"
VENV_PY="$HOME/virtualenv/chatbot/3.11/bin/python"
mkdir -p "$ROOT/logs"
LOG="$ROOT/logs/userbot_${SESSION}.log"
KEEPALIVE_LOG="$ROOT/logs/keepalive.log"

cd "$ROOT"

if pgrep -f "userbot.py --session $SESSION" > /dev/null 2>&1; then
    exit 0  # allaqachon ishlab turibdi — hech narsa qilmaymiz
fi

nohup "$VENV_PY" userbot.py --session "$SESSION" >> "$LOG" 2>&1 &
disown
echo "$(date '+%Y-%m-%d %H:%M:%S'): '$SESSION' qayta ishga tushirildi (PID $!)" >> "$KEEPALIVE_LOG"
