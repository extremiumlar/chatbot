"""Django backend bilan aloqa — ikkita rejim.

1) HAQIQIY HTTP (standart, systemd/Docker) — bot va Django backend ALOHIDA
   jarayon bo'lganda (masalan gunicorn 127.0.0.1:8010) ishlatiladi.

2) IN-PROCESS (.env: BACKEND_IN_PROCESS=1) — bot va backend BIR XIL Django
   jarayonida ishlaganda (masalan cPanel Passenger: Instagram webhook shu
   Django ilovasi ichida, alohida port/jarayon yo'q). Bu holda BACKEND_API_URL
   orqali haqiqiy tarmoq so'rovi qilish o'z-o'ziga tiqilib qolishga olib keladi
   (hodimlar_tizimi loyihasida topilgan xuddi shu klassdagi bug: yagona
   Passenger ishchisi o'ziga so'rov kutib abadiy band bo'lib qoladi/yoki
   ulanish rad etiladi). django.test.Client Django URL routeri orqali
   TARMOQSIZ, to'g'ridan-to'g'ri view funksiyasini chaqiradi — bu muammoni
   butunlay bartaraf etadi.
"""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

import config

IN_PROCESS = os.getenv("BACKEND_IN_PROCESS", "0") == "1"


def _in_process_get(url: str):
    from django.test import Client  # lazy: faqat IN_PROCESS=1 bo'lganda kerak

    kwargs = {}
    if config.BOT_API_TOKEN:
        kwargs["HTTP_X_BOT_TOKEN"] = config.BOT_API_TOKEN
    path = urlsplit(url).path or url
    return Client().get(path, **kwargs)


def get_json(url: str, timeout: int = 5) -> dict:
    """GET so'rov, JSON javobni dict qilib qaytaradi (butun javob, {"data": ...} bilan)."""
    if IN_PROCESS:
        resp = _in_process_get(url)
        return json.loads(resp.content.decode("utf-8"))
    import urllib.request

    req = urllib.request.Request(url)
    if config.BOT_API_TOKEN:
        req.add_header("X-Bot-Token", config.BOT_API_TOKEN)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_bytes(url: str, timeout: int = 20) -> bytes:
    """GET so'rov, xom baytlarni qaytaradi (rasm/pdf yuklab olish uchun)."""
    if IN_PROCESS:
        resp = _in_process_get(url)
        return resp.content
    import urllib.request

    req = urllib.request.Request(url)
    if config.BOT_API_TOKEN:
        req.add_header("X-Bot-Token", config.BOT_API_TOKEN)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()
