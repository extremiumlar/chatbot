"""Uysot showroom API'dan xonadon TURLARINI (planirovka turlari) sync qiladi.

Ishlatilishi:
    python manage.py sync_layouts

Nima qiladi:
  1) filter-properties -> bloklar va qavatlar diapazoni
  2) shaxmatka (block-flat-data/{blockId}?floor=N) -> BARCHA xonadonlar (SOLD ham)
     va ularning statusi (SALE / SOLD / RESERVE)
  3) har flat uchun flat-all-data -> xona soni va maydon
  4) (xona, maydon) bo'yicha aniq TURLARGA ajratib, Layout jadvaliga yozadi/yangilaydi

Diqqat: yuklangan planirovka rasmi, "is_active" va "izoh" — sync TEGMAYDI (qo'lda boshqariladi).
~220 ta so'rov qiladi (bir necha soniya), inventar tez-tez o'zgarmagani uchun kamdan-kam ishga tushiriladi.
"""
from __future__ import annotations

import json
import time
import urllib.request
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from inventory.models import Layout


def _get(path: str) -> dict:
    req = urllib.request.Request(f"{settings.UYSOT_SHOWROOM_BASE}{path}")
    req.add_header("X-Auth", settings.UYSOT_SHOWROOM_TOKEN)
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


class Command(BaseCommand):
    help = "Uysot showroom API'dan xonadon turlarini sync qiladi"

    def handle(self, *args, **options):
        if not settings.UYSOT_SHOWROOM_TOKEN:
            self.stderr.write("UYSOT_SHOWROOM_TOKEN .env da yo'q.")
            return
        house = settings.UYSOT_HOUSE_ID

        # 1) Bloklar va qavatlar
        fp = _get(f"/filter-properties/{house}")["data"]
        blocks = {b["id"]: b["name"] for b in fp.get("buildingCompactList", [])}
        min_floor = int(fp.get("minFloor") or 1)
        max_floor = int(fp.get("maxFloor") or 9)
        self.stdout.write(f"Bloklar: {list(blocks.values())}, qavatlar {min_floor}-{max_floor}")

        # 2) Shaxmatka -> barcha (flatId, status, blok nomi)
        flats: list[tuple[int, str, str]] = []
        for bid, bname in blocks.items():
            for fl in range(min_floor, max_floor + 1):
                try:
                    d = _get(f"/block-flat-data/{bid}?floor={fl}")["data"] or {}
                except Exception as e:  # noqa: BLE001
                    self.stderr.write(f"  blok {bname} qavat {fl}: {e}")
                    continue
                for x in d.get("blockFlatDataDtoList") or []:
                    flats.append((x["flatId"], x.get("flatStatus") or "", bname))
        self.stdout.write(f"Shaxmatkada jami {len(flats)} xonadon topildi. Tafsilotlar olinmoqda...")

        # 3) Har flat uchun maydon/xona -> (xona, maydon) turlari
        types: dict[tuple, dict] = {}
        for i, (fid, status, bname) in enumerate(flats, 1):
            try:
                fd = _get(f"/block/flat-all-data/{fid}")["data"]
            except Exception:  # noqa: BLE001
                continue
            try:
                rooms = int(fd["rooms"])
                area = round(float(fd["area"]), 1)
            except (KeyError, TypeError, ValueError):
                continue
            number = str(fd.get("number") or "")
            # "M" raqamli — tijorat (do'kon), kvartira turlariga qo'shmaymiz
            if number.upper().startswith("M"):
                continue
            floor = fd.get("floor")
            t = types.setdefault((rooms, area), {
                "blocks": set(), "avail": 0, "total": 0, "floors": set(),
                "sample": None, "sample_avail": None,
            })
            t["total"] += 1
            t["blocks"].add(str(fd.get("block") or bname))
            if floor:
                t["floors"].add(int(floor))
            if status == "SALE":
                t["avail"] += 1
                t["sample_avail"] = t["sample_avail"] or fid
            t["sample"] = t["sample"] or fid
            if i % 25 == 0:
                self.stdout.write(f"  {i}/{len(flats)}...")
            time.sleep(0.03)

        # 4) Layout jadvaliga yozamiz (rasm/is_active/izohga tegmaymiz)
        now = timezone.now()
        created = updated = 0
        for (rooms, area), t in sorted(types.items()):
            blocks_str = ", ".join(sorted(t["blocks"],
                                          key=lambda b: int(b) if b.isdigit() else 99))
            _, is_new = Layout.objects.update_or_create(
                rooms=rooms, area=area,
                defaults=dict(
                    blocks=blocks_str,
                    available_count=t["avail"],
                    total_count=t["total"],
                    sample_flat_id=t["sample_avail"] or t["sample"],
                    min_floor=min(t["floors"]) if t["floors"] else None,
                    max_floor=max(t["floors"]) if t["floors"] else None,
                    synced_at=now,
                ),
            )
            created += int(is_new)
            updated += int(not is_new)

        self.stdout.write(self.style.SUCCESS(
            f"Sync tugadi: {len(types)} tur ({created} yangi, {updated} yangilangan). "
            f"Planirovka rasmini admin panelдан yuklang."))
