"""Django backend bilan aloqa.

Bot xonadon TURLARINI va ularга yuklangan PLANIROVKA rasmlarini shu backenddан oladi
(backend o'z navbatida Uysot API'дан sync qiladi + admin qo'lда rasm yuklaydi).
Backend ishlamasa — bo'sh ro'yxat qaytadi (bot planirovkani "menejer yuboradi" deydi).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request

import config

log = logging.getLogger("backend")

_cache: dict[str, tuple[float, object]] = {}


def get_layouts(force: bool = False) -> list[dict]:
    """Faol xonadon turlari (keshlangan). Har biri:
    {id, rooms, area, blocks[], available_count, total_count,
     image_url (2D, ixtiyoriy), image_3d_url (3D, ixtiyoriy), ...}."""
    now = time.time()
    hit = _cache.get("layouts")
    if not force and hit and now - hit[0] < config.BACKEND_CACHE_TTL:
        return hit[1]  # type: ignore[return-value]
    try:
        url = f"{config.BACKEND_API_URL}/api/layouts/"
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data") or []
    except Exception as e:  # noqa: BLE001
        log.warning("Backend layouts olishда xato: %s", e)
        data = []
    _cache["layouts"] = (now, data)
    return data


def layouts_with_image(rooms: int | None = None) -> list[dict]:
    """Kamida BITTA rasmi (2D yoki 3D) YUKLANGAN turlar. rooms berilsa — filtrlaydi."""
    out = []
    for l in get_layouts():
        if not (l.get("image_url") or l.get("image_3d_url")):
            continue
        if rooms is not None and int(l.get("rooms", 0)) != rooms:
            continue
        out.append(l)
    return out


def fetch_image(image_url: str) -> bytes:
    """Rasm baytlarini yuklab oladi (Telegramга yuborish uchun)."""
    with urllib.request.urlopen(image_url, timeout=20) as resp:
        return resp.read()
