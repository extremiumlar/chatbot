"""RAG sifatini o'lchash — "oltin to'plam" bilan top-1 aniqlikni baholaydi.

Ishlatilishi (loyiha ildizidan):
    .venv\\Scripts\\python.exe tests\\rag_eval.py                     # joriy config.EMBED_MODEL, faqat vektor
    .venv\\Scripts\\python.exe tests\\rag_eval.py --hybrid            # gibrid (vektor + kalit so'z)
    .venv\\Scripts\\python.exe tests\\rag_eval.py --model <nom>       # boshqa embedding modeli bilan

Baza vaqtinchalik papkada quriladi — production storage/ ga TEGMAYDI.

Metrikalar:
  - top-1 accuracy: eng yuqori ball TO'G'RI bo'lakka tegdimi (savol turlari bo'yicha ham).
  - threshold tahlili: to'g'ri top-1 ballarning eng pasti va noto'g'ri top-1 ballarning
    eng yuqorisi — RAG_MIN_SCORE ni kalibrlash uchun.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import pathlib

sys.path.insert(0, os.path.abspath("."))  # loyiha ildizidan import qilish uchun

import config  # noqa: E402

# ---------------------------------------------------------------------------
# Oltin to'plam: 10 mavzu (haqiqiy KB mazmuniga o'xshash bo'laklar)
# ---------------------------------------------------------------------------
GOLDEN: dict[str, str] = {
    "parkovka": (
        "Majmuada mashinalar uchun parkovka (avtoturargoh) mavjud. Podval qavatida "
        "ham mashina qo'yish joylari bor, parkovka alohida shartnoma bilan sotiladi."
    ),
    "kafolat": (
        "Bino konstruksiyasiga qabul dalolatnomasidan boshlab 1 yil kafolat beriladi. "
        "Muhandislik tizimlariga ham kamida 1 yil kafolat bor. Kafolat muddatida nuqson "
        "topilsa, u bepul bartaraf etiladi va kafolat muddati uzayadi."
    ),
    "tolov_jadvali": (
        "To'lovlar shartnomaga ilova qilingan oylik jadval asosida bank orqali (naqdsiz) "
        "amalga oshiriladi. Boshlang'ich to'lov shartnoma imzolangach 3 ish kuni ichida "
        "to'lanadi, qolgani oylik bo'lib to'lanadi."
    ),
    "chegirma": (
        "Chegirma boshlang'ich to'lov hajmiga qarab beriladi: boshlang'ich to'lov qancha "
        "ko'p bo'lsa, chegirma shuncha katta. Aniq chegirma summasi ofisda hisoblab beriladi."
    ),
    "topshirish": (
        "Uy-joy majmuasi 2027-yil 4-chorakda foydalanishga topshiriladi. Qurilish muddati "
        "shartnoma tuzilgan kundan 24 oy, zarurat bo'lsa 6 oygacha uzayishi mumkin."
    ),
    "hujjatlar": (
        "Xonadon faqat pasport bilan rasmiylashtiriladi, rasmiy ish joyi talab qilinmaydi. "
        "Kadastr va guvohnoma blok tomi yopilgach 1-3 oy ichida mijoz nomiga o'tkaziladi."
    ),
    "planirovka": (
        "Xonadon planirovkalari 2 va 3 xonali variantlarda: 62 m² dan 74.6 m² gacha. "
        "Har bir xonadonning rejasi (chizmasi) PDF ko'rinishida mavjud."
    ),
    "joylashuv": (
        "Majmua Sirdaryo viloyati, Guliston shahri, 4-mikrorayon oxirida, Zarbdor MFY "
        "hududida joylashgan. Shaharga eng yaqin va tinch hududlardan biri."
    ),
    "material": (
        "Bino monolit (quyma beton) va gazoblokdan qurilgan, 9 ballgacha zilzilaga "
        "chidamli. Kommunikatsiyalar to'liq ulangan, isitish uchun gaz olib kelingan."
    ),
    "boshlangich_tolov": (
        "Boshlang'ich to'lov 30 mln so'mdan boshlanadi. 30 mln bilan 48 oygacha, "
        "60 mln va undan ko'p bilan 60 oygacha muddatli to'lov beriladi."
    ),
}

# (savol, kutilgan_mavzu, tur)  tur: direct | synonym | free
QUERIES: list[tuple[str, str, str]] = [
    ("parkovka bormi", "parkovka", "direct"),
    ("avtoturargoh bormi", "parkovka", "synonym"),
    ("mashina qo'yish joyi bormi", "parkovka", "free"),

    ("kafolat necha yil", "kafolat", "direct"),
    ("garantiya qancha", "kafolat", "synonym"),
    ("nuqson chiqsa nima bo'ladi", "kafolat", "free"),

    ("to'lov qanday amalga oshiriladi", "tolov_jadvali", "direct"),
    ("oylik to'lov jadvali qanday", "tolov_jadvali", "direct"),
    ("pulni qanday to'layman", "tolov_jadvali", "free"),

    ("chegirma bormi", "chegirma", "direct"),
    ("skidka qancha", "chegirma", "synonym"),
    ("arzonroq olsa bo'ladimi", "chegirma", "free"),

    ("uy qachon topshiriladi", "topshirish", "direct"),
    ("qurilish qachon bitadi", "topshirish", "free"),
    ("kvartira qachon beriladi", "topshirish", "synonym"),

    ("qanday hujjat kerak", "hujjatlar", "direct"),
    ("dokument nima kerak", "hujjatlar", "synonym"),
    ("kadastr qachon beriladi", "hujjatlar", "direct"),

    ("planirovka qanday", "planirovka", "direct"),
    ("xonadon rejasi qanaqa", "planirovka", "synonym"),
    ("2 xonali qanday joylashgan", "planirovka", "free"),

    ("qayerda joylashgan", "joylashuv", "direct"),
    ("manzil qayer", "joylashuv", "direct"),
    ("adres qanaqa", "joylashuv", "synonym"),

    ("nimadan qurilgan", "material", "direct"),
    ("zilzilaga chidaydimi", "material", "direct"),
    ("g'isht ishlatilganmi", "material", "free"),

    ("boshlang'ich to'lov qancha", "boshlangich_tolov", "direct"),
    ("pervonachalniy vznos qancha", "boshlangich_tolov", "synonym"),
    ("birinchi to'lov qancha berish kerak", "boshlangich_tolov", "free"),
]


def build_index() -> dict[int, str]:
    """Oltin bo'laklarni vaqtinchalik Chroma'ga joylaydi. {chunk_id: mavzu} qaytaradi."""
    from knowledge import vectorstore
    topics = list(GOLDEN)
    ids = list(range(1, len(topics) + 1))
    vectorstore.add_chunks(
        ids,
        [GOLDEN[t] for t in topics],
        [{"document_id": 1, "filename": "golden", "page": 1, "chunk_index": i}
         for i in ids],
    )
    return dict(zip(ids, topics))


def run_eval(hybrid: bool) -> dict:
    from knowledge import vectorstore
    id2topic = build_index()

    if hybrid:
        from knowledge import hybrid as hy
        search_fn = lambda q: hy.hybrid_search(q, top_k=3)  # noqa: E731
    else:
        search_fn = lambda q: vectorstore.search(q, top_k=3)  # noqa: E731

    rows, correct_scores, wrong_scores = [], [], []
    by_kind: dict[str, list[bool]] = {"direct": [], "synonym": [], "free": []}
    for q, expected, kind in QUERIES:
        hits = search_fn(q)
        top = max(hits, key=lambda h: h["score"]) if hits else None
        got = id2topic.get(top["chunk_id"]) if top else None
        ok = got == expected
        by_kind[kind].append(ok)
        (correct_scores if ok else wrong_scores).append(top["score"] if top else 0.0)
        rows.append((q, expected, got or "-", top["score"] if top else 0.0, ok))

    n_ok = sum(1 for *_, ok in rows if ok)
    print(f"\n{'savol':38} {'kutilgan':18} {'topildi':18} {'ball':>6}  holat")
    print("-" * 92)
    for q, exp, got, sc, ok in rows:
        print(f"{q[:37]:38} {exp:18} {got:18} {sc:6.3f}  {'✓' if ok else '✗ XATO'}")

    print("-" * 92)
    print(f"TOP-1 ANIQLIK: {n_ok}/{len(rows)} = {100*n_ok/len(rows):.0f}%")
    for kind, oks in by_kind.items():
        print(f"  {kind:8}: {sum(oks)}/{len(oks)}")
    if correct_scores:
        print(f"to'g'ri top-1 ballar:  min={min(correct_scores):.3f}  "
              f"o'rtacha={sum(correct_scores)/len(correct_scores):.3f}")
    if wrong_scores:
        print(f"noto'g'ri top-1 ballar: max={max(wrong_scores):.3f}")
        print(f"-> RAG_MIN_SCORE uchun oraliq: ({max(wrong_scores):.3f} .. "
              f"{min(correct_scores):.3f}) orasida bo'lsa ideal")
    return {"acc": n_ok / len(rows), "correct_min": min(correct_scores) if correct_scores else 0,
            "wrong_max": max(wrong_scores) if wrong_scores else 0}


def main() -> None:
    ap = argparse.ArgumentParser(description="RAG oltin-to'plam bahosi")
    ap.add_argument("--model", default=None, help="EMBED_MODEL ni vaqtincha almashtirish")
    ap.add_argument("--hybrid", action="store_true", help="gibrid qidiruv (vektor+kalit so'z)")
    args = ap.parse_args()

    if args.model:
        config.EMBED_MODEL = args.model
    # Production bazaga tegmaslik uchun vaqtinchalik papkalar
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="rag_eval_"))
    config.CHROMA_DIR = tmp / "chroma"
    config.CHROMA_DIR.mkdir(parents=True)
    config.SQLITE_PATH = tmp / "eval.db"

    mode = "GIBRID (vektor+kalit so'z)" if args.hybrid else "faqat VEKTOR"
    print(f"Model: {config.EMBED_MODEL}\nRejim: {mode}")
    run_eval(hybrid=args.hybrid)


if __name__ == "__main__":
    main()
