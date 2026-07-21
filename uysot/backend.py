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


def _open(url: str, timeout: int):
    """Backend so'rovi — himoya tokeni (X-Bot-Token) bilan."""
    req = urllib.request.Request(url)
    if config.BOT_API_TOKEN:
        req.add_header("X-Bot-Token", config.BOT_API_TOKEN)
    return urllib.request.urlopen(req, timeout=timeout)


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
        with _open(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8")).get("data") or []
    except Exception as e:  # noqa: BLE001
        log.warning("Backend layouts olishда xato: %s", e)
        data = []
    _cache["layouts"] = (now, data)
    return data


def layouts_with_image(rooms: int | None = None,
                       only_available: bool = True) -> list[dict]:
    """Kamida BITTA rasmi (2D yoki 3D) YUKLANGAN turlar. rooms berilsa — filtrlaydi.

    only_available=True (default): faqat SOTUVDA QOLGAN (available_count > 0) turlar —
    sotilib bo'lgan xonadon planirovkasi mijozga yuborilmasin. False — hammasi
    (masalan "bu tur bormi-yo'qmi" tekshiruvi uchun)."""
    out = []
    for l in get_layouts():
        if not (l.get("image_url") or l.get("image_3d_url")):
            continue
        if only_available and int(l.get("available_count") or 0) <= 0:
            continue
        if rooms is not None and int(l.get("rooms", 0)) != rooms:
            continue
        out.append(l)
    return out


def fetch_image(image_url: str) -> bytes:
    """Rasm baytlarini yuklab oladi (Telegramга yuborish uchun)."""
    with _open(image_url, timeout=20) as resp:
        return resp.read()


def inventory_summary() -> str:
    """Botning system-prompt'iga qo'shiladigan ixcham jonli inventar xulosasi.

    YAGONA MANBA: shu funksiya ham, planirovka oqimi (`layouts_with_image`) ham
    bir xil `get_layouts()` (Django Layout jadvali) dan o'qiydi — shuning uchun
    "jonli inventar 1 ta 1-xonali deydi, planirovka 3 tur yuboradi" kabi
    ziddiyat endi tuzilmaviy ravishda yo'q (raqamlar har doim bir xil manbadan).

    Uysot'ga TO'G'RIDAN-TO'G'RI so'rov BU YERDA YO'Q — Layout jadvali backend
    tomonida alohida (`manage.py sync_layouts` yoki admin tugmasi) yangilanadi.

    DIQQAT: bu yerda NARX ATAYIN YO'Q — bot mijozga narx aytmaydi (narx so'ralsa
    ofisga taklif qiladi). Backend ishlamasa/bo'sh bo'lsa — bo'sh satr qaytadi
    (bot umumiy bilim bazasiga tayanadi, jim qolmaydi)."""
    layouts = [l for l in get_layouts() if int(l.get("available_count") or 0) > 0]
    if not layouts:
        return ""

    apts = [l for l in layouts if int(l.get("rooms") or 0) > 0]
    total_units = sum(int(l.get("available_count") or 0) for l in apts)

    lines: list[str] = [
        f"Hozir sotuvda jami {total_units} ta kvartira ({len(apts)} xil tur).",
        "\nKVARTIRALAR (xona turi bo'yicha, qaysi blokda nechta qolgani):",
    ]
    by_room: dict[str, list[dict]] = {}
    for l in apts:
        by_room.setdefault(str(l["rooms"]), []).append(l)
    for rooms in sorted(by_room, key=lambda r: int(r) if r.isdigit() else 99):
        items = by_room[rooms]
        n = sum(int(l.get("available_count") or 0) for l in items)
        lines.append(f"• {rooms} xonali — jami {n} ta:")
        for l in sorted(items, key=lambda x: float(x.get("area") or 0)):
            blocks = ", ".join(l.get("blocks") or [])
            floors = (f"{l['min_floor']}–{l['max_floor']}" if l.get("min_floor")
                     and l.get("max_floor") and l["min_floor"] != l["max_floor"]
                     else str(l.get("min_floor") or l.get("max_floor") or "?"))
            lines.append(
                f"   - {blocks}-blok: {l.get('available_count')} ta | "
                f"{float(l.get('area') or 0):g} m² | {floors}-qavat"
            )
    return "\n".join(lines)
