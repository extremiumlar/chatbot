# Deploy yo'riqnomasi (Linux server, systemd)

## 1. Fayllarni joylash
```bash
sudo mkdir -p /opt/nurli && cd /opt/nurli
git clone <repo> chatbot && cd chatbot
python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt gunicorn
```

## 2. .env to'ldirish (loyiha ildizida)
Majburiy: `GEMINI_API_KEY`, `UYSOT_SHOWROOM_TOKEN`,
`DJANGO_SECRET_KEY` (uzun tasodifiy), `BOT_API_TOKEN` (uzun tasodifiy),
`DJANGO_ALLOWED_HOSTS=admin.nurlidiyor.uz,127.0.0.1`, `DJANGO_DEBUG=0`,
`PUBLIC_BASE_URL=https://admin.nurlidiyor.uz` (planirovka rasm URL'lari shu
domendan — Instagram Send API rasmni shu URL orqali yuklab oladi, shuning
uchun MAJBURIY va haqiqiy public HTTPS domen bo'lishi kerak, `127.0.0.1` emas),
`BACKEND_API_URL=http://127.0.0.1:8010` (bot shu serverda bo'lsa).

Instagram uchun (`.env.example`dagi izohlarga qarang — App ID/Secret, Page
Access Token va h.k. qayerdan olinishi tushuntirilgan):
`INSTAGRAM_APP_SECRET`, `INSTAGRAM_PAGE_ACCESS_TOKEN`, `INSTAGRAM_VERIFY_TOKEN`,
`INSTAGRAM_BUSINESS_ACCOUNT_ID`.

## 3. Backend tayyorlash
```bash
cd backend
../.venv/bin/python manage.py migrate
../.venv/bin/python manage.py collectstatic --noinput
../.venv/bin/python manage.py createsuperuser
../.venv/bin/python manage.py sync_layouts     # birinchi inventar sync
```

## 4. Servisni yoqish
```bash
sudo cp deploy/nurli-backend.service deploy/nurli-sync.service deploy/nurli-sync.timer \
    /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now nurli-backend nurli-sync.timer
```
Bot mantig'i (`instagram_bot.py`) endi ALOHIDA JARAYON EMAS — `nurli-backend`
(Django/gunicorn) ichida, webhook orqali ishlaydi. Eski Telegram userbot
(`nurli-bot.service`) endi kerak emas — allaqachon yoqilgan bo'lsa o'chiring:
```bash
sudo systemctl disable --now nurli-bot
```
(`userbot.py`/`bot.py` fayllari o'chirilmagan, faqat ishga tushirilmaydi.)

## 5. nginx + HTTPS
`deploy/nginx.conf.example` ni ko'chirib domenni yozing; `certbot --nginx`;
so'ng `.env` da `DJANGO_HTTPS=1` va servislarni restart qiling. nginx'ga
Instagram uchun QO'SHIMCHA sozlash SHART EMAS — webhook mavjud Django
backend ichida (`/api/instagram/webhook/`), mavjud `location /` bloki orqali o'tadi.

## 6. Meta App Dashboard'da webhook'ni ro'yxatdan o'tkazish
- Callback URL: `https://admin.nurlidiyor.uz/api/instagram/webhook/`
- Verify Token: `.env`dagi `INSTAGRAM_VERIFY_TOKEN` bilan bir xil qiymat
- Subscribe qilinadigan fieldlar: `messages` (xohlasangiz `messaging_postbacks` ham)
- Development mode'da faqat App Dashboard'dagi Tester/Administrator sifatida
  qo'shilgan Instagram akkauntlar bilan ishlaydi — real mijozlar bilan ishga
  tushirishdan oldin Meta App Review'dan o'tkazish kerak.

## Tekshirish
- `curl -H "X-Bot-Token: $BOT_API_TOKEN" http://127.0.0.1:8010/api/layouts/` → 200
- Tokensiz → 401. Admin: https://domen/admin/
- `curl "https://domen/api/instagram/webhook/?hub.mode=subscribe&hub.verify_token=$INSTAGRAM_VERIFY_TOKEN&hub.challenge=123"`
  → tanasida `123` qaytishi kerak.
