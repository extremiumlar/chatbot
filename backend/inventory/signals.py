"""KnowledgeSection saqlanganda mos knowledge_base/*.md faylni avtomatik yangilaydi.

Nega kerak: `KnowledgeSection` (admin tahrirlaydi) — bilim bazasining YAGONA
haqiqat manbai; `.md` fayllar endi faqat zaxira (backend o'chib qolganda bot
o'shani o'qiydi, knowledge/answer.py::_load_knowledge_files). Bu signal bo'lmasa
admin panelda qilingan tahrir `.md` ga hech qachon tushmay, zaxira abadiy eskirib
qolardi (import_kb bir martalik ko'chirish, keyin sync yo'q edi).

Mapping: bo'lim sarlavhasi -> fayl nomi import_kb.py bilan BIR XIL qoidada
("Nurli diyor" -> "nurli_diyor.md"). Faqat import_kb.KB_FILES ro'yxatidagi
(botga tanish) fayllar yangilanadi — admin qo'shgan YANGI bo'lim hozircha
botning config.KB_FILES ro'yxatida bo'lmagani uchun avtomatik zaxiralanmaydi
(bu — bilingan cheklov, pastda logga yoziladi)."""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .management.commands.import_kb import KB_FILES
from .models import KnowledgeSection

log = logging.getLogger("inventory.kb_backup")


def _title_to_filename(title: str) -> str:
    """import_kb bilan BIR XIL qoida: "Nurli diyor" -> "nurli_diyor.md"."""
    return title.strip().lower().replace(" ", "_") + ".md"


@receiver(post_save, sender=KnowledgeSection)
def backup_knowledge_section(sender, instance: KnowledgeSection, **kwargs) -> None:
    filename = _title_to_filename(instance.title)
    if filename not in KB_FILES:
        log.info(
            "Bo'lim '%s' botning KB_FILES ro'yxatida yo'q (%s) — avtomatik "
            "zaxiralanmaydi. Botga tanishtirish uchun config.KB_FILES'ga qo'shing.",
            instance.title, filename)
        return
    kb_dir = Path(settings.BASE_DIR).parent / "knowledge_base"
    try:
        kb_dir.mkdir(parents=True, exist_ok=True)
        (kb_dir / filename).write_text(instance.content, encoding="utf-8")
        log.info("Zaxira yangilandi: knowledge_base/%s (%d belgi)",
                 filename, len(instance.content))
    except Exception:  # noqa: BLE001 - fayl yozilmasa ham admin ishlashda davom etsin
        log.exception("Zaxira faylini yozishda xato: %s", filename)
