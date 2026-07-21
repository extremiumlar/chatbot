"""Uysot showroom API'dan xonadon turlarini sync qilish — asosiy mantiq.

Chaqiriladi: `python manage.py sync_layouts` (qo'lda/cron) yoki admin panelda
"Hozir sync qilish" tugmasi (LayoutAdmin). ENDI so'rov yo'lida (`/api/layouts/`)
AVTOMATIK CHAQIRILMAYDI (4.4-tuzatish) — begona so'rov Uysot'ga zanjir
chaqiruvlarini boshlab yubormasin.

Sync yuklangan planirovka rasmlariga, is_active va izohga TEGMAYDI.

SO'ROVLAR SONI (4.4-tuzatish, N+1 muammosi hal qilindi):
  ESKI usul: har SOTUVDAGI/SOTILGAN xonadon uchun ALOHIDA `flat-all-data` so'rovi —
  ~257 ta HTTP chaqiruv (1 + 45 chessboard + ~211 flat-all-data).
  YANGI usul: `get-all-flat-by-filter` BITTA so'rov turkumida (sahifalab, odatda
  1 sahifa) barcha SOTUVDAGI xonadonlarni TO'LIQ tafsilot bilan beradi (rooms,
  area, block, floor) — flat-all-data endi shart emas. SOTILGAN xonadonlar soni
  uchun faqat chessboard (`block-flat-data`, blok x qavat) kerak — u yerda
  `flatRooms`+`flatStatus` bor, `area` esa SOTUVDAGI ma'lumotdan (blok+xona soni
  bo'yicha) olinadi. Natija: ~257 -> ~47 so'rov (haqiqiy bino: 5 blok x 9 qavat).
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
# Oxirgi (muvaffaqiyatli yoki muvaffaqiyatsiz) urinish payti (monotonic) — 4.4:
# ketma-ket muvaffaqiyatsizliklarda har so'rovda qayta urinib, Uysot'ni "urib"
# yubormaslik uchun.
_last_attempt: float = 0.0
_RETRY_BACKOFF_SEC = 900  # 15 daqiqa


def _get(path: str) -> dict:
    req = urllib.request.Request(f"{settings.UYSOT_SHOWROOM_BASE}{path}")
    req.add_header("X-Auth", settings.UYSOT_SHOWROOM_TOKEN)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _post(path: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(f"{settings.UYSOT_SHOWROOM_BASE}{path}",
                                 data=data, method="POST")
    req.add_header("X-Auth", settings.UYSOT_SHOWROOM_TOKEN)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _is_commercial(number: str) -> bool:
    return str(number or "").upper().startswith("M")


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

    # 1) Bloklar va qavatlar (1 so'rov)
    fp = _get(f"/filter-properties/{house}")["data"]
    blocks = {b["id"]: b["name"] for b in fp.get("buildingCompactList", [])}
    min_floor = int(fp.get("minFloor") or 1)
    max_floor = int(fp.get("maxFloor") or 9)
    say(f"Bloklar: {list(blocks.values())}, qavatlar {min_floor}-{max_floor}")

    # 2) SOTUVDAGI xonadonlar — BITTA so'rov turkumida (sahifalab) TO'LIQ tafsilot
    # bilan (rooms/area/block/floor) — har flat uchun alohida so'rov ENDI SHART EMAS.
    avail_flats: list[dict] = []
    page = 1
    while True:
        d = _post(f"/block/get-all-flat-by-filter/{house}",
                  {"page": page, "size": 200})["data"]
        avail_flats.extend(d.get("data") or [])
        if page >= int(d.get("totalPages") or 1):
            break
        page += 1
    say(f"Sotuvda {len(avail_flats)} birlik (to'liq tafsilot, {page} sahifa so'rovi).")

    types: dict[tuple, dict] = {}
    # (blok nomi, xona soni) -> maydon — sotilgan birliklarni turkumlash uchun
    # (chessboard'da area yo'q, lekin bir xil blok+xona sonida maydon barqaror)
    block_room_area: dict[tuple[str, int], float] = {}
    for fd in avail_flats:
        if _is_commercial(fd.get("number")):
            continue   # do'kon/tijorat — kvartira turlariga qo'shmaymiz
        try:
            rooms = int(fd["rooms"])
            area = round(float(fd["area"]), 1)
        except (KeyError, TypeError, ValueError):
            continue
        bname = str(fd.get("block") or "")
        floor = fd.get("floor")
        t = types.setdefault((rooms, area), {
            "blocks": set(), "avail": 0, "total": 0, "floors": set(),
            "sample": None, "sample_avail": None,
        })
        t["avail"] += 1
        t["total"] += 1   # sotilganlar 3-qadamda qo'shiladi
        t["blocks"].add(bname)
        if floor:
            t["floors"].add(int(floor))
        t["sample_avail"] = t["sample_avail"] or fd["id"]
        t["sample"] = t["sample"] or fd["id"]
        block_room_area[(bname, rooms)] = area

    # 3) SOTILGAN birliklar SONI uchun chessboard (blok x qavat). flatRooms +
    # flatStatus YETARLI — flat-all-data (har flat uchun so'rov) endi shart emas.
    n_chess = 0
    for bid, bname in blocks.items():
        for fl in range(min_floor, max_floor + 1):
            n_chess += 1
            try:
                d = _get(f"/block-flat-data/{bid}?floor={fl}")["data"] or {}
            except Exception as e:  # noqa: BLE001
                say(f"  blok {bname} qavat {fl}: {e}")
                continue
            for x in d.get("blockFlatDataDtoList") or []:
                if x.get("flatStatus") == "SALE":
                    continue  # allaqachon 2-qadamda (avail_flats) hisoblangan
                try:
                    rooms = int(x.get("flatRooms") or 0)
                except (TypeError, ValueError):
                    continue
                if rooms <= 0:
                    continue
                area = block_room_area.get((bname, rooms))
                if area is None:
                    # bu blok+xona-soni uchun sotuvda NAMUNA yo'q (hammasi sotilgan) —
                    # maydonni aniqlab bo'lmaydi, xavfsiz tomondan o'tkazib yuboramiz
                    # (undercounting total_count, lekin available_count aniq qoladi)
                    continue
                t = types.setdefault((rooms, area), {
                    "blocks": set(), "avail": 0, "total": 0, "floors": set(),
                    "sample": None, "sample_avail": None,
                })
                t["total"] += 1
                t["blocks"].add(bname)
    say(f"Chessboard tekshirildi ({n_chess} so'rov) — sotilgan birliklar hisoblandi.")

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
               f"{len(avail_flats)} sotuvda. Jami {1 + page + n_chess} so'rov.")
    say(summary)
    return summary


def maybe_auto_sync() -> None:
    """Ma'lumot eskirgan bo'lsa (LAYOUT_SYNC_TTL dan qari) — FONDA sync boshlaydi.
    Bloklamaydi: chaqiruvchiga darhol qaytadi, yangi ma'lumot keyingi chaqiruvlarga
    tayyor bo'ladi. Parallel sync bo'lmasligi uchun lock bor.

    DIQQAT: ENDI so'rov yo'lidan (`/api/layouts/`) chaqirilmaydi (4.4-tuzatish) —
    lekin cron/admin tugmasi shu funksiyani ishlatishi mumkin bo'lgani uchun
    muvaffaqiyatsizlik-backoff saqlanadi: ketma-ket urinishlar Uysot'ni "urib"
    yubormasin (`_RETRY_BACKOFF_SEC`, `latest is None` holatida ham qo'llanadi)."""
    global _last_attempt
    import os
    ttl = int(os.getenv("LAYOUT_SYNC_TTL", "3600"))  # sekund; default 1 soat
    latest = (Layout.objects.exclude(synced_at=None)
              .order_by("-synced_at").values_list("synced_at", flat=True).first())
    if latest and (timezone.now() - latest).total_seconds() < ttl:
        return
    now_m = time.monotonic()
    if now_m - _last_attempt < _RETRY_BACKOFF_SEC:
        return  # yaqinda muvaffaqiyatsiz urindik — hali qayta urinmaymiz
    if _sync_lock.locked():
        return  # allaqachon sync ketyapti

    def _run() -> None:
        global _last_attempt
        if not _sync_lock.acquire(blocking=False):
            return
        _last_attempt = time.monotonic()
        try:
            sync_all()
        except Exception:  # noqa: BLE001
            log.exception("Avto-sync xatosi (kamida %ds dan keyin qayta uriniladi)",
                          _RETRY_BACKOFF_SEC)
        finally:
            _sync_lock.release()

    threading.Thread(target=_run, daemon=True, name="layout-auto-sync").start()
    log.info("Avto-sync fonda boshlandi (ma'lumot %s dan eski).",
             f"{ttl}s" if latest else "yo'q")
