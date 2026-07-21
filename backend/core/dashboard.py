"""Admin bosh sahifasi (dashboard) uchun statistika.

admin.site.index ni o'rab, index sahifasiga hisob-kitoblarni qo'shadi;
shablon: templates/admin/index.html. Har bir blok alohida try/except bilan —
bot bazasi (knowledge.db) bo'sh/yo'q bo'lsa ham admin ochilaveradi.
"""
from __future__ import annotations

from datetime import date

from django.contrib import admin
from django.urls import reverse


def _kb_stats() -> dict:
    """Bot bazasi (kb app) bo'yicha sonlar. Xato bo'lsa nollar."""
    out = {"leads_total": 0, "leads_today": 0, "msgs_today": 0,
           "facts_total": 0, "docs_total": 0, "recent_leads": [],
           "bugs_total": 0, "recent_bugs": []}
    try:
        from kb.models import Document, Fact, Lead, Message
        today = date.today().isoformat()
        out["leads_total"] = Lead.objects.count()
        out["leads_today"] = Lead.objects.filter(first_seen__startswith=today).count()
        out["msgs_today"] = Message.objects.filter(created_at__startswith=today).count()
        out["facts_total"] = Fact.objects.count()
        out["docs_total"] = Document.objects.count()
        out["recent_leads"] = list(Lead.objects.order_by("-last_seen")[:5])
    except Exception:  # noqa: BLE001 - knowledge.db yo'q/bo'sh bo'lsa ham yiqilmaymiz
        pass
    try:
        from kb.models import BugReport
        out["bugs_total"] = BugReport.objects.count()
        out["recent_bugs"] = list(BugReport.objects.order_by("-id")[:5])
    except Exception:  # noqa: BLE001 - bug_reports jadvali hali yo'q bo'lishi mumkin
        pass
    return out


def _inventory_stats() -> dict:
    out = {"layouts_active": 0, "layouts_with_image": 0, "layouts_no_image": 0,
           "kb_sections": 0, "kb_last_updated": None, "last_sync": None}
    try:
        from django.db.models import Q
        from inventory.models import KnowledgeSection, Layout
        active = Layout.objects.filter(is_active=True)
        out["layouts_active"] = active.count()
        out["layouts_with_image"] = active.exclude(
            Q(planirovka="") & Q(planirovka_3d="")).count()
        out["layouts_no_image"] = out["layouts_active"] - out["layouts_with_image"]
        sections = KnowledgeSection.objects.filter(is_active=True)
        out["kb_sections"] = sections.count()
        latest = sections.order_by("-updated_at").first()
        out["kb_last_updated"] = latest.updated_at if latest else None
        out["last_sync"] = (Layout.objects.exclude(synced_at=None)
                            .order_by("-synced_at")
                            .values_list("synced_at", flat=True).first())
    except Exception:  # noqa: BLE001
        pass
    return out


def dashboard_context() -> dict:
    ctx = {**_kb_stats(), **_inventory_stats()}
    # Shablonda ishlatiladigan ro'yxat havolalari
    ctx["links"] = {
        "leads": reverse("admin:kb_lead_changelist"),
        "messages": reverse("admin:kb_message_changelist"),
        "facts": reverse("admin:kb_fact_changelist"),
        "documents": reverse("admin:kb_document_changelist"),
        "layouts": reverse("admin:inventory_layout_changelist"),
        "sections": reverse("admin:inventory_knowledgesection_changelist"),
        "bugs": reverse("admin:kb_bugreport_changelist"),
    }
    return ctx


def install() -> None:
    """admin.site.index ni dashboard konteksti bilan o'raydi (bir marta, urls.py dan)."""
    original_index = admin.site.index

    def index(request, extra_context=None):
        extra_context = dict(extra_context or {})
        extra_context.update(dashboard_context())
        return original_index(request, extra_context)

    admin.site.index = index
