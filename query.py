"""Bazani tez sinash — savol yozib, mos bo'laklar va faktlarni ko'rish.

Ishlatilishi:
    python query.py "3 xonali uy narxi qancha?"
    python query.py            # interaktiv rejim (savollarni ketma-ket yozasiz)

Bu hali bot EMAS — shunchaki RAG bazasi to'g'ri ishlayotganini tekshirish vositasi.
"""
from __future__ import annotations

import sys

from knowledge import db, vectorstore


def answer(question: str, top_k: int = 5) -> None:
    print(f"\n❓ {question}")

    hits = vectorstore.search(question, top_k=top_k)
    if not hits:
        print("  (bazada hech narsa topilmadi — avval `python ingest.py` ni ishga tushiring)")
        return

    # Chroma dan kelgan id lar bo'yicha SQLite dan to'liq meta olamiz
    rows = db.get_chunk_texts([h["chunk_id"] for h in hits])

    print("\n🔎 Eng mos bo'laklar:")
    for i, h in enumerate(hits, 1):
        row = rows.get(h["chunk_id"])
        src = f"{row['filename']} (sahifa {row['page']})" if row else "?"
        snippet = h["text"][:220].replace("\n", " ")
        print(f"  {i}. [{h['score']:.2f}] {src}\n     {snippet}...")


def main() -> None:
    db.init_db()
    if len(sys.argv) > 1:
        answer(" ".join(sys.argv[1:]))
        return

    print("Interaktiv rejim. Savol yozing (chiqish: bo'sh qatur / Ctrl+C).")
    try:
        while True:
            q = input("\n> ").strip()
            if not q:
                break
            answer(q)
    except (KeyboardInterrupt, EOFError):
        print("\nXayr!")


if __name__ == "__main__":
    main()
