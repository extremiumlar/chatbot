"""Bilim bazasi (storage/knowledge.db) uchun admin panel.

Hujjatlar, RAG bo'laklari, faktlar, uylar, lidlar va suhbat tarixini
brauzerda ko'rish, qidirish va tahrirlash imkonini beradi.
"""
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import Chunk, Document, Fact, Lead, Message, Property

CHROMA_ESLATMA = (
    "DIQQAT: bo'lak matni bu yerda tahrirlansa, semantik qidiruv (Chroma) "
    "indeksi ESKICHA qoladi. Tahrirdan keyin loyiha ildizida "
    "`python ingest.py --rebuild` ni ishga tushiring."
)


def _qisqa(matn: str | None, uzunlik: int = 90) -> str:
    """Ro'yxatda ko'rsatish uchun matnni qisqartiradi."""
    if not matn:
        return "—"
    matn = " ".join(matn.split())
    return matn if len(matn) <= uzunlik else matn[:uzunlik] + "…"


class ChunkInline(admin.TabularInline):
    """Hujjat sahifasida uning bo'laklari ro'yxati (qisqa ko'rinishda)."""
    model = Chunk
    extra = 0
    can_delete = False
    show_change_link = True                     # to'liq tahrirlash uchun havola
    fields = ("chunk_index", "page", "matn_qisqa")
    readonly_fields = ("chunk_index", "page", "matn_qisqa")

    @admin.display(description="Matn (qisqa)")
    def matn_qisqa(self, obj):
        return _qisqa(obj.text, 140)

    def has_add_permission(self, request, obj=None):
        return False                            # bo'lak qo'lda emas, ingest orqali qo'shiladi


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "filename", "title", "source_type",
                    "num_pages", "num_chunks", "bolaklar", "created_at")
    list_filter = ("source_type",)
    search_fields = ("filename", "title", "summary")
    readonly_fields = ("file_hash", "created_at")
    inlines = [ChunkInline]
    list_per_page = 50

    @admin.display(description="Bo'laklari")
    def bolaklar(self, obj):
        url = reverse("admin:kb_chunk_changelist")
        return format_html('<a href="{}?document__id__exact={}">ko\'rish</a>',
                           url, obj.pk)


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "chunk_index", "page", "matn_qisqa")
    list_filter = ("document",)
    search_fields = ("text", "document__filename", "document__title")
    autocomplete_fields = ("document",)
    list_select_related = ("document",)
    list_per_page = 50

    fieldsets = (
        (None, {
            "fields": ("document", "chunk_index", "page", "text"),
            "description": CHROMA_ESLATMA,
        }),
    )

    @admin.display(description="Matn (qisqa)")
    def matn_qisqa(self, obj):
        return _qisqa(obj.text, 120)


@admin.register(Fact)
class FactAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "question", "javob_qisqa", "document", "created_at")
    list_filter = ("category",)
    list_editable = ("category",)
    search_fields = ("question", "answer", "category")
    autocomplete_fields = ("document",)
    readonly_fields = ("created_at",)
    list_per_page = 50

    @admin.display(description="Javob (qisqa)")
    def javob_qisqa(self, obj):
        return _qisqa(obj.answer)


@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "address", "rooms", "area_m2", "floor",
                    "price", "build_stage", "status", "created_at")
    list_filter = ("status", "rooms", "build_stage")
    list_editable = ("price", "status")
    search_fields = ("name", "address", "price", "extra")
    autocomplete_fields = ("document",)
    readonly_fields = ("created_at",)
    list_per_page = 50


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("id", "telegram_id", "name", "username", "phone",
                    "num_messages", "first_seen", "last_seen", "suhbat")
    search_fields = ("name", "username", "phone", "telegram_id")
    readonly_fields = ("first_seen", "last_seen", "num_messages")
    list_per_page = 50

    @admin.display(description="Suhbati")
    def suhbat(self, obj):
        if obj.telegram_id is None:
            return "—"
        url = reverse("admin:kb_message_changelist")
        return format_html('<a href="{}?telegram_id__exact={}">xabarlari</a>',
                           url, obj.telegram_id)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "telegram_id", "role", "matn_qisqa", "created_at")
    list_filter = ("role",)
    search_fields = ("content", "telegram_id")
    readonly_fields = ("created_at",)
    list_per_page = 100

    @admin.display(description="Xabar (qisqa)")
    def matn_qisqa(self, obj):
        return _qisqa(obj.content, 120)

    def lookup_allowed(self, lookup, value, request=None):
        # Lid sahifasidagi "xabarlari" havolasi ?telegram_id__exact=... bilan keladi
        if lookup in ("telegram_id", "telegram_id__exact"):
            return True
        return super().lookup_allowed(lookup, value, request)
