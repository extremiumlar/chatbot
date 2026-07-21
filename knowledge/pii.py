"""Shaxsiy ma'lumot (PII) detektorlari — hozircha telefon raqamlari.

Nega kerak: master-reja PDF'idan pudratchi telefoni fakt bo'lib bazaga kirib,
har promptga chiqib yurgan edi. Endi ingest paytida ham (ingest.py), promptga
yig'ish paytida ham (answer.py) shu filtr qo'llanadi — telefonli fakt bazaga
yozilmaydi va yozilgan bo'lsa ham mijozga chiqmaydi.

Eslatma: bu filtr FAKTLARGA qo'llanadi. Bilim bazasidagi rasmiy kompaniya
raqami (KnowledgeSection/QA ichida) bunga tegishli emas — u fakt emas.
"""
from __future__ import annotations

import re

# +998 bilan boshlanadigan (7-10 raqam davomli) — bo'shliq/`-`lar olib tashlangan matnda
_RE_UZ_PHONE = re.compile(r"\+?998\d{7,10}")
# Umumiy guruhlangan ko'rinish: "97 444 00 88" yoki "90-123-45-67" kabi (xom matnda).
# Ajratkich sifatida bo'shliq HAM chiziqcha qabul qilinadi.
_RE_GROUPED_PHONE = re.compile(r"\+?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}\b")

# Telefon EMAS deb biladigan rasmiy raqamlar: kompaniya STIR'i 9 xonali bo'lgani
# uchun guruhlangan-telefon naqshiga to'g'ri kelib qoladi — uni istisno qilamiz
# (rasmiy QA'da mijoz rekvizit so'raganda chiqishi kerak).
ALLOWED_NON_PHONE_DIGITS = frozenset({"311781954"})


def contains_phone(text: str) -> bool:
    """Matnda telefon raqami borga o'xshasa True."""
    if not text:
        return False
    stripped = re.sub(r"[\s\-()]", "", text)
    if _RE_UZ_PHONE.search(stripped):
        return True
    for m in _RE_GROUPED_PHONE.finditer(text):
        digits = re.sub(r"\D", "", m.group(0))
        if digits in ALLOWED_NON_PHONE_DIGITS:
            continue          # STIR kabi rasmiy raqam — telefon emas
        return True
    return False
