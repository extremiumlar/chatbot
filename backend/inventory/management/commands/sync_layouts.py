"""Uysot showroom API'dan xonadon TURLARINI (planirovka turlari) sync qiladi.

Ishlatilishi:
    python manage.py sync_layouts

Asosiy mantiq inventory/services.py da (views dagi avto-sync ham o'shani chaqiradi).
Diqqat: yuklangan planirovka rasmi, "is_active" va "izoh" — sync TEGMAYDI.
~220 ta so'rov qiladi (bir necha soniya).
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
