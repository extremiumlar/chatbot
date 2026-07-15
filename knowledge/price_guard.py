"""Narx sizib chiqishiga qarshi DETERMINISTIK filtr (kod darajasidagi himoya).

Kompaniya siyosati: bot mijozga xonadonning UMUMIY (yakuniy) summasini,
boshlang'ich to'lov miqdorini va chegirma summasini aytmaydi — faqat rasmiy
m² tarif (8 990 000 / 8 490 000 so'm) va bandlikni aytadi.

Bu siyosat system-prompt qoidalari bilan ham himoyalangan, lekin prompt-darajali
himoya mo'rt (boshqa ta'riflash/til/model bilan buzilishi mumkin). Shu modul
LLM javobini Telegram'ga ketishidan OLDIN tekshiradi: taqiqlangan summa topilsa,
answer.py bir marta qayta so'raydi, bo'lmasa xavfsiz tayyor matn yuboradi.

Qoidalar:
  TAQIQLANADI (pul ko'rinishidagi katta sonlar):
    - guruhlangan 7+ xonali sonlar:  "557 380 000", "40.921.800", "915,000,000"
    - uzluksiz 7+ raqam:             "557380000"
    - N mln/million/млн (N >= 10):   "205 mln", "550 millionga yaqin"
    - har qanday mlrd/milliard/млрд: "1.2 mlrd"
  RUXSAT ETILADI (istisnolar):
    - rasmiy m² tarif har qanday formatda: 8 990 000 / 8490000 / 8.99 mln / 8,49 mln
    - O'zbekiston telefon raqamlari: +998901079792 (998 + 9 raqam)
    - kichik sonlar, maydonlar (62 m²), sanalar (2027), muddatlar (36 oy) — bu
      naqshlar 7 xonaga yetmagani uchun tabiiy o'tadi.
"""
from __future__ import annotations

import re

# Rasmiy m² tarifi — normalizatsiyadan (ajratkichlarni olib tashlash) keyingi ko'rinish.
# Yagona ruxsat etilgan "katta" summalar.
ALLOWED_TARIFF_DIGITS = frozenset({"8990000", "8490000"})
# "mln" yozuvidagi ruxsat etilgan tarif qiymatlari (8.99 mln = 8 990 000)
ALLOWED_MLN_VALUES = frozenset({8.49, 8.99})

# Javob almashtiriladigan xavfsiz matn (2-urinish ham leak bersa)
SAFE_PRICE_REPLY = (
    "Yakuniy summa chegirma va to'lov shartlariga qarab ofisda aniq hisoblab "
    "beriladi — ko'pincha bu siz kutgandan foydaliroq chiqadi 😊 Aniq hisob-kitob "
    "uchun ofisga tashrif buyuring yoki telefon raqamingizni qoldiring."
)

# Guruhlangan son: 1-3 raqam + kamida IKKITA "ajratkich + 3 raqam" bloki (>= 7 xona).
# Ajratkich: bo'shliq, NBSP, nuqta, vergul, apostrof.
_RE_GROUPED = re.compile(r"\d{1,3}(?:[   .,']\d{3}){2,}")
# Uzluksiz 7+ raqam
_RE_CONTIG = re.compile(r"\d{7,}")
# N mln/million/млн — qo'shimchalarga chidamli (millionga, mlndan, млнга ...)
_RE_MLN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:mln|million|млн)\w*", re.IGNORECASE)
# mlrd/milliard/млрд — har qanday qiymat taqiqlanadi
_RE_MLRD = re.compile(r"\d+(?:[.,]\d+)?\s*(?:mlrd|milliard|млрд)\w*", re.IGNORECASE)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def contains_forbidden_sum(text: str) -> list[str]:
    """Matnda taqiqlangan pul summalari bo'lsa, ularning ro'yxatini qaytaradi.
    Bo'sh ro'yxat = matn toza (yuborish mumkin)."""
    if not text:
        return []
    leaks: list[str] = []
    seen_spans: list[tuple[int, int]] = []

    # 1) Guruhlangan va uzluksiz katta sonlar
    for m in list(_RE_GROUPED.finditer(text)) + list(_RE_CONTIG.finditer(text)):
        start, end = m.span()
        # bir xil joyni ikki naqsh bilan ikki marta hisoblamaymiz
        if any(start < pe and ps < end for ps, pe in seen_spans):
            continue
        seen_spans.append((start, end))
        frag = m.group(0)
        d = _digits(frag)
        if len(d) < 7:
            continue                      # kichik son — xavfsiz
        if d in ALLOWED_TARIFF_DIGITS:
            continue                      # rasmiy m² tarif
        if d.startswith("998") and len(d) == 12:
            continue                      # O'zbekiston telefon raqami (+998 XX XXX XX XX)
        leaks.append(frag)

    # 2) "N mln" ko'rinishi (tarifdan boshqa, N >= 10 — umumiy summa belgisi)
    for m in _RE_MLN.finditer(text):
        try:
            val = float(m.group(1).replace(",", "."))
        except ValueError:
            continue
        if val in ALLOWED_MLN_VALUES:
            continue                      # 8.49 / 8.99 mln — tarif
        if val >= 10:
            leaks.append(m.group(0))

    # 3) "N mlrd" — har doim taqiqlangan
    for m in _RE_MLRD.finditer(text):
        leaks.append(m.group(0))

    return leaks
