"""Bot API himoyasi — X-Bot-Token sarlavhasi tekshiruvi.

Nega kerak: /api/layouts|knowledge|qa|tariff/ endpointlari kompaniyaning butun
bilim bazasini beradi. Server tashqariga chiqsa, tokensiz har kim o'qiy olardi.

Sozlash: .env da BOT_API_TOKEN=<uzun tasodifiy satr> (bot va backend BIR XIL
.env o'qiydi, shuning uchun ikkalasiga bitta qator yetadi). Token sozlanmagan
bo'lsa himoya O'CHIQ (lokal ishlab chiqish qulayligi uchun) — lekin DEBUG=False
bo'lsa settings.py token bo'lishini MAJBURIY qiladi (ishga tushmaydi).
"""
from __future__ import annotations

import hmac
from functools import wraps

from django.conf import settings
from django.http import JsonResponse


def require_bot_token(view):
    """X-Bot-Token sarlavhasini settings.BOT_API_TOKEN bilan solishtiradi.

    hmac.compare_digest — oddiy `==` emas (timing-attack'dan himoya).
    Token sozlanmagan bo'lsa tekshiruvsiz o'tkazadi (lokal rejim)."""
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        expected = settings.BOT_API_TOKEN
        if expected:
            got = request.headers.get("X-Bot-Token", "")
            if not hmac.compare_digest(got.encode(), expected.encode()):
                return JsonResponse({"error": "unauthorized"}, status=401)
        return view(request, *args, **kwargs)
    return wrapper
