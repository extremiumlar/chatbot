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


class PricingConfig(models.Model):
    """Narx kalkulyatori sozlamalari (bitta yozuv). Admin paneldan o'zgartiriladi."""
    default_prepayment = models.DecimalField(
        "Standart boshlang'ich to'lov (so'm)", max_digits=15, decimal_places=0,
        default=30_000_000,
        help_text="Kalkulyatorda boshlang'ich kiritilmasa shu summa olinadi "
                  "(kompaniya siyosati: har doim 30 mln).")
    repair_price_per_m2 = models.DecimalField(
        "Ta'mir tarifi (so'm/m²)", max_digits=12, decimal_places=0,
        default=3_000_000,
        help_text="Ta'mirli variantda har m² uchun qo'shiladigan summa.")
    # RASMIY m² tarif — YAGONA manba (bot prompti, narx-filtr, planirovka izohi
    # hammasi /api/tariff/ orqali shu qiymatlarni oladi). O'zgartirsangiz bot
    # ~5 daqiqada (BACKEND_CACHE_TTL) yangi tarifga o'tadi.
    tariff_m2_low_floors = models.DecimalField(
        "Rasmiy tarif: 1–5-qavat (so'm/m²)", max_digits=12, decimal_places=0,
        default=8_990_000)
    tariff_m2_high_floors = models.DecimalField(
        "Rasmiy tarif: 6–9-qavat (so'm/m²)", max_digits=12, decimal_places=0,
        default=8_490_000)
    tariff_warning = models.CharField(
        "Tarif ogohlantirishi", max_length=255, blank=True, default="",
        help_text="Sync Uysot'dagi m² narx bilan farq topsa shu yerga yozadi "
                  "(dashboard'da qizil ko'rinadi).")
    updated_at = models.DateTimeField("Oxirgi tahrir", auto_now=True)

    class Meta:
        verbose_name = "Narx sozlamalari"
        verbose_name_plural = "Narx sozlamalari"

    def __str__(self) -> str:
        return "Narx sozlamalari"

    @classmethod
    def get(cls) -> "PricingConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class DiscountTier(models.Model):
    """Chegirma zinapoyasi: boshlang'ich to'lov ulushi oshgani sari chegirma oshadi.

    Kalkulyator boshlang'ich to'lovning umumiy narxdagi ulushini hisoblab,
    shu ulushga yetgan ENG KATTA pog'onaning chegirmasini avtomatik qo'llaydi.
    Masalan: 50% → 3%, 70% → 5%, 100% → 8% kabi pog'onalarni kiritishingiz mumkin."""
    min_prepayment_percent = models.DecimalField(
        "Boshlang'ich ulushi kamida (%)", max_digits=5, decimal_places=1,
        help_text="Umumiy narxning necha foizi to'lansa shu pog'ona ishlaydi")
    discount_percent = models.DecimalField(
        "Chegirma (%)", max_digits=5, decimal_places=2)
    is_active = models.BooleanField("Faol", default=True)

    class Meta:
        verbose_name = "Chegirma pog'onasi"
        verbose_name_plural = "Chegirma zinapoyasi (boshlang'ichga qarab)"
        ordering = ("min_prepayment_percent",)

    def __str__(self) -> str:
        return f"{self.min_prepayment_percent}% dan → {self.discount_percent}% chegirma"


class QAEntry(models.Model):
    """Menejerlar anketasidan olingan RASMIY savol-javob (bilim_dataset.json).

    Bot mijozning savoli shu ro'yxatdagi savolga mos kelsa, javobni AYNAN shu
    tasdiqlangan javob mazmuni bilan beradi (fakt va raqamlarni o'zgartirmasdan).
    Import: `python manage.py import_qa <fayl.json>`. Admin shu yerdan ko'radi,
    tahrirlaydi; javobi bo'sh/"bilmayman" bo'lganlari importda o'zi o'chiq bo'ladi.
    """
    KATEGORIYALAR = [
        ("asosiy", "Asosiy"), ("etiroz", "E'tiroz (qarshiliklar)"),
        ("hudud", "Hudud"), ("jarayon", "Jarayon"), ("kompaniya", "Kompaniya"),
        ("narx", "Narx"), ("ochiq", "Ochiq savollar"), ("qurilish", "Qurilish"),
        ("topshirish", "Topshirish"), ("umumiy", "Umumiy"), ("xonadon", "Xonadon"),
    ]

    savol = models.TextField("Savol")
    javob = models.TextField("Rasmiy javob",
                             help_text="Bot AYNAN shu javob mazmuni bilan javob beradi.")
    kategoriya = models.CharField("Kategoriya", max_length=30,
                                  choices=KATEGORIYALAR, default="umumiy")
    sana_sezgir = models.BooleanField(
        "Sana-sezgir", default=False,
        help_text="Vaqt o'tishi bilan eskiradigan javob (masalan qurilish holati).")
    qayta_tekshirish_kerak = models.BooleanField("Qayta tekshirish kerak", default=False)
    yangilangan = models.DateField("Yangilangan sana", null=True, blank=True)
    is_active = models.BooleanField("Botga berilsinmi", default=True)
    note = models.CharField("Izoh", max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Rasmiy savol-javob"
        verbose_name_plural = "Rasmiy savol-javoblar (anketa)"
        ordering = ("kategoriya", "id")
        constraints = [
            models.UniqueConstraint(fields=["savol", "javob"], name="uniq_savol_javob"),
        ]

    def __str__(self) -> str:
        return self.savol[:80]


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
