"""Bot uchun JSON API — xonadon turlari, planirovka rasm URL'lari va bilim bazasi."""
from django.http import JsonResponse

from . import services
from .models import KnowledgeSection, Layout


def layouts_api(request):
    """GET /api/layouts/ — faol xonadon turlari ro'yxati (bot shundan o'qiydi).

    Har so'rovda ma'lumot eskirganini tekshiradi: LAYOUT_SYNC_TTL (default 1 soat)
    dan qari bo'lsa — FONDA Uysot'dan qayta sync boshlanadi (javob bloklanmaydi).
    Shu tarzda qolgan/sotilgan sonlar CRM'dan avtomatik yangilanib turadi."""
    services.maybe_auto_sync()
    items = []
    for l in Layout.objects.filter(is_active=True):
        img_url = request.build_absolute_uri(l.planirovka.url) if l.planirovka else None
        img_3d_url = (request.build_absolute_uri(l.planirovka_3d.url)
                      if l.planirovka_3d else None)
        items.append({
            "id": l.id,
            "rooms": l.rooms,
            "area": float(l.area),
            "blocks": [b.strip() for b in l.blocks.split(",") if b.strip()],
            "available_count": l.available_count,
            "total_count": l.total_count,
            "min_floor": l.min_floor,
            "max_floor": l.max_floor,
            "image_url": img_url,        # 2D planirovka (ixtiyoriy — bo'sh bo'lishi mumkin)
            "image_3d_url": img_3d_url,  # 3D variant (ixtiyoriy — bo'sh bo'lishi mumkin)
            "note": l.note,
        })
    return JsonResponse({"data": items}, json_dumps_params={"ensure_ascii": False})


def knowledge_api(request):
    """GET /api/knowledge/ — bilim bazasi (faol bo'limlar, tartib bilan birlashtirilgan).

    Bot har javobda shu matnni system promptga qo'yadi (o'z tomonida keshlaydi).
    Bo'limlar admin panelda tahrirlanadi (Bilim bazasi bo'limi)."""
    sections = KnowledgeSection.objects.filter(is_active=True)
    text = "\n\n".join(s.content.strip() for s in sections if s.content.strip())
    latest = max((s.updated_at for s in sections), default=None)
    return JsonResponse(
        {"data": {"text": text,
                  "updated_at": latest.isoformat() if latest else None,
                  "sections": sections.count()}},
        json_dumps_params={"ensure_ascii": False})
