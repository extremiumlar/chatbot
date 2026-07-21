# Deploy yo'riqnomasi (Linux server, systemd)

## 1. Fayllarni joylash
```bash
sudo mkdir -p /opt/nurli && cd /opt/nurli
git clone <repo> chatbot && cd chatbot
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt gunicorn
```

## 2. .env to'ldirish (loyiha ildizida)
Majburiy: `GEMINI_API_KEY`, `TELEGRAM_API_ID/HASH`, `UYSOT_SHOWROOM_TOKEN`,
`DJANGO_SECRET_KEY` (uzun tasodifiy), `BOT_API_TOKEN` (uzun tasodifiy),
`DJANGO_ALLOWED_HOSTS=admin.nurlidiyor.uz,127.0.0.1`, `DJANGO_DEBUG=0`,
`PUBLIC_BASE_URL=https://admin.nurlidiyor.uz` (bot boshqa mashinada bo'lsa),
`BACKEND_API_URL=http://127.0.0.1:8010` (bot shu serverda bo'lsa).

## 3. Backend tayyorlash
```bash
cd backend
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py collectstatic --noinput
../.venv/bin/python manage.py createsuperuser
../.venv/bin/python manage.py sync_layouts     # birinchi inventar sync
```

## 4. Servislarni yoqish
```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nurli-backend nurli-bot nurli-sync.timer
```
Birinchi ishga tushirishda bot Telegram kodi so'raydi — bir marta qo'lda:
`systemctl stop nurli-bot && .venv/bin/python userbot.py` (kod kiritib Ctrl+C),
keyin `systemctl start nurli-bot`.

## 5. nginx + HTTPS
`deploy/nginx.conf.example` ni ko'chirib domenni yozing; `certbot --nginx`;
so'ng `.env` da `DJANGO_HTTPS=1` va servislarni restart qiling.

## Tekshirish
- `curl -H "X-Bot-Token: $BOT_API_TOKEN" http://127.0.0.1:8010/api/layouts/` → 200
- Tokensiz → 401. Admin: https://domen/admin/
