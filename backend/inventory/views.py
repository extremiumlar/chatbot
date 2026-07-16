"""Bot uchun JSON API — xonadon turlari + planirovka rasm URL'lari."""
from django.http import JsonResponse

from .models import Layout


def layouts_api(request):
    """GET /api/layouts/ — faol xonadon turlari ro'yxati (bot shundan o'qiydi)."""
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
