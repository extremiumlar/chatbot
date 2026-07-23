"""Bilim bazasi (storage/knowledge.db) uchun admin panel.

Hujjatlar, RAG bo'laklari, faktlar, uylar, lidlar va suhbat tarixini
brauzerda ko'rish, qidirish va tahrirlash imkonini beradi.
"""
from django.contrib import admin
from django.urls import reverse
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

from .models import BugReport, Chunk, Document, Fact, Lead, Message, Property

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
    list_display = ("id", "external_id", "name", "username", "phone",
                    "num_messages", "first_seen", "last_seen", "suhbat")
    search_fields = ("name", "username", "phone", "external_id")
    readonly_fields = ("first_seen", "last_seen", "num_messages", "suhbat_korinishi")
    fields = ("external_id", "name", "username", "phone",
              "first_seen", "last_seen", "num_messages", "suhbat_korinishi")
    ordering = ("-last_seen",)
    list_per_page = 50

    @admin.display(description="Suhbati")
    def suhbat(self, obj):
        if obj.external_id is None:
            return "—"
        url = reverse("admin:kb_message_changelist")
        return format_html('<a href="{}?external_id__exact={}">xabarlari</a>',
                           url, obj.external_id)

    @admin.display(description="Suhbat (oxirgi 50 xabar)")
    def suhbat_korinishi(self, obj):
        """Lid sahifasining o'zida suhbatni chat ko'rinishida o'qish
        (Message ro'yxatiga o'tmasdan). Eskidan yangiga tartibda."""
        if obj.external_id is None:
            return "—"
        msgs = list(Message.objects.filter(external_id=obj.external_id)
                    .order_by("-id")[:50])[::-1]
        if not msgs:
            return "Hali xabar yo'q."
        bubbles = []
        for m in msgs:
            is_bot = m.role == "assistant"
            bubbles.append(
                '<div style="display:flex;justify-content:{just}">'
                '<div style="max-width:75%;margin:3px 0;padding:7px 11px;'
                'border-radius:10px;background:{bg};font-size:13px;'
                'white-space:pre-wrap;word-break:break-word">'
                '<b style="font-size:11px;color:{who_c}">{who}</b><br>{text}'
                '<div style="font-size:10px;color:#999;text-align:right">{t}</div>'
                "</div></div>".format(
                    just="flex-end" if is_bot else "flex-start",
                    bg="#e7f3e7" if is_bot else "#eef2f7",
                    who_c="#2e7d32" if is_bot else "#1a5276",
                    who="🤖 Bot" if is_bot else "👤 Mijoz",
                    text=escape(m.content),
                    t=escape(m.created_at or ""),
                ))
        full_url = reverse("admin:kb_message_changelist")
        return mark_safe(
            '<div style="max-height:460px;overflow-y:auto;border:1px solid #ddd;'
            'border-radius:8px;padding:8px 10px;background:#fff">'
            + "".join(bubbles) + "</div>"
            + f'<p style="margin-top:6px"><a href="{full_url}?external_id__exact='
              f'{obj.external_id}">Barcha xabarlarini ochish →</a></p>')


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "external_id", "kim", "matn_qisqa", "created_at")
    list_filter = ("role",)
    search_fields = ("content", "=external_id")
    readonly_fields = ("created_at",)
    ordering = ("-id",)
    list_per_page = 100

    @admin.display(description="Kim", ordering="role")
    def kim(self, obj):
        if obj.role == "assistant":
            return format_html('<span style="color:#2e7d32">🤖 Bot</span>')
        return format_html('<span style="color:#1a5276">👤 Mijoz</span>')

    @admin.display(description="Xabar (qisqa)")
    def matn_qisqa(self, obj):
        return _qisqa(obj.content, 120)

    def lookup_allowed(self, lookup, value, request=None):
        # Lid sahifasidagi "xabarlari" havolasi ?external_id__exact=... bilan keladi
        if lookup in ("external_id", "external_id__exact"):
            return True
        return super().lookup_allowed(lookup, value, request)


@admin.register(BugReport)
class BugReportAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "username", "qisqa", "created_at")
    search_fields = ("report", "name", "username")
    ordering = ("-id",)

    @admin.display(description="Hisobot")
    def qisqa(self, obj):
        return (obj.report or "")[:100]

    def has_add_permission(self, request):
        return False    # hisobotlar faqat botdan keladi
