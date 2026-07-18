"""Menejerlar anketasi JSON'ini (bilim_dataset.json) QAEntry jadvaliga import qiladi.

Ishlatilishi:
    python manage.py import_qa ../bilim_dataset.json

Qoidalar:
  - (savol, javob) jufti bo'yicha upsert — qayta import dublikat yaratmaydi.
  - Bir savolga bir nechta rasmiy javob bo'lishi mumkin (ikkalasi ham saqlanadi).
  - Javobi "bilmayman" turidagi yozuvlar AVTOMATIK O'CHIQ (is_active=False) bo'ladi —
    bot "Bilmiman" deb javob berib qo'ymasligi uchun. Menejer javobni to'ldirib,
    admin panelda o'zi yoqadi.
  - Mavjud yozuvning qo'lda o'zgartirilgan is_active holatiga (agar yozuv o'zgarmagan
    bo'lsa) tegilmaydi.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from inventory.models import QAEntry

# Javob yo'qligini bildiruvchi matnlar (kichik harfda, lotin+kirill)
_UNKNOWN = {"bilmiman", "bilmadim", "bilmayman", "билмадим", "билмайман",
            "bilmadim.", "yo'q ma'lumot", ""}


def _is_unknown(javob: str) -> bool:
    return javob.strip().lower().rstrip(".") in _UNKNOWN


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


class Command(BaseCommand):
    help = "Anketa JSON (bilim_dataset.json) ni QAEntry jadvaliga import qiladi"

    def add_arguments(self, parser):
        parser.add_argument("path", help="JSON fayl yo'li")

    def handle(self, *args, **options):
        path = Path(options["path"])
        if not path.exists():
            raise CommandError(f"Fayl topilmadi: {path}")

        data = json.loads(path.read_text(encoding="utf-8"))
        entries = data.get("entries") if isinstance(data, dict) else data
        if not isinstance(entries, list):
            raise CommandError("JSON formati kutilmagan: 'entries' ro'yxati topilmadi.")

        created = updated = deactivated = skipped = 0
        for e in entries:
            savol = (e.get("savol") or "").strip()
            javob = (e.get("javob") or "").strip()
            if not savol:
                skipped += 1
                continue

            unknown = _is_unknown(javob)
            defaults = dict(
                kategoriya=(e.get("kategoriya") or "umumiy").strip() or "umumiy",
                sana_sezgir=bool(e.get("sana_sezgir")),
                qayta_tekshirish_kerak=bool(e.get("qayta_tekshirish_kerak")),
                yangilangan=_parse_date(e.get("yangilangan")),
            )
            obj, is_new = QAEntry.objects.get_or_create(
                savol=savol, javob=javob, defaults=defaults)
            if is_new:
                created += 1
                if unknown:
                    obj.is_active = False
                    obj.note = "Javob to'ldirilmagan (anketada 'bilmayman') — menejer to'ldirsin."
                    obj.save(update_fields=["is_active", "note"])
                    deactivated += 1
            else:
                # metama'lumotlarni yangilaymiz, admin qo'ygan is_active/notega tegmaymiz
                for k, v in defaults.items():
                    setattr(obj, k, v)
                obj.save(update_fields=list(defaults))
                updated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Import tugadi: {created} yangi, {updated} yangilangan, "
            f"{deactivated} o'chiq ('bilmayman'), {skipped} o'tkazildi. "
            f"Jami faol: {QAEntry.objects.filter(is_active=True).count()}"))
