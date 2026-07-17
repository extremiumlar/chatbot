"""Narx kalkulyatori — Uysot'dagi narx belgilash tizimining nusxasi (admin uchun).

Uysot showroom API'dan JONLI tekshiruv bilan aniqlangan bosqichlar
(2026-07-16, flat-shourum-pdf hisob-varag'i bilan raqamma-raqam solishtirilgan):

  1) Bazaviy narx   = xonadon maydoni x m2 tarif (qavatga bog'liq, API beradi)
  2) Terrasa        = terrasa maydoni x terrasa tarifi (alohida, hozir 3 mln/m2)
  3) Ta'mir opsiyasi= tanlansa: xonadon maydoni x TA'MIR tarifi (+3 mln/m2);
                      terrasada o'zining pricePerAreaRepaired tarifi ishlaydi
  4) Chegirma       = jami narxdan % yoki qat'iy summa (Uysot dvijogida bor,
                      lekin kompaniya jadval sozlamagani uchun u yerda doim 0 --
                      bizda qo'lda kiritiladi)
  5) To'lov rejasi  = boshlang'ich to'lov + qoldiq muddatga teng bo'linadi,
                      USTAMA FOIZSIZ (36/24/12 oyda tekshirilgan).
                      DIQQAT: Uysot API prePayment maydonida 20% ko'rsatadi,
                      lekin KOMPANIYA SIYOSATI — boshlang'ich har doim qat'iy
                      30 mln so'm (shuning uchun default shu).

DIQQAT: bu hisob faqat ADMIN (xodimlar) uchun. Bot mijozga umumiy summa
aytmaydi (price_guard siyosati) -- bu modul bot javob yo'liga ulanmagan.
"""
from __future__ import annotations

import json
import time
import urllib.request

from django.conf import settings

# Cloudflare python-so'rovlarni bloklamasligi uchun (CRM hostida 1010 xato kuzatilgan)
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NurliDiyorAdmin/1.0"

# Zaxira qiymatlar (baza hali tayyor bo'lmasa). Asosiy manba — admin paneldagi
# "Narx sozlamalari" (PricingConfig) va "Chegirma zinapoyasi" (DiscountTier).
FALLBACK_REPAIR_PER_M2 = 3_000_000.0   # Uysot PDF bilan tekshirilgan
FALLBACK_PREPAYMENT = 30_000_000.0     # kompaniya siyosati: standart 30 mln


def get_config() -> dict:
    """Admin sozlamalari: standart boshlang'ich va ta'mir tarifi."""
    try:
        from .models import PricingConfig
        cfg = PricingConfig.get()
        return {"default_prepayment": float(cfg.default_prepayment),
                "repair_price_per_m2": float(cfg.repair_price_per_m2)}
    except Exception:  # noqa: BLE001 - migratsiya o'tmagan bo'lsa ham ishlashi uchun
        return {"default_prepayment": FALLBACK_PREPAYMENT,
                "repair_price_per_m2": FALLBACK_REPAIR_PER_M2}


def tier_discount_percent(prepay_share_percent: float) -> float:
    """Chegirma zinapoyasi: boshlang'ich ulushi (umumiy narxga %) shu ulushga
    yetgan ENG KATTA faol pog'onaning chegirma foizini qaytaradi (yo'q bo'lsa 0)."""
    try:
        from .models import DiscountTier
        tier = (DiscountTier.objects.filter(
                    is_active=True,
                    min_prepayment_percent__lte=prepay_share_percent)
                .order_by("-min_prepayment_percent").first())
        return float(tier.discount_percent) if tier else 0.0
    except Exception:  # noqa: BLE001
        return 0.0

_cache: tuple[float, list[dict]] | None = None
_CACHE_TTL = 600  # 10 daqiqa


def get_available_flats(force: bool = False) -> list[dict]:
    """Sotuvdagi xonadonlar (Uysot showroom, keshlangan). API ishlamasa []."""
    global _cache
    now = time.time()
    if not force and _cache and now - _cache[0] < _CACHE_TTL:
        return _cache[1]
    flats: list[dict] = []
    try:
        page = 1
        while True:
            body = json.dumps({"page": page, "size": 100}).encode()
            req = urllib.request.Request(
                f"{settings.UYSOT_SHOWROOM_BASE}/block/get-all-flat-by-filter/"
                f"{settings.UYSOT_HOUSE_ID}", data=body, method="POST")
            req.add_header("X-Auth", settings.UYSOT_SHOWROOM_TOKEN)
            req.add_header("Content-Type", "application/json")
            req.add_header("User-Agent", _UA)
            with urllib.request.urlopen(req, timeout=30) as resp:
                d = json.loads(resp.read().decode("utf-8"))["data"]
            flats.extend(d.get("data") or [])
            if page >= int(d.get("totalPages") or 1):
                break
            page += 1
        flats.sort(key=lambda f: (_is_commercial(f), int(f.get("rooms") or 0),
                                  float(f.get("area") or 0), str(f.get("block")),
                                  int(f.get("floor") or 0)))
        _cache = (now, flats)
    except Exception:  # noqa: BLE001 - API yotgan bo'lsa eski kesh yoki bo'sh
        if _cache:
            return _cache[1]
    return flats


def _is_commercial(flat: dict) -> bool:
    """"M" raqamli xonadonlar aslida tijorat (do'kon)."""
    return str(flat.get("number") or "").upper().startswith("M")


def flat_label(flat: dict) -> str:
    kind = "Do'kon" if _is_commercial(flat) else f"{flat['rooms']} xonali"
    t = flat.get("terrace")
    terr = f", terrasa {t['area']:g} m²" if t else ""
    return (f"{kind} — {flat['area']:g} m², {flat['block']}-blok, "
            f"{flat['floor']}-qavat, №{flat['number']}{terr}")


def calculate(*, area: float, price_per_m2: float,
              terrace_area: float = 0.0, terrace_price_per_m2: float = 0.0,
              repaired: bool = False, repair_price_per_m2: float | None = None,
              discount_percent: float = 0.0, discount_sum: float = 0.0,
              prepayment_percent: float | None = None,
              prepayment_sum: float | None = None,
              months: int = 0) -> dict:
    """Uysot bosqichlari bo'yicha to'liq hisob. Hammasi so'mda (float).

    Chegirma: % va qat'iy summa BIRGA berilsa — ikkalasi ham qo'llanadi
    (avval %, keyin summa). Boshlang'ich: sum berilsa o'sha; % berilsa
    sotuv summasidan; ikkalasi ham yo'q — admin sozlamasidagi standart
    (30 mln)."""
    cfg = get_config()
    if repair_price_per_m2 is None:
        repair_price_per_m2 = cfg["repair_price_per_m2"]

    base = area * price_per_m2                                   # 1-bosqich
    terrace = terrace_area * terrace_price_per_m2                # 2-bosqich
    repair = area * repair_price_per_m2 if repaired else 0.0     # 3-bosqich
    total = base + terrace + repair

    disc = total * (discount_percent / 100.0) + discount_sum     # 4-bosqich
    disc = min(disc, total)
    sale = total - disc

    if prepayment_sum is None:                                   # 5-bosqich
        if prepayment_percent is not None:
            prepayment_sum = sale * (prepayment_percent / 100.0)
        else:
            prepayment_sum = cfg["default_prepayment"]           # standart 30 mln
    prepayment_sum = min(prepayment_sum, sale)
    prepay_pct = (prepayment_sum / sale * 100.0) if sale else 0.0
    remainder = sale - prepayment_sum
    monthly = (remainder / months) if months > 0 else 0.0

    return {
        "area": area, "price_per_m2": price_per_m2, "base": base,
        "terrace_area": terrace_area, "terrace_price_per_m2": terrace_price_per_m2,
        "terrace": terrace,
        "repaired": repaired, "repair_price_per_m2": repair_price_per_m2,
        "repair": repair,
        "total": total,
        "discount": disc, "discount_percent_effective": (disc / total * 100.0) if total else 0.0,
        "sale": sale,
        "prepayment": prepayment_sum, "prepayment_percent": prepay_pct,
        "remainder": remainder, "months": months, "monthly": monthly,
    }


def calculate_for_flat(flat: dict, *, repaired: bool = False,
                       discount_percent: float = 0.0, discount_sum: float = 0.0,
                       prepayment_percent: float | None = None,
                       prepayment_sum: float | None = None,
                       months: int = 0) -> dict:
    """Uysot'dagi tayyor xonadon uchun hisob (tariflar API'dan olinadi)."""
    t = flat.get("terrace") or {}
    t_price = (t.get("pricePerAreaRepaired") if repaired else t.get("pricePerArea")) or 0
    return calculate(
        area=float(flat["area"]), price_per_m2=float(flat["pricePerArea"]),
        terrace_area=float(t.get("area") or 0), terrace_price_per_m2=float(t_price),
        repaired=repaired,
        discount_percent=discount_percent, discount_sum=discount_sum,
        prepayment_percent=prepayment_percent, prepayment_sum=prepayment_sum,
        months=months,
    )


def fetch_shourum_pdf(flat_id: int, *, months: int, prepayment_sum: float,
                      repaired: bool) -> bytes:
    """Uysot'ning rasmiy hisob-varaq PDF'i (xodim yuklab olishi uchun)."""
    body = json.dumps({
        "flatId": flat_id, "delay": months, "repaired": repaired,
        "discount": False, "clientPaymentAmount": prepayment_sum,
    }).encode()
    req = urllib.request.Request(
        f"{settings.UYSOT_SHOWROOM_BASE}/flat-shourum-pdf", data=body, method="POST")
    req.add_header("X-Auth", settings.UYSOT_SHOWROOM_TOKEN)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", _UA)
    with urllib.request.urlopen(req, timeout=40) as resp:
        return resp.read()
