"""Gibrid qidiruv birlik testlari — transliteratsiya, sinonim, kontrast-guard.

API'siz va EMBEDDING'SIZ (torch yuklanmaydi) — bir soniyada o'tadi.
Ishlatilishi:  .venv\\Scripts\\python.exe tests\\test_hybrid_units.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import pathlib

sys.path.insert(0, os.path.abspath("."))

import config  # noqa: E402

# Birlik testlar production bazaga tegmasin
_tmp = pathlib.Path(tempfile.mkdtemp())
config.SQLITE_PATH = _tmp / "u.db"
config.CHROMA_DIR = _tmp / "chroma"
config.CHROMA_DIR.mkdir()

from knowledge import answer, hybrid  # noqa: E402
from knowledge.hybrid import (  # noqa: E402
    _STOPWORDS, has_contrast, keyword_score, normalize,
)
from knowledge.uz_synonyms import SYNONYMS  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
    print(f"  {'✓' if cond else '✗ FAIL'}  {name}")


print("=== 1) normalize: kirill→lotin transliteratsiya ===")
check('normalize("Чегирма") == "chegirma"', normalize("Чегирма") == "chegirma")
check('normalize("ҲУЖЖАТ") == "hujjat"', normalize("ҲУЖЖАТ") == "hujjat")
check('normalize("хонадон") == "xonadon" (х→x)', normalize("хонадон") == "xonadon")
check('normalize("ҳужжат") == "hujjat" (ҳ→h)', normalize("ҳужжат") == "hujjat")
check('"инвестиция" → "investitsiya" (ц→ts)',
      normalize("инвестиция") == "investitsiya")
check('normalize("chegirma") — lotin O\'ZGARMAYDI',
      normalize("chegirma") == "chegirma")
check('aralash: "Планировка bormi" → "planirovka bormi"',
      normalize("Планировка bormi") == "planirovka bormi")
check('"қ/ғ/ў" → "q/g\'/o\'": "қўрғон" → "qo\'rg\'on"',
      normalize("қўрғон") == "qo'rg'on")
check('"парковка борми" → "parkovka bormi"',
      normalize("парковка борми") == "parkovka bormi")

print("=== 2) keyword_score: kirill savol ↔ lotin bo'lak ===")
check('kw("чегирма борми", lotin bo\'lak) > 0',
      keyword_score("чегирма борми", "Chegirma boshlang'ich to'lov hajmiga qarab") > 0)
check('kw("кафолат неча йил", lotin bo\'lak) > 0',
      keyword_score("кафолат неча йил", "Bino konstruksiyasiga 1 yil kafolat") > 0)
check('kw("гарантия қанча", kafolat bo\'lagi) > 0  (sinonim ham)',
      keyword_score("гарантия қанча", "kafolat beriladi") > 0)

print("=== 3) yangi sinonim kalitlari _STOPWORDS bilan to'qnashmaydi ===")
new_keys = ["bitarkan", "bitadimi", "bitib", "kere", "qog'oz", "to'liymiz",
            "to'liman", "to'lash", "nechchi", "mustahkam", "moshina",
            "arzonlashtirib", "qanaqasiga", "oyiga"]
collide = [k for k in new_keys if k in _STOPWORDS]
check(f"14 yangi kalitning birortasi stopword emas {collide or ''}", not collide)
check("barcha yangi kalitlar lug'atda bor",
      all(k in SYNONYMS for k in new_keys))
# umumiy invariant: lug'atning BARCHA kalitlari stopword bo'lmasin
all_collide = [k for k in SYNONYMS if k in _STOPWORDS]
check(f"lug'atda umuman stopword-kalit yo'q {all_collide or ''}", not all_collide)

print("=== 4) sheva sinonimlari ishlaydi ===")
check('kw("uyla qachon bitarkan", topshirish bo\'lagi) > 0',
      keyword_score("uyla qachon bitarkan",
                    "Uy-joy majmuasi 2027-yil 4-chorakda topshiriladi") > 0)
check('kw("qanaqa qog\'oz kerak", hujjatlar bo\'lagi) > 0',
      keyword_score("qanaqa qog'oz kerak bo'ladi",
                    "Xonadon faqat pasport bilan rasmiylashtiriladi. Kadastr...") > 0)
check('kw("pulini qanaqasiga to\'liymiz", to\'lov bo\'lagi) > 0',
      keyword_score("pulini qanaqasiga to'liymiz",
                    "To'lovlar oylik jadval asosida bank orqali to'lanadi") > 0)
check('kw("uyla mustahkammi", material bo\'lagi) > 0',
      keyword_score("uyla mustahkammi o'zi",
                    "Bino monolit va gazoblokdan qurilgan, zilzilaga chidamli") > 0)

print("=== 5) has_contrast ===")
def _h(scores):
    return [{"score": s} for s in scores]
check("yopishgan [0.48,0.47,0.47,0.46] → False",
      has_contrast(_h([0.48, 0.47, 0.47, 0.46])) is False)
check("aniq g'olib [0.85,0.50,0.40] → True",
      has_contrast(_h([0.85, 0.50, 0.40])) is True)
check("bitta nomzod [0.6] → True", has_contrast(_h([0.6])) is True)
check("bo'sh [] → False", has_contrast([]) is False)
check("min_gap parametri ishlaydi (0.3 talab, farq 0.2 → False)",
      has_contrast(_h([0.7, 0.5]), min_gap=0.3) is False)

print("=== 6) INTEGRATSION: kontrast-guard promptga RAG qo'shishni to'xtatadi ===")
# hybrid_search'ni sun'iy natijalar bilan almashtiramiz; has_data=True qilamiz
from knowledge import vectorstore  # noqa: E402
_orig_search = hybrid.hybrid_search
_orig_hasdata = vectorstore.has_data

vectorstore.has_data = lambda: True
FLAT = [{"chunk_id": i, "text": f"bo'lak {i}", "score": s,
         "vec_score": s, "kw_score": 0.0, "meta": {}}
        for i, s in enumerate([0.48, 0.47, 0.47, 0.46], 1)]
CONTRAST = [{"chunk_id": 1, "text": "kafolat bir yil beriladi", "score": 0.85,
             "vec_score": 0.8, "kw_score": 1.0, "meta": {}},
            {"chunk_id": 2, "text": "boshqa bo'lak", "score": 0.50,
             "vec_score": 0.5, "kw_score": 0.0, "meta": {}}]

hybrid.hybrid_search = lambda q, top_k=5: FLAT
blk = answer._rag_context_block("кафолат неча йил")
check("yopishgan ballar → RAG bo'limi promptga QO'SHILMADI",
      "HUJJATLARDAN" not in blk)

hybrid.hybrid_search = lambda q, top_k=5: CONTRAST
blk = answer._rag_context_block("kafolat necha yil")
check("aniq g'olib → RAG bo'limi promptga QO'SHILDI",
      "HUJJATLARDAN" in blk and "kafolat bir yil" in blk)

hybrid.hybrid_search = _orig_search
vectorstore.has_data = _orig_hasdata

# _system_prompt kirill savol bilan xatosiz quriladi (RAG bo'sh temp'da)
sp = answer._system_prompt("тест")
check("_system_prompt('тест') xatosiz qurildi", len(sp) > 5000)

print()
total = PASS + len(FAIL)
print(f"NATIJA: {PASS}/{total} o'tdi" + (f" | YIQILDI: {FAIL}" if FAIL else " — hammasi toza ✅"))
sys.exit(1 if FAIL else 0)
