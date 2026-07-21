from django import forms
from django.contrib import admin, messages
from django.utils.html import format_html

from .models import DiscountTier, KnowledgeSection, Layout, PricingConfig, QAEntry


@admin.register(Layout)
class LayoutAdmin(admin.ModelAdmin):
    list_display = ("nomi_holat", "blocks", "sotuv_holati", "total_count",
                    "image_tag", "is_active", "synced_at")
    list_filter = ("rooms", "is_active")
    list_editable = ("is_active",)
    search_fields = ("blocks", "note")
    list_per_page = 50
    actions = ["sync_now"]
    readonly_fields = ("image_preview", "image_3d_preview", "sample_flat_id", "synced_at",
                       "created_at", "updated_at")
    fields = ("rooms", "area", "blocks", "available_count", "total_count",
              "min_floor", "max_floor", "sample_flat_id",
              "planirovka", "image_preview",
              "planirovka_3d", "image_3d_preview",
              "is_active", "note",
              "synced_at", "created_at", "updated_at")

    @admin.action(description="Hozir Uysot'dan sync qilish")
    def sync_now(self, request, queryset):
        """4.4: sync ENDI so'rov yo'lida avtomatik chaqirilmaydi — shu tugma yoki
        `manage.py sync_layouts` (cron) orqali qo'lda/rejalashtirilgan ishga tushadi."""
        from . import services
        try:
            summary = services.sync_all()
        except Exception as e:  # noqa: BLE001
            self.message_user(request, f"Sync xatosi: {e}", level=messages.ERROR)
            return
        self.message_user(request, summary, level=messages.SUCCESS)

    @admin.display(description="Xonadon turi", ordering="rooms")
    def nomi_holat(self, obj):
        """Sotuvda yo'q, lekin is_active=True — QIZIL (bot bu turni endi yubormaydi,
        admin adashmasin: yo is_active o'chirilsin, yo yangi xonadon kutilsin)."""
        if obj.is_active and (obj.available_count or 0) <= 0:
            return format_html('<span style="color:#c00;font-weight:600">{} — SOTILGAN</span>',
                               str(obj))
        return str(obj)

    @admin.display(description="Sotuvda (qolgan)", ordering="available_count")
    def sotuv_holati(self, obj):
        if (obj.available_count or 0) <= 0:
            return format_html('<span style="color:#c00;font-weight:600">0</span>')
        return obj.available_count

    @admin.display(description="Rasm")
    def image_tag(self, obj):
        thumbs = []
        if obj.planirovka:
            thumbs.append(format_html(
                '<img src="{}" title="2D" style="height:44px;border-radius:4px;margin-right:4px" />',
                obj.planirovka.url))
        if obj.planirovka_3d:
            thumbs.append(format_html(
                '<img src="{}" title="3D" style="height:44px;border-radius:4px" />',
                obj.planirovka_3d.url))
        if thumbs:
            return format_html("".join(["{}"] * len(thumbs)), *thumbs)
        return format_html('<span style="color:#c00">— yo\'q —</span>')

    @admin.display(description="Planirovka (2D) ko'rinishi")
    def image_preview(self, obj):
        if obj.planirovka:
            return format_html('<img src="{}" style="max-width:520px;border:1px solid #ddd" />',
                               obj.planirovka.url)
        return "Hali 2D rasm yuklanmagan (ixtiyoriy)."

    @admin.display(description="Planirovka (3D) ko'rinishi")
    def image_3d_preview(self, obj):
        if obj.planirovka_3d:
            return format_html('<img src="{}" style="max-width:520px;border:1px solid #ddd" />',
                               obj.planirovka_3d.url)
        return "Hali 3D rasm yuklanmagan (ixtiyoriy)."


@admin.register(PricingConfig)
class PricingConfigAdmin(admin.ModelAdmin):
    """Bitta yozuvli sozlama: qo'shish/o'chirish yo'q, faqat tahrirlash."""
    list_display = ("__str__", "default_prepayment", "repair_price_per_m2", "updated_at")
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not PricingConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(DiscountTier)
class DiscountTierAdmin(admin.ModelAdmin):
    list_display = ("min_prepayment_percent", "discount_percent", "is_active")
    list_editable = ("discount_percent", "is_active")
    ordering = ("min_prepayment_percent",)


class QAEntryForm(forms.ModelForm):
    class Meta:
        model = QAEntry
        fields = "__all__"
        widgets = {
            "savol": forms.Textarea(attrs={"rows": 3, "style": "width:96%"}),
            "javob": forms.Textarea(attrs={"rows": 8, "style": "width:96%"}),
        }


@admin.register(QAEntry)
class QAEntryAdmin(admin.ModelAdmin):
    form = QAEntryForm
    list_display = ("qisqa_savol", "kategoriya", "is_active",
                    "sana_sezgir", "qayta_tekshirish_kerak", "yangilangan")
    list_filter = ("kategoriya", "is_active", "sana_sezgir", "qayta_tekshirish_kerak")
    list_editable = ("is_active", "qayta_tekshirish_kerak")
    search_fields = ("savol", "javob", "note")
    list_per_page = 50
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Savol")
    def qisqa_savol(self, obj):
        return obj.savol[:90]


class KnowledgeSectionForm(forms.ModelForm):
    class Meta:
        model = KnowledgeSection
        fields = "__all__"
        widgets = {
            "content": forms.Textarea(attrs={
                "rows": 34, "style": "width:96%;font-family:Consolas,monospace"}),
        }


@admin.register(KnowledgeSection)
class KnowledgeSectionAdmin(admin.ModelAdmin):
    form = KnowledgeSectionForm
    list_display = ("title", "order", "is_active", "chars", "updated_at")
    list_editable = ("order", "is_active")
    search_fields = ("title", "content")
    readonly_fields = ("created_at", "updated_at")

    @admin.display(description="Hajmi (belgi)")
    def chars(self, obj):
        return len(obj.content or "")
