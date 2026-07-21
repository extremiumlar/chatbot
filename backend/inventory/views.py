"""Bot uchun JSON API — xonadon turlari, planirovka rasm URL'lari va bilim bazasi.
Pastda: admin narx kalkulyatori (faqat xodimlar uchun)."""
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render

from . import pricing
from .auth import require_bot_token
from .models import KnowledgeSection, Layout, QAEntry


def _abs_url(request, file_field) -> str | None:
    """Rasm uchun to'liq URL. PUBLIC_BASE_URL sozlangan bo'lsa — o'sha domen bilan
    (bot boshqa mashinadan ham ochadi); bo'lmasa so'rov hostidan (lokal rejim)."""
    if not file_field:
        return None
    if settings.PUBLIC_BASE_URL:
        return f"{settings.PUBLIC_BASE_URL}{file_field.url}"
    return request.build_absolute_uri(file_field.url)


@require_bot_token
def layouts_api(request):
    """GET /api/layouts/ — faol xonadon turlari ro'yxati (bot shundan o'qiydi).

    DIQQAT: avto-sync ENDI BU YERDA EMAS (begona so'rov 257 ta Uysot chaqiruvini
    qo'zg'atmasin) — sync `manage.py sync_layouts` (cron) yoki admin tugmasi bilan."""
    items = []
    for l in Layout.objects.filter(is_active=True):
        img_url = _abs_url(request, l.planirovka)
        img_3d_url = _abs_url(request, l.planirovka_3d)
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


def _f(request, name: str, default: float | None = None) -> float | None:
    """Formadan float o'qish ('12 500 000', '12,5' kabi yozuvlarni ham tushunadi)."""
    raw = (request.GET.get(name) or "").replace(" ", "").replace("'", "").replace(",", ".")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _calc_with_policy(calc_fn, common: dict) -> tuple[dict, float]:
    """Ikki o'tishli hisob: avval boshlang'ich summani aniqlaymiz, uning umumiy
    narxdagi ulushiga qarab chegirma ZINAPOYASIDAN (admin sozlaydi) avto-chegirma
    olamiz, keyin yakuniy hisob. Qaytaradi: (natija, avto_chegirma_foizi)."""
    prelim = calc_fn(**common)
    share = (prelim["prepayment"] / prelim["total"] * 100.0) if prelim["total"] else 0.0
    auto = pricing.tier_discount_percent(share)
    if not auto:
        return prelim, 0.0
    final = dict(common)
    final["discount_percent"] = (common.get("discount_percent") or 0.0) + auto
    final["prepayment_percent"] = None
    final["prepayment_sum"] = prelim["prepayment"]   # summa qotiriladi, % qayta hisoblanmaydi
    return calc_fn(**final), auto


@staff_member_required
def price_calculator(request):
    """GET /admin/narx/ — Uysot bosqichlari bo'yicha narx kalkulyatori (xodimlar).

    Ikki rejim: Uysot'dagi xonadonni tanlash (tariflar API'dan) yoki qo'lda
    maydon/tarif kiritish. Standart boshlang'ich (30 mln) va ta'mir tarifi —
    admin "Narx sozlamalari"da; boshlang'ich ulushiga qarab avto-chegirma —
    "Chegirma zinapoyasi"da. Hisob mantiqi: inventory/pricing.py."""
    flats = pricing.get_available_flats()
    flat_choices = [(f["id"], pricing.flat_label(f)) for f in flats]
    cfg = pricing.get_config()

    ctx: dict = {
        "title": "Narx kalkulyatori",
        "flats": flat_choices,
        "repair_tariff": cfg["repair_price_per_m2"],
        "default_prepayment": cfg["default_prepayment"],
        "values": request.GET,
        "result": None, "flat": None, "error": None, "auto_discount": 0.0,
    }

    if request.GET.get("hisobla"):
        months = int(_f(request, "months", 0) or 0)
        common = dict(
            repaired=request.GET.get("repaired") == "1",
            discount_percent=_f(request, "discount_percent", 0.0) or 0.0,
            discount_sum=_f(request, "discount_sum", 0.0) or 0.0,
            prepayment_percent=_f(request, "prepayment_percent"),
            prepayment_sum=_f(request, "prepayment_sum"),
            months=months,
        )
        mode = request.GET.get("mode") or "flat"
        if mode == "flat":
            flat_id = int(_f(request, "flat_id", 0) or 0)
            flat = next((f for f in flats if f["id"] == flat_id), None)
            if flat is None:
                ctx["error"] = ("Xonadon topilmadi (ro'yxat yangilangan bo'lishi "
                                "mumkin) — qaytadan tanlang.")
            else:
                ctx["flat"] = {"id": flat["id"], "label": pricing.flat_label(flat)}
                fn = lambda **kw: pricing.calculate_for_flat(flat, **kw)  # noqa: E731
                ctx["result"], ctx["auto_discount"] = _calc_with_policy(fn, common)
        else:
            area = _f(request, "area")
            tariff = _f(request, "price_per_m2")
            if not area or not tariff:
                ctx["error"] = "Qo'lda rejimda maydon va m² tarif majburiy."
            else:
                fn = lambda **kw: pricing.calculate(  # noqa: E731
                    area=area, price_per_m2=tariff,
                    terrace_area=_f(request, "terrace_area", 0.0) or 0.0,
                    terrace_price_per_m2=_f(request, "terrace_price", 0.0) or 0.0,
                    **kw)
                ctx["result"], ctx["auto_discount"] = _calc_with_policy(fn, common)
    return render(request, "admin/price_calculator.html", ctx)


@staff_member_required
def price_pdf(request):
    """GET /admin/narx/pdf/ — Uysot'ning rasmiy hisob-varaq PDF'ini yuklab beradi."""
    flat_id = int(_f(request, "flat_id", 0) or 0)
    months = int(_f(request, "months", 0) or 0)
    prepay = _f(request, "prepayment_sum", 0.0) or 0.0
    repaired = request.GET.get("repaired") == "1"
    try:
        pdf = pricing.fetch_shourum_pdf(flat_id, months=months,
                                        prepayment_sum=prepay, repaired=repaired)
    except Exception as e:  # noqa: BLE001
        return HttpResponse(f"Uysot PDF olishda xato: {e}", status=502)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="narx_{flat_id}.pdf"'
    return resp


@require_bot_token
def tariff_api(request):
    """GET /api/tariff/ — rasmiy m² tarif (YAGONA manba: PricingConfig, admin tahrirlaydi).
    Bot prompti, narx-filtri va planirovka izohlari shu qiymatlarga ergashadi."""
    from .models import PricingConfig
    cfg = PricingConfig.get()
    return JsonResponse({"data": {
        "low": int(cfg.tariff_m2_low_floors),
        "high": int(cfg.tariff_m2_high_floors),
        "updated_at": cfg.updated_at.isoformat() if cfg.updated_at else None,
    }})


@require_bot_token
def qa_api(request):
    """GET /api/qa/ — menejerlar tasdiqlagan RASMIY savol-javoblar (faol).

    Bot bularni system promptga alohida blok qilib qo'yadi va mijoz savoli mos
    kelganda javobni AYNAN shu tasdiqlangan mazmun bilan beradi."""
    items = []
    for q in QAEntry.objects.filter(is_active=True):
        items.append({
            "savol": q.savol,
            "javob": q.javob,
            "kategoriya": q.kategoriya,
            "sana_sezgir": q.sana_sezgir,
            "yangilangan": q.yangilangan.isoformat() if q.yangilangan else None,
        })
    latest = (QAEntry.objects.filter(is_active=True)
              .order_by("-updated_at").values_list("updated_at", flat=True).first())
    return JsonResponse(
        {"data": {"entries": items,
                  "updated_at": latest.isoformat() if latest else None}},
        json_dumps_params={"ensure_ascii": False})


@require_bot_token
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
