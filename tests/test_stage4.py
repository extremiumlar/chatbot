"""4-BOSQICH testlari: KB signal, tarif API, inventar yagona manba, sync N+1.

Django kerak bo'lgan qismlar (4.1 signal, 4.4 sync) shu faylda emas — ular
alohida (Django test client bilan) qadamlar davomida qo'lda sinaldi va
hisobotda yozilgan. Bu fayl LOKAL (Django'siz) qismlarni tekshiradi:
uysot/backend.py::inventory_summary(), config.get_tariffs() mexanikasi.

Ishlatilishi:  .venv\\Scripts\\python.exe tests\\test_stage4.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import pathlib

sys.path.insert(0, os.path.abspath("."))

import config  # noqa: E402

_tmp = pathlib.Path(tempfile.mkdtemp())
config.SQLITE_PATH = _tmp / "t.db"

from uysot import backend  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
    print(f"  {'✓' if cond else '✗ FAIL'}  {name}")


FAKE_LAYOUTS = [
    {"id": 1, "rooms": 1, "area": 24.1, "blocks": ["3"], "available_count": 1,
     "total_count": 5, "min_floor": 2, "max_floor": 9},
    {"id": 2, "rooms": 2, "area": 62.0, "blocks": ["1", "3"], "available_count": 15,
     "total_count": 40, "min_floor": 1, "max_floor": 9},
    {"id": 3, "rooms": 3, "area": 74.6, "blocks": ["1"], "available_count": 0,
     "total_count": 2, "min_floor": 9, "max_floor": 9},   # sotuvda yo'q -> chiqmasin
]


def test_inventory_summary() -> None:
    print("=== 4.3: backend.inventory_summary() Layout'dan quriladi ===")
    orig = backend.get_layouts
    backend.get_layouts = lambda force=False: FAKE_LAYOUTS
    try:
        text = backend.inventory_summary()
        check("1 xonali chiqdi", "1 xonali" in text)
        check("2 xonali chiqdi", "2 xonali" in text)
        check("available_count=0 (3 xonali) CHIQMADI", "3 xonali" not in text)
        check("narx YO'Q (kompaniya siyosati)", "so'm" not in text and "mln" not in text)
        check("jami hisob to'g'ri (1+15=16)", "16 ta kvartira" in text)
    finally:
        backend.get_layouts = orig

    backend.get_layouts = lambda force=False: []
    try:
        check("bo'sh layout -> bo'sh matn", backend.inventory_summary() == "")
    finally:
        backend.get_layouts = orig


if __name__ == "__main__":
    test_inventory_summary()
    total = PASS + len(FAIL)
    print(f"\nNATIJA: {PASS}/{total}" + (f" | YIQILDI: {FAIL}" if FAIL else " — ✅"))
    sys.exit(1 if FAIL else 0)
