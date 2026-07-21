"""Uysot showroom API — TO'G'RIDAN-TO'G'RI Uysot bilan gaplashadigan qism.

DIQQAT (4.3-arxitektura tuzatishi): bot javob yo'lida bu modul ENDI ISHLATILMAYDI.
Ilgari `inventory_summary()` shu yerdan to'g'ridan-to'g'ri Uysot'ga so'rov yuborardi,
`backend.layouts_with_image()` esa Django `Layout` jadvalidan (sync qilingan) —
ikkalasi mustaqil manba bo'lgani uchun ba'zan mos kelmasdi (masalan jonli inventar
"1 ta 1-xonali" desa, planirovka 3 turni yuborardi). Endi YAGONA manba —
`uysot/backend.py::inventory_summary()` — Layout jadvalidan, planirovka bilan bir xil.

Bu modul (to'g'ridan-to'g'ri Uysot chaqiruvlari) diagnostika/qo'lda tekshirish
uchun qoldirilgan (`python -m uysot.showroom`) va kelajakda PDF-planirovka
(narx-tozalangan, `flat_plan_pdf`) muqobil yo'l sifatida ishlatilishi mumkin —
hozircha userbot.py rasm-albom yo'lini ishlatadi (backend.layouts_with_image).
"""
from __future__ import annotations

import json
import logging
import re
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


def _rng(vals, fmt) -> str:
    lo, hi = min(vals), max(vals)
    return fmt(lo) if lo == hi else f"{fmt(lo)}–{fmt(hi)}"


def inventory_summary() -> str:
    """Botning system-prompt'iga qo'shiladigan ixcham jonli inventar xulosasi.

    DIQQAT: bu yerda NARX ATAYIN YO'Q — kompaniya siyosati bo'yicha bot mijozga
    narx aytmaydi (narx so'ralsa ofisga taklif qiladi). Ma'lumot promptga
    kirmagani uchun model uni "bilib qolib" aytib yuborishi ham mumkin emas.
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
        f"{len(comm)} tijorat).",
    ]

    if apts:
        lines.append("\nKVARTIRALAR (xona turi bo'yicha, qaysi blokda nechta qolgani):")
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
                floors = _rng([f["floor"] for f in bi], lambda v: f"{v:g}")
                lines.append(
                    f"   - {block}-blok: {len(bi)} ta | {area} m² | {floors}-qavat"
                )

    if comm:
        area = _rng([f["area"] for f in comm], lambda v: f"{v:g}")
        lines.append(
            f"\nTIJORAT (do'kon/noturar joy, asosan 1-qavat) — {len(comm)} ta | {area} m²"
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


# --- PDF'dan narxni o'chirish (kompaniya siyosati: bot narx aytmaydi) ---
# API PDF'ni har doim narx varag'i bilan generatsiya qiladi (buni o'chiradigan
# parametri yo'q — ShourumPdfRequest tekshirilgan). Shuning uchun narxlarni
# lokalda CHINAKAM o'chiramiz (redaction): shunchaki ustini yopish emas —
# matn PDF'dan butunlay olib tashlanadi (nusxalab ham olib bo'lmaydi).

# O'chiriladigan yorliq iboralari (normalizatsiyadan keyin solishtiriladi)
_PRICE_LABELS = [
    ("umumiy", "narxi"),
    ("boshlangich", "tolov"),
    ("sotuv", "summasi"),
    ("chegirma", "summasi"),
    ("oylik", "tolov"),
    ("foizi",),
    ("muddat",),   # aynan "muddat" tokeni ("Amal qilish muddati" footeriga tegmaydi)
]


def _norm_token(word: str) -> str:
    """kichik harf + harf-raqamdan boshqasini olib tashlash: so'm/so`m -> som."""
    return re.sub(r"[^a-z0-9.%()+]", "", word.lower())


def _is_money_token(tok: str) -> bool:
    return tok.endswith("som") or tok.endswith("%") or tok == "oy"


def _find_price_leaks(text: str) -> list[str]:
    """Matndan narx izlarini qidiradi (tozalash sifatini tekshirish uchun)."""
    leaks = []
    for line in text.splitlines():
        n = re.sub(r"[^a-z0-9.% ]", "", line.lower())
        if re.search(r"\d{3}", n) and ("som" in n.replace(" ", "") or "%" in n):
            leaks.append(line.strip())
        elif any(" ".join(p) in n for p in
                 (("umumiy", "narxi"), ("boshlangich", "tolov"), ("sotuv", "summasi"),
                  ("oylik", "tolov"), ("chegirma", "summasi"))):
            leaks.append(line.strip())
    return leaks


def _strip_prices_from_pdf(pdf_bytes: bytes) -> bytes:
    """PDF'dagi barcha narx yorliqlari va summalarini o'chiradi.

    Saqlanadi: maydon (m.kv), xona soni, blok/qavat/xonadon raqami, reja rasmi,
    brend va aloqa ma'lumotlari. O'chadi: umumiy narx, boshlang'ich to'lov, foiz,
    chegirma, sotuv summasi, muddat, oylik to'lov (yorliqlari bilan birga).
    Tozalashдан keyin tekshiradi — narx qolgan bo'lsa xato ko'taradi (bunday PDF
    mijozga KETMAYDI)."""
    import fitz  # PyMuPDF — faqat shu yerda kerak (import yengil qolsin)

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    for page in doc:
        words = page.get_text("words")  # (x0, y0, x1, y1, matn, block, line, word_no)
        lines: dict[tuple, list] = {}
        for w in words:
            lines.setdefault((w[5], w[6]), []).append(w)

        rects = []
        for ws in lines.values():
            ws.sort(key=lambda w: w[7])
            toks = [_norm_token(w[4]) for w in ws]

            # 1) Yorliqlar — faqat mos so'zlar o'chadi ("Maydoni" yonida tursa ham qoladi)
            for phrase in _PRICE_LABELS:
                for i in range(len(toks) - len(phrase) + 1):
                    if tuple(toks[i:i + len(phrase)]) == phrase:
                        rects.extend(fitz.Rect(w[:4]) for w in ws[i:i + len(phrase)])

            # 2) Pul qatorlari (ichida so'm/%/oy bor): maydon qismi (m.kv gacha) qoladi,
            #    qolgan hammasi o'chadi
            if any(_is_money_token(t) for t in toks):
                start = 0
                for i, t in enumerate(toks):
                    if t in ("m.kv", "mkv", "m.kv."):
                        start = i + 1
                rects.extend(fitz.Rect(w[:4]) for w in ws[start:])

        for r in rects:
            page.add_redact_annot(r)
        if rects:
            # rasmlarga tegmaymiz (reja chizmasi saqlanadi)
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

    out = doc.tobytes(garbage=3, deflate=True)
    text_after = "\n".join(p.get_text() for p in doc)
    doc.close()

    leaks = _find_price_leaks(text_after)
    if leaks:
        raise RuntimeError(f"PDF tozalashdan keyin ham narx qoldi: {leaks[:3]}")
    return out


def flat_plan_pdf(flat: dict) -> bytes:
    """Bitta xonadon uchun shourum PDF (planirovka) baytlarini qaytaradi.
    Narx ma'lumotlari yuborishdan oldin PDF'dan o'chiriladi (kompaniya siyosati).
    Tozalab bo'lmasa xato ko'taradi — narxli PDF mijozga chiqib ketmaydi."""
    body = {
        "flatId": flat["id"],
        "delay": int(flat.get("delay") or 0),
        "repaired": False,
        "discount": False,
        "clientPaymentAmount": float(flat.get("prePayment") or 0),
    }
    raw = _request_raw("POST", "/flat-shourum-pdf", body)
    return _strip_prices_from_pdf(raw)


if __name__ == "__main__":
    print(inventory_summary())
    print("\n--- Planirovka turlari ---")
    for g in list_layouts():
        print(f"{g['rooms']} xona, {g['area']} m² | bloklar {g['blocks']} | "
              f"{g['count']} ta | namuna flatId={g['flat']['id']}")
