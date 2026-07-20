"""Kirill va sheva savollarida RAG aniqligini o'lchash (lokal, LLM'siz).

Ishlatilishi:  .venv\\Scripts\\python.exe tests\\script_eval.py

Uch guruh: KIRILL (transliteratsiya sinovi), SHEVA (og'zaki/lahja sinonimlari),
LOTIN NAZORAT (regressiya). Oltin bo'laklar rag_eval.GOLDEN'dan olinadi,
baza vaqtinchalik papkada quriladi — production'ga tegilmaydi.
"""
from __future__ import annotations

import os
import sys
import tempfile
import pathlib

sys.path.insert(0, os.path.abspath("."))

import config  # noqa: E402

# Production bazaga tegmaslik uchun vaqtinchalik papkalar (importlardan OLDIN)
_tmp = pathlib.Path(tempfile.mkdtemp(prefix="script_eval_"))
config.CHROMA_DIR = _tmp / "chroma"
config.CHROMA_DIR.mkdir(parents=True)
config.SQLITE_PATH = _tmp / "eval.db"

from tests.rag_eval import GOLDEN, build_index  # noqa: E402
from knowledge import hybrid  # noqa: E402

KIRILL = [
    ("парковка борми", "parkovka"),
    ("машина қўядиган жой борми", "parkovka"),
    ("кафолат неча йил", "kafolat"),
    ("гарантия қанча", "kafolat"),
    ("чегирма борми", "chegirma"),
    ("скидка қанча", "chegirma"),
    ("уй качон топширилади", "topshirish"),
    ("қандай ҳужжат керак", "hujjatlar"),
    ("қаерда жойлашган", "joylashuv"),
    ("нимадан қурилган", "material"),
]
SHEVA = [
    ("mashina qo'yishga joy bormi aka", "parkovka"),
    ("moshina uchun joy-pjoy bormi", "parkovka"),
    ("garantiyasi qancha ekan bu uylani", "kafolat"),
    ("uyla qachon bitarkan", "topshirish"),
    ("qachongacha bitib qoladi uy", "topshirish"),
    ("pulini qanaqasiga to'liymiz", "tolov_jadvali"),
    ("nechchi pul to'lash kere oyiga", "tolov_jadvali"),
    ("skidka-pidka bo'ladimi", "chegirma"),
    ("arzonlashtirib berilmaydimi", "chegirma"),
    ("dokumentga nima kere", "hujjatlar"),
    ("qanaqa qog'oz kerak bo'ladi", "hujjatlar"),
    ("uyla mustahkammi o'zi", "material"),
    ("zilzila bo'sa yiqilib tushmaydimi", "material"),
]
LOTIN_NAZORAT = [
    ("parkovka bormi", "parkovka"),
    ("kafolat necha yil", "kafolat"),
    ("chegirma bormi", "chegirma"),
    ("qayerda joylashgan", "joylashuv"),
    ("boshlang'ich to'lov qancha", "boshlangich_tolov"),
]


def run_group(name: str, queries: list[tuple[str, str]],
              id2topic: dict[int, str]) -> tuple[int, int]:
    print(f"\n### {name} ###")
    print(f"{'savol':40.40} | {'topildi':18} | {'ball':>5} | {'vec':>5} | {'kw':>5} | holat")
    print("-" * 95)
    ok = 0
    for q, expected in queries:
        hits = hybrid.hybrid_search(q, top_k=3)
        top = hits[0] if hits else None
        got = id2topic.get(top["chunk_id"]) if top else None
        good = got == expected
        ok += good
        print(f"{q:40.40} | {got or '-':18} | {top['score'] if top else 0:5.2f} | "
              f"{top['vec_score'] if top else 0:5.2f} | {top['kw_score'] if top else 0:5.2f} | "
              f"{'✓' if good else '✗ XATO (kutilgan: ' + expected + ')'}")
    print(f"--- {name}: {ok}/{len(queries)}")
    return ok, len(queries)


def main() -> None:
    id2topic = build_index()
    print(f"Model: {config.EMBED_MODEL} | bo'laklar: {len(GOLDEN)}")

    k_ok, k_n = run_group("KIRILL", KIRILL, id2topic)
    s_ok, s_n = run_group("SHEVA / OG'ZAKI", SHEVA, id2topic)
    l_ok, l_n = run_group("LOTIN NAZORAT (regressiya)", LOTIN_NAZORAT, id2topic)

    print("\n" + "=" * 60)
    print(f"KIRILL:  {k_ok}/{k_n}   (mezon: >= 9/10)")
    print(f"SHEVA:   {s_ok}/{s_n}  (mezon: >= 11/13)")
    print(f"LOTIN:   {l_ok}/{l_n}    (mezon: 5/5)")
    passed = k_ok >= 9 and s_ok >= 11 and l_ok == l_n
    print("✅ QABUL MEZONLARI BAJARILDI" if passed else "⚠ MEZON BAJARILMADI")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
