"""knowledge_base/*.md fayllarini KnowledgeSection jadvaliga import qiladi.

Ishlatilishi:
    python manage.py import_kb           # jadval bo'sh bo'lsa import qiladi
    python manage.py import_kb --force   # mavjud bo'limlarni O'CHIRIB, qaytadan

Bir martalik ko'chirish uchun: shundan keyin bilim bazasi admin panelda
tahrirlanadi ("Bilim bazasi" bo'limi), .md fayllar esa zaxira/fallback bo'lib
qoladi (backend ishlamasa bot ularni o'qiydi).
"""
from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from inventory.models import KnowledgeSection

# Tartib bot config.KB_FILES bilan bir xil bo'lishi kerak
KB_FILES = ["nurli_diyor.md", "shartnoma_shartlari.md", "hudud_atrof.md"]


class Command(BaseCommand):
    help = "knowledge_base/*.md fayllarini bilim bazasi jadvaliga ko'chiradi"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true",
                            help="Mavjud bo'limlarni o'chirib, qaytadan import qiladi")

    def handle(self, *args, **options):
        if KnowledgeSection.objects.exists():
            if not options["force"]:
                self.stderr.write(
                    "Jadvalda bo'limlar bor. Qaytadan import: --force "
                    "(DIQQAT: admin qilgan tahrirlar o'chadi!)")
                return
            KnowledgeSection.objects.all().delete()
            self.stdout.write("Eski bo'limlar o'chirildi (--force).")

        kb_dir = Path(settings.BASE_DIR).parent / "knowledge_base"
        n = 0
        for order, name in enumerate(KB_FILES):
            path = kb_dir / name
            if not path.exists():
                self.stderr.write(f"Topilmadi: {path}")
                continue
            content = path.read_text(encoding="utf-8").strip()
            title = name.removesuffix(".md").replace("_", " ").capitalize()
            KnowledgeSection.objects.create(
                title=title, content=content, order=order, is_active=True)
            self.stdout.write(f"  + {title} ({len(content):,} belgi)")
            n += 1
        self.stdout.write(self.style.SUCCESS(f"{n} bo'lim import qilindi."))
