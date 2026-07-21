"""Uysot showroom API'dan xonadon TURLARINI (planirovka turlari) sync qiladi.

Ishlatilishi:
    python manage.py sync_layouts

Cron/systemd timer bilan rejalashtiring (deploy/nurli-sync.timer namunasi) yoki
admin panelda "Hozir sync qilish" tugmasini bosing (LayoutAdmin). ENDI so'rov
yo'lidan (`/api/layouts/`) AVTOMATIK chaqirilmaydi (4.4-tuzatish) — begona
so'rov Uysot'ga zanjir chaqiruvlarini boshlab yubormasin.

Diqqat: yuklangan planirovka rasmi, "is_active" va "izoh" — sync TEGMAYDI.
~47 ta so'rov qiladi (ilgari ~257 edi — N+1 muammosi hal qilindi, services.py'ga qarang).
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from inventory import services


class Command(BaseCommand):
    help = "Uysot showroom API'dan xonadon turlarini sync qiladi"

    def handle(self, *args, **options):
        try:
            summary = services.sync_all(progress=self.stdout.write)
        except Exception as e:  # noqa: BLE001
            self.stderr.write(str(e))
            return
        self.stdout.write(self.style.SUCCESS(
            f"{summary} Planirovka rasmini admin paneldan yuklang."))
