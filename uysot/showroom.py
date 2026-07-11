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


def get_available_flats(force: bool = False) -> list[dict]:
    """Hozir sotuvdagi (qolgan) barcha xonadonlar ro'yxati (keshlangan)."""
    now = time.time()
    hit = _cache.get("flats")
    if not force and hit and now - hit[0] < config.UYSOT_CACHE_TTL:
        return hit[1]  # type: ignore[return-value]

    res = _request("POST", f"/block/get-all-flat-by-filter/{config.UYSOT_HOUSE_ID}",
                   {"page": 1, "size": 200})
    flats = (res.get("data") or {}).get("data") or []
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


if __name__ == "__main__":
    print(inventory_summary())
