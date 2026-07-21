"""Pytest ko'prigi — mavjud standalone test skriptlarini (tests/*.py) va Django
sync testlarini (backend/inventory/tests) BITTA `pytest` buyrug'i bilan yuritadi.

Har bir skript SUBPROCESS sifatida chaqiriladi va standalone rejimida ishlagani
kabi ishlaydi (`.venv\\Scripts\\python.exe tests\\xxx.py` hali ham to'g'ridan-to'g'ri
ishlaydi, o'zgarishsiz) — bu fayl faqat ularning chiqish kodini/natijasini
pytest'ga "tarjima qiladi", skriptlarning ichki mantig'iga tegmaydi (past-risk
integratsiya: birorta ham mavjud test o'zgartirilmagan).

Ishlatilishi:
    pytest -m "not live"     # faqat oflayn testlar (tavsiya, CI/kundalik uchun)
    pytest                   # oflayn + live (Gemini API kerak, sekin, kvota sarflaydi)
    pytest tests/test_pytest_bridge.py -v    # faqat shu ko'prik, batafsil

Markerlar: `live` — Gemini/tashqi API'ga haqiqiy tarmoq so'rovi yuboradigan
testlar (`pytest.ini`da ro'yxatga olingan).
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
PY = sys.executable


def _run(args: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        args, cwd=cwd, timeout=timeout,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _run_script(rel_path: str, extra_args: list[str] | None = None,
                timeout: int = 300) -> subprocess.CompletedProcess:
    """tests/xxx.py ni loyiha ildizidan standalone rejimda ishga tushiradi."""
    return _run([PY, rel_path, *(extra_args or [])], cwd=ROOT, timeout=timeout)


# ---------------------------------------------------------------------------
# OFLAYN testlar (tarmoq/LLM'siz — lokal embedding model, mock'langan provayder)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("script", [
    "tests/test_hybrid_units.py",
    "tests/test_price_guard.py",
    "tests/test_stage1.py",
    "tests/test_stage4.py",
    "tests/test_stage5_debug.py",
])
def test_offline_script(script: str) -> None:
    """Har bir standalone skript o'zining ICHKI check()/assert mantig'i bo'yicha
    0 (muvaffaqiyat) yoki 1 (xato) bilan chiqadi — shu kod pytest'ga tarjima qilinadi."""
    res = _run_script(script)
    assert res.returncode == 0, (
        f"{script} muvaffaqiyatsiz (kod {res.returncode}):\n"
        f"--- STDOUT ---\n{res.stdout[-3000:]}\n--- STDERR ---\n{res.stderr[-1500:]}"
    )


def test_script_eval() -> None:
    """KIRILL/SHEVA/LOTIN natijalari — script_eval.py o'z mezonlari bo'yicha
    (>=9/10, >=11/13, 5/5) exit-kod beradi."""
    res = _run_script("tests/script_eval.py", timeout=300)
    assert res.returncode == 0, (
        f"script_eval.py mezonlarni bajarmadi:\n{res.stdout[-3000:]}\n{res.stderr[-1000:]}"
    )


def test_rag_eval_hybrid_100_percent() -> None:
    """Bazaviy talab: tests/rag_eval.py --hybrid => 30/30 (100%). Bu skript sof
    diagnostika vositasi sifatida yozilgan (har doim exit 0) — shuning uchun
    pytest bosqichida STDOUT'dagi "TOP-1 ANIQLIK: X/Y" qatorini o'qib, X==Y
    ekanini shu yerda tekshiramiz (skriptning o'zi o'zgartirilmagan)."""
    res = _run_script("tests/rag_eval.py", ["--hybrid"], timeout=300)
    assert res.returncode == 0, f"rag_eval.py --hybrid ishga tushmadi:\n{res.stderr[-1500:]}"
    m = re.search(r"TOP-1 ANIQLIK:\s*(\d+)/(\d+)", res.stdout)
    assert m, f"natija qatori topilmadi:\n{res.stdout[-2000:]}"
    ok, total = int(m.group(1)), int(m.group(2))
    assert ok == total, (
        f"RAG aniqligi pasaydi: {ok}/{total} (30/30 SHART, pasaytirish taqiqlangan)\n"
        f"{res.stdout[-3000:]}"
    )


def test_django_sync_unit_tests() -> None:
    """4.4-bosqich: sync N+1 va backoff testlari (backend/inventory/tests/test_sync.py).
    To'liq mock'langan (Uysot'ga haqiqiy so'rov yo'q) — shuning uchun oflayn."""
    res = _run(
        [PY, "manage.py", "test", "inventory.tests.test_sync", "-v", "1"],
        cwd=BACKEND_DIR, timeout=120,
    )
    assert res.returncode == 0, (
        f"Django sync testlari muvaffaqiyatsiz:\n{res.stdout[-2000:]}\n{res.stderr[-2000:]}"
    )


# ---------------------------------------------------------------------------
# JONLI testlar (haqiqiy Gemini API so'rovi — default O'TKAZIB YUBORILADI)
# ---------------------------------------------------------------------------

@pytest.mark.live
def test_price_policy_live() -> None:
    """Narx-filtr JONLI adversarial baho (6 tuzoq + 2 nazorat, real Gemini).
    Ishga tushirish: `pytest -m live` yoki `pytest tests/test_pytest_bridge.py::test_price_policy_live`.
    GEMINI_API_KEY talab qiladi va bepul kvotadan foydalanadi."""
    res = _run_script("tests/price_policy_eval.py", timeout=300)
    assert res.returncode == 0, (
        f"Narx siyosati jonli testda muammo topildi:\n{res.stdout[-4000:]}\n{res.stderr[-1500:]}"
    )
