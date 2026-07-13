"""Uysot showroom (inventar) API — Nurli Diyor jonli xonadonlari.

Bu API real vaqtда qaysi blokda qanday xonadon SOTUVDA (qolgan) ekanini,
maydoni, narxi va 1 m² narxini beradi. Bot shu ma'lumot asosida aniq javob beradi.

Natija ~10 daqiqaga keshlanadi (har xabarда API chaqirmaslik uchun).
API ishlamasa — bot umumiy bilim bazasiga tayanadi (jim qolmaydi).
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from collections import defaultdict

import config

log = logging.getLogger("showroom")

# {kalit: (timestamp, data)}
_cache: dict[str, tuple[float, object]] = {}


def _request(method: str, path: str, body: dict | None = None) -> dict:
    url = f"{config.UYSOT_SHOWROOM_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Auth", config.UYSOT_SHOWROOM_TOKEN)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_all_flats(page_size: int = 200, max_pages: int = 5) -> list[dict]:
    """Barcha sahifalarni yig'adi. API javobida totalPages bo'lsa unga tayanamiz;
    bo'lmasa to'liq bo'lmagan sahifa kelguncha davom etamiz. Xato bo'lsa — yig'ilgan
    qismini qaytaramiz (bot yiqilmasin). max_pages — cheksiz siklga qarshi himoya."""
    all_flats: list[dict] = []
    page = 1
    while page <= max_pages:
        try:
            res = _request("POST",
                           f"/block/get-all-flat-by-filter/{config.UYSOT_HOUSE_ID}",
                           {"page": page, "size": page_size})
        except Exception as e:  # noqa: BLE001
            log.warning("Showroom %d-sahifada xato: %s (yig'ilgan %d birlik qaytadi)",
                        page, e, len(all_flats))
            break
        data = res.get("data") or {}
        batch = data.get("data") or []
        all_flats.extend(batch)

        total_pages = data.get("totalPages")
        if total_pages is not None:
            if page >= total_pages:
                break
        elif len(batch) < page_size:   # total yo'q — kam kelsa oxiri
            break
        page += 1
    else:
        log.warning("Showroom: max_pages (%d) chegarasiga yetildi — inventar to'liq "
                    "bo'lmasligi mumkin.", max_pages)
    return all_flats


def get_available_flats(force: bool = False) -> list[dict]:
    """Hozir sotuvdagi (qolgan) barcha xonadonlar ro'yxati (keshlangan, sahifalab yig'iladi)."""
    now = time.time()
    hit = _cache.get("flats")
    if not force and hit and now - hit[0] < config.UYSOT_CACHE_TTL:
        return hit[1]  # type: ignore[return-value]

    flats = _fetch_all_flats()
    _cache["flats"] = (now, flats)
    return flats


def _is_commercial(flat: dict) -> bool:
    """"M" bilan boshlanadigan raqamli birliklar — do'kon/tijorat (kvartira emas)."""
    return str(flat.get("number", "")).upper().startswith("M")


def _mln(x: float) -> str:
    return f"{x / 1_000_000:.0f}"


def _mln1(x: float) -> str:
    s = f"{x / 1_000_000:.1f}"
    return s.rstrip("0").rstrip(".")


def _rng(vals, fmt) -> str:
    lo, hi = min(vals), max(vals)
    return fmt(lo) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"


def inventory_summary() -> str:
    """Botning system-prompt'iga qo'shiladigan ixcham jonli inventar xulosasi.
    API ishlamasa bo'sh satr qaytaradi (bot umumiy bilimga tayanadi)."""
    try:
        flats = get_available_flats()
    except Exception as e:  # noqa: BLE001
        log.warning("Showroom API ishlamadi: %s", e)
        return ""

    if not flats:
        return "Hozircha showroom bo'yicha sotuvdagi xonadon topilmadi (sotuv bo'limi aniq aytadi)."

    apts = [f for f in flats if not _is_commercial(f)]
    comm = [f for f in flats if _is_commercial(f)]

    lines: list[str] = [
        f"Hozir sotuvda jami {len(flats)} ta birlik ({len(apts)} kvartira, "
        f"{len(comm)} tijorat). Narxlar — list narx (chegirmasiz).",
    ]

    if apts:
        lines.append("\nKVARTIRALAR (xona turi bo'yicha):")
        by_room: dict[str, list[dict]] = defaultdict(list)
        for f in apts:
            by_room[str(f["rooms"])].append(f)
        for rooms in sorted(by_room, key=lambda r: int(r) if r.isdigit() else 99):
            items = by_room[rooms]
            lines.append(f"• {rooms} xonali — jami {len(items)} ta:")
            by_block: dict[str, list[dict]] = defaultdict(list)
            for f in items:
                by_block[str(f["block"])].append(f)
            for block in sorted(by_block, key=lambda b: int(b) if b.isdigit() else 99):
                bi = by_block[block]
                area = _rng([f["area"] for f in bi], lambda v: f"{v:g}")
                price = _rng([f["price"] for f in bi], _mln)
                ppa = _rng([f["pricePerArea"] for f in bi], _mln1)
                floors = _rng([f["floor"] for f in bi], lambda v: f"{v:g}")
                lines.append(
                    f"   - {block}-blok: {len(bi)} ta | {area} m² | {floors}-qavat "
                    f"| narx {price} mln so'm | {ppa} mln so'm/m²"
                )

    if comm:
        area = _rng([f["area"] for f in comm], lambda v: f"{v:g}")
        price = _rng([f["price"] for f in comm], _mln)
        ppa = _rng([f["pricePerArea"] for f in comm], _mln1)
        lines.append(
            f"\nTIJORAT (do'kon/noturar joy, asosan 1-qavat) — {len(comm)} ta | "
            f"{area} m² | narx {price} mln so'm | {ppa} mln so'm/m²"
        )

    return "\n".join(lines)


def _request_raw(method: str, path: str, body: dict | None = None) -> bytes:
    """JSON emas, xom baytlar qaytaradigan so'rov (masalan PDF yuklab olish uchun)."""
    url = f"{config.UYSOT_SHOWROOM_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("X-Auth", config.UYSOT_SHOWROOM_TOKEN)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read()


def _has_plan(flat: dict) -> bool:
    return any(g.get("position") == "FLAT_PLAN" for g in (flat.get("gallery") or []))


def list_layouts() -> list[dict]:
    """Har xil planirovka turlari (xona soni + maydon bo'yicha guruhlangan).
    Har turdan bitta namuna xonadon (PDF olish uchun) va bloklar ro'yxati qaytadi.
    [{'rooms', 'area', 'blocks': [...], 'count', 'flat': {...}}]"""
    flats = [f for f in get_available_flats()
             if not _is_commercial(f) and _has_plan(f)]
    groups: dict[tuple, dict] = {}
    for f in flats:
        key = (f["rooms"], round(f["area"], 1))
        g = groups.get(key)
        if g is None:
            g = {"rooms": f["rooms"], "area": round(f["area"], 1),
                 "blocks": set(), "count": 0, "flat": f,
                 "price_min": f["price"], "price_max": f["price"]}
            groups[key] = g
        g["blocks"].add(str(f["block"]))
        g["count"] += 1
        g["price_min"] = min(g["price_min"], f["price"])
        g["price_max"] = max(g["price_max"], f["price"])
    out = []
    for key in sorted(groups, key=lambda k: (int(k[0]) if str(k[0]).isdigit() else 99, k[1])):
        g = groups[key]
        g["blocks"] = sorted(g["blocks"], key=lambda b: int(b) if b.isdigit() else 99)
        out.append(g)
    return out


def flat_plan_pdf(flat: dict) -> bytes:
    """Bitta xonadon uchun shourum PDF (planirovka + narx) baytlarini qaytaradi."""
    body = {
        "flatId": flat["id"],
        "delay": int(flat.get("delay") or 0),
        "repaired": False,
        "discount": False,
        "clientPaymentAmount": float(flat.get("prePayment") or 0),
    }
    return _request_raw("POST", "/flat-shourum-pdf", body)


if __name__ == "__main__":
    print(inventory_summary())
    print("\n--- Planirovka turlari ---")
    for g in list_layouts():
        print(f"{g['rooms']} xona, {g['area']} m² | bloklar {g['blocks']} | "
              f"{g['count']} ta | namuna flatId={g['flat']['id']}")
