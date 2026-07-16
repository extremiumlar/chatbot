"""Bot bilim bazasi (storage/knowledge.db) uchun Django modellari.

Bu jadvallarni bot o'zi yaratadi va boshqaradi (knowledge/db.py dagi SCHEMA).
Shuning uchun hamma model `managed = False` — Django migratsiya qilmaydi,
faqat mavjud jadvallarni o'qiydi/yozadi. Qaysi bazaga ulanishni kb/router.py
hal qiladi ('knowledge' bazasi -> storage/knowledge.db).

DIQQAT: bot bazasida sana ustunlari TEXT ("YYYY-MM-DD HH:MM:SS", lokal vaqt).
SQLite'dagi DEFAULT lar Django INSERT'ida ishlamaydi (Django hamma ustunni
o'zi yozadi), shuning uchun default'lar bu yerda Python darajasida berilgan.
"""
from datetime import datetime

from django.db import models


def _now() -> str:
    """Bot formatidagi lokal vaqt (knowledge/db.py dagi datetime('now','localtime'))."""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Document(models.Model):
    """Yuklangan manba fayl (PDF, matn, va h.k.) — `documents` jadvali."""
    id = models.AutoField(primary_key=True)
    filename = models.TextField("Fayl nomi")
    source_type = models.TextField("Manba turi", default="pdf",
                                   help_text="pdf | text | manual")
    title = models.TextField("Sarlavha", null=True, blank=True,
                             help_text="Claude bergan sarlavha/xulosa")
    summary = models.TextField("Qisqa mazmun", null=True, blank=True)
    num_pages = models.IntegerField("Sahifalar", null=True, blank=True)
    num_chunks = models.IntegerField("Bo'laklar", null=True, blank=True, default=0)
    file_hash = models.TextField("Fayl hash", unique=True, null=True, blank=True,
                                 help_text="Takror yuklashni oldini oladi")
    created_at = models.TextField("Yaratilgan", default=_now)

    class Meta:
        managed = False
        db_table = "documents"
        verbose_name = "Hujjat"
        verbose_name_plural = "Hujjatlar"
        ordering = ["-id"]

    def __str__(self):
        return self.title or self.filename


class Chunk(models.Model):
    """Hujjat matnining RAG bo'lagi — `chunks` jadvali.

    DIQQAT: bo'lak matni tahrirlansa Chroma'dagi embedding ESKICHA qoladi —
    semantik qidiruv yangi matnni ko'rmaydi. To'liq yangilash uchun:
    `python ingest.py --rebuild` (loyiha ildizida).
    """
    id = models.AutoField(primary_key=True)
    document = models.ForeignKey(Document, on_delete=models.CASCADE,
                                 db_column="document_id", verbose_name="Hujjat",
                                 related_name="chunks_set")
    chunk_index = models.IntegerField("Tartib raqami")
    page = models.IntegerField("Sahifa", null=True, blank=True)
    text = models.TextField("Matn")

    class Meta:
        managed = False
        db_table = "chunks"
        verbose_name = "Bo'lak (chunk)"
        verbose_name_plural = "Bo'laklar (chunks)"
        ordering = ["document_id", "chunk_index"]
        unique_together = [("document", "chunk_index")]

    def __str__(self):
        return f"#{self.pk} ({self.document_id}-hujjat, {self.chunk_index}-bo'lak)"


class Property(models.Model):
    """Uy / ob'ekt — tuzilgan sotuv ma'lumoti, `properties` jadvali."""
    id = models.AutoField(primary_key=True)
    document = models.ForeignKey(Document, on_delete=models.SET_NULL,
                                 db_column="document_id", verbose_name="Hujjat",
                                 null=True, blank=True)
    name = models.TextField("Nomi", null=True, blank=True)
    address = models.TextField("Manzil", null=True, blank=True)
    rooms = models.IntegerField("Xonalar", null=True, blank=True)
    area_m2 = models.FloatField("Maydoni (m²)", null=True, blank=True)
    floor = models.TextField("Qavat", null=True, blank=True)
    price = models.TextField("Narx", null=True, blank=True)
    build_stage = models.TextField("Qurilish bosqichi", null=True, blank=True)
    status = models.TextField("Holati", null=True, blank=True,
                              help_text="sotuvda | band | sotilgan")
    extra = models.TextField("Qo'shimcha", null=True, blank=True)
    created_at = models.TextField("Yaratilgan", default=_now)

    class Meta:
        managed = False
        db_table = "properties"
        verbose_name = "Uy / ob'ekt"
        verbose_name_plural = "Uylar / ob'ektlar"
        ordering = ["-id"]

    def __str__(self):
        return self.name or f"Ob'ekt #{self.pk}"


class Fact(models.Model):
    """Claude ajratgan aniq savol-javob fakti — `facts` jadvali."""
    id = models.AutoField(primary_key=True)
    document = models.ForeignKey(Document, on_delete=models.CASCADE,
                                 db_column="document_id", verbose_name="Hujjat",
                                 null=True, blank=True)
    category = models.TextField("Kategoriya", null=True, blank=True,
                                help_text="narx | qurilish | joylashuv | shartlar | umumiy ...")
    question = models.TextField("Tipik savol", null=True, blank=True)
    answer = models.TextField("Javob")
    created_at = models.TextField("Yaratilgan", default=_now)

    class Meta:
        managed = False
        db_table = "facts"
        verbose_name = "Fakt"
        verbose_name_plural = "Faktlar"
        ordering = ["category", "-id"]

    def __str__(self):
        return self.question or (self.answer[:60] if self.answer else f"Fakt #{self.pk}")


class Lead(models.Model):
    """Botga yozgan mijoz — `leads` jadvali."""
    id = models.AutoField(primary_key=True)
    telegram_id = models.IntegerField("Telegram ID", unique=True, null=True, blank=True)
    name = models.TextField("Ismi", null=True, blank=True)
    username = models.TextField("Username", null=True, blank=True)
    phone = models.TextField("Telefon", null=True, blank=True)
    first_seen = models.TextField("Birinchi murojaat", default=_now)
    last_seen = models.TextField("Oxirgi murojaat", default=_now)
    num_messages = models.IntegerField("Xabarlar soni", null=True, blank=True, default=0)

    class Meta:
        managed = False
        db_table = "leads"
        verbose_name = "Lid (mijoz)"
        verbose_name_plural = "Lidlar (mijozlar)"
        ordering = ["-last_seen"]

    def __str__(self):
        return self.name or self.username or f"Lid {self.telegram_id}"


class Message(models.Model):
    """Suhbat tarixi xabari — `messages` jadvali."""
    ROLE_CHOICES = [("user", "Mijoz"), ("assistant", "Bot")]

    id = models.AutoField(primary_key=True)
    telegram_id = models.IntegerField("Telegram ID")
    role = models.TextField("Kim yozgan", choices=ROLE_CHOICES)
    content = models.TextField("Matn")
    created_at = models.TextField("Vaqt", default=_now)

    class Meta:
        managed = False
        db_table = "messages"
        verbose_name = "Xabar"
        verbose_name_plural = "Xabarlar (suhbat tarixi)"
        ordering = ["-id"]

    def __str__(self):
        return f"{self.get_role_display()} ({self.telegram_id}): {self.content[:40]}"
