"""Uysot showroom API'dan xonadon turlarini sync qilish — asosiy mantiq.

Ikkita joydan chaqiriladi:
  - `python manage.py sync_layouts` (qo'lda)
  - views.layouts_api dagi AVTO-SYNC (ma'lumot eskirgan bo'lsa, fonda o'zi yangilaydi)

Sync yuklangan planirovka rasmlariga, is_active va izohga TEGMAYDI.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request

from django.conf import settings
from django.utils import timezone

from .models import Layout

log = logging.getLogger("inventory.sync")

# Bir vaqtda faqat bitta sync ishlashi uchun (avto + qo'lda to'qnashmasin)
_sync_lock = threading.Lock()


def _get(path: str) -> dict:
    req = urllib.request.Request(f"{settings.UYSOT_SHOWROOM_BASE}{path}")
    req.add_header("X-Auth", settings.UYSOT_SHOWROOM_TOKEN)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def sync_all(progress=None) -> str:
    """To'liq sync. progress — ixtiyoriy callback(str) (manage.py chiqishi uchun).
    Natija xulosasini (str) qaytaradi. Xato bo'lsa exception ko'taradi."""
    def say(msg: str) -> None:
        if progress:
            progress(msg)
        log.info(msg)

    if not settings.UYSOT_SHOWROOM_TOKEN:
        raise RuntimeError("UYSOT_SHOWROOM_TOKEN .env da yo'q.")
    house = settings.UYSOT_HOUSE_ID

    # 1) Bloklar va qavatlar
    fp = _get(f"/filter-properties/{house}")["data"]
    blocks = {b["id"]: b["name"] for b in fp.get("buildingCompactList", [])}
    min_floor = int(fp.get("minFloor") or 1)
    max_floor = int(fp.get("maxFloor") or 9)
    say(f"Bloklar: {list(blocks.values())}, qavatlar {min_floor}-{max_floor}")

    # 2) Shaxmatka -> barcha (flatId, status, blok nomi)
    flats: list[tuple[int, str, str]] = []
    for bid, bname in blocks.items():
        for fl in range(min_floor, max_floor + 1):
            try:
                d = _get(f"/block-flat-data/{bid}?floor={fl}")["data"] or {}
            except Exception as e:  # noqa: BLE001
                say(f"  blok {bname} qavat {fl}: {e}")
                continue
            for x in d.get("blockFlatDataDtoList") or []:
                flats.append((x["flatId"], x.get("flatStatus") or "", bname))
    say(f"Shaxmatkada jami {len(flats)} xonadon topildi. Tafsilotlar olinmoqda...")

    # 3) Har flat uchun maydon/xona -> (xona, maydon) turlari
    types: dict[tuple, dict] = {}
    for i, (fid, status, bname) in enumerate(flats, 1):
        try:
            fd = _get(f"/block/flat-all-data/{fid}")["data"]
        except Exception:  # noqa: BLE001
            continue
        try:
            rooms = int(fd["rooms"])
            area = round(float(fd["area"]), 1)
        except (KeyError, TypeError, ValueError):
            continue
        number = str(fd.get("number") or "")
        # "M" raqamli — tijorat (do'kon), kvartira turlariga qo'shmaymiz
        if number.upper().startswith("M"):
            continue
        floor = fd.get("floor")
        t = types.setdefault((rooms, area), {
            "blocks": set(), "avail": 0, "total": 0, "floors": set(),
            "sample": None, "sample_avail": None,
        })
        t["total"] += 1
        t["blocks"].add(str(fd.get("block") or bname))
        if floor:
            t["floors"].add(int(floor))
        if status == "SALE":
            t["avail"] += 1
            t["sample_avail"] = t["sample_avail"] or fid
        t["sample"] = t["sample"] or fid
        if progress and i % 25 == 0:
            progress(f"  {i}/{len(flats)}...")
        time.sleep(0.03)

    # 4) Layout jadvaliga yozamiz (rasm/is_active/izohga tegmaymiz)
    now = timezone.now()
    created = updated = 0
    for (rooms, area), t in sorted(types.items()):
        blocks_str = ", ".join(sorted(t["blocks"],
                                      key=lambda b: int(b) if b.isdigit() else 99))
        _, is_new = Layout.objects.update_or_create(
            rooms=rooms, area=area,
            defaults=dict(
                blocks=blocks_str,
                available_count=t["avail"],
                total_count=t["total"],
                sample_flat_id=t["sample_avail"] or t["sample"],
                min_floor=min(t["floors"]) if t["floors"] else None,
                max_floor=max(t["floors"]) if t["floors"] else None,
                synced_at=now,
            ),
        )
        created += int(is_new)
        updated += int(not is_new)

    summary = (f"Sync tugadi: {len(types)} tur ({created} yangi, {updated} yangilangan), "
               f"{len(flats)} xonadon ko'rildi.")
    say(summary)
    return summary


def maybe_auto_sync() -> None:
    """Ma'lumot eskirgan bo'lsa (LAYOUT_SYNC_TTL dan qari) — FONDA sync boshlaydi.
    Bloklamaydi: API so'roviga darhol eski (lekin bor) ma'lumot qaytadi, yangisi
    keyingi so'rovlarga tayyor bo'ladi. Parallel sync bo'lmasligi uchun lock bor."""
    import os
    ttl = int(os.getenv("LAYOUT_SYNC_TTL", "3600"))  # sekund; default 1 soat
    latest = (Layout.objects.exclude(synced_at=None)
              .order_by("-synced_at").values_list("synced_at", flat=True).first())
    if latest and (timezone.now() - latest).total_seconds() < ttl:
        return
    if _sync_lock.locked():
        return  # allaqachon sync ketyapti

    def _run() -> None:
        if not _sync_lock.acquire(blocking=False):
            return
        try:
            sync_all()
        except Exception:  # noqa: BLE001
            log.exception("Avto-sync xatosi (keyingi so'rovda qayta uriniladi)")
        finally:
            _sync_lock.release()

    threading.Thread(target=_run, daemon=True, name="layout-auto-sync").start()
    log.info("Avto-sync fonda boshlandi (ma'lumot %s dan eski).",
             f"{ttl}s" if latest else "yo'q")
