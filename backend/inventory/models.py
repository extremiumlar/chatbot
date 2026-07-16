"""Nurli Diyor xonadon turlari (planirovka turlari).

Har bir yozuv — bitta xonadon TURI (xona soni + maydon bo'yicha).
Ma'lumot Uysot showroom API'dan sync qilinadi; planirovka RASMINI esa
admin panelдан qo'lda yuklaysiz (Uysot'da haqiqiy chizma yo'q).
Bot shu jadvaldan o'qiydi (inventar + rasm).
"""
from django.db import models


class Layout(models.Model):
    rooms = models.IntegerField("Xona soni")
    area = models.DecimalField("Maydon (m²)", max_digits=6, decimal_places=1)

    # Uysot API'dan sync qilinadigan ma'lumot
    blocks = models.CharField("Bloklar", max_length=100, blank=True,
                              help_text="Masalan: 3, 4, 5")
    available_count = models.IntegerField("Sotuvda (qolgan)", default=0)
    total_count = models.IntegerField("Jami (sotilgan bilan)", default=0)
    sample_flat_id = models.BigIntegerField("Namuna flat ID", null=True, blank=True)
    min_floor = models.IntegerField("Eng past qavat", null=True, blank=True)
    max_floor = models.IntegerField("Eng baland qavat", null=True, blank=True)

    # Qo'lda boshqariladigan qism — ikkalasi ham IXTIYORIY (bittasi bo'lsa ham botда ishlatiladi)
    planirovka = models.ImageField("Planirovka rasmi (2D)", upload_to="planirovka/",
                                   null=True, blank=True)
    planirovka_3d = models.ImageField("Planirovka rasmi (3D)", upload_to="planirovka_3d/",
                                      null=True, blank=True)
    is_active = models.BooleanField("Botда ko'rsatilsinmi", default=True)
    note = models.CharField("Izoh", max_length=255, blank=True)

    synced_at = models.DateTimeField("Oxirgi sync", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Xonadon turi"
        verbose_name_plural = "Xonadon turlari"
        unique_together = ("rooms", "area")
        ordering = ("rooms", "area")

    def __str__(self) -> str:
        return f"{self.rooms} xonali — {self.area} m²"

    @property
    def has_image(self) -> bool:
        return bool(self.planirovka or self.planirovka_3d)


class KnowledgeSection(models.Model):
    """Bot javob beradigan BILIM BAZASI bo'limi (markdown matn).

    Bot barcha faol bo'limlarni tartib bo'yicha birlashtirib, har javobda
    to'liq modelga beradi. Admin shu yerdan faktlarni ko'radi va tahrirlaydi;
    o'zgarish botga keshi yangilanganda (BACKEND_CACHE_TTL, ~5 daqiqa) yetadi.

    DIQQAT: rasmiy m² NARX o'zgarsa faqat shu yerni emas, bot kodidagi
    deterministik himoyani ham yangilash kerak (knowledge/price_guard.py va
    answer.py dagi narx qoidasi) — aks holda bot yangi narxni aytolmaydi.
    """
    title = models.CharField("Sarlavha", max_length=120)
    content = models.TextField(
        "Matn (markdown)",
        help_text="Bot shu matnni o'qiydi. Fakt qo'shish/o'zgartirish shu yerda.")
    order = models.IntegerField("Tartib", default=0,
                                help_text="Kichik raqam birinchi keladi")
    is_active = models.BooleanField("Botga berilsinmi", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField("Oxirgi tahrir", auto_now=True)

    class Meta:
        verbose_name = "Bilim bo'limi"
        verbose_name_plural = "Bilim bazasi (bot faktlari)"
        ordering = ("order", "id")

    def __str__(self) -> str:
        return self.title
