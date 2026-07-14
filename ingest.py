"""Ma'lumot yuklash (ingest) — RAG bazasini quradi.

Ishlatilishi:
    python ingest.py data/raw/uylar.pdf
    python ingest.py data/raw/            # papkadagi barcha PDF/txt fayllar
    python ingest.py data/raw/uylar.pdf --no-ai   # Claude tahlilisiz (faqat qidiruv indeksi)

Har bir fayl uchun:
  1) matnni o'qiydi (PDF/txt),
  2) bo'laklarga bo'lib SQLite + Chroma ga saqlaydi (semantik qidiruv uchun),
  3) Claude bilan tushunib, faktlar/uylar/xulosani ajratib SQLite ga saqlaydi.

Bir marta yuklangan fayl (hash bo'yicha) qayta yuklanmaydi.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from tqdm import tqdm

import config
from knowledge import db, pdf_reader, vectorstore
from knowledge.chunker import chunk_text

# --- PII himoyasi ---
# RAG'ga faqat UMUMIY hujjatlar kirishi kerak. Kimdir adashib mijozning shaxsiy
# shartnomasini ingest qilsa, shaxsiy ma'lumot bot javobiga chiqib ketishi mumkin.
# Quyidagi belgilar topilsa fayl o'tkazib yuboriladi (--allow-pii bilan majburlash mumkin).
_PII_PATTERNS = [
    re.compile(r"[A-Z]{2}\s?\d{7}"),   # pasport seriya-raqami (AB 1234567)
    re.compile(r"\b\d{14}\b"),         # JShShIR / PINFL (14 raqam)
]


def _looks_private(pages: list[str]) -> bool:
    """Matn shaxsiy hujjatga (mijoz shartnomasi va h.k.) o'xshaydimi."""
    head = "\n".join(pages)[:20_000]
    if any(p.search(head) for p in _PII_PATTERNS):
        return True
    # telefon raqam + shartnoma/pasport so'zlari birga kelsa — ehtimol shaxsiy shartnoma
    if re.search(r"\+998\d{9}", head) and re.search(
            r"pasport|passport|паспорт|shartnoma\s*[№#]", head, re.IGNORECASE):
        return True
    return False


def ingest_file(path: Path, use_ai: bool = True, allow_pii: bool = False) -> None:
    print(f"\n=== {path.name} ===")

    file_hash = pdf_reader.file_hash(path)
    if db.document_exists(file_hash):
        print("  ⏭  Bu fayl allaqachon yuklangan (o'tkazib yuborildi).")
        return

    # 1) O'qish
    try:
        pages, source_type = pdf_reader.read_any(path)
    except ValueError as e:
        print(f"  ⚠  {e}")
        return
    total_chars = sum(len(p) for p in pages)
    if total_chars == 0:
        print("  ⚠  Matn topilmadi (skanerlangan PDF bo'lishi mumkin — OCR kerak).")
        return
    print(f"  📄 {len(pages)} sahifa, {total_chars:,} belgi")

    # PII himoyasi: shaxsiy hujjat belgilarini tekshiramiz
    if not allow_pii and _looks_private(pages):
        print(f"  🔒 '{path.name}' shaxsiy ma'lumot (PII) saqlashi mumkin — ingest QILINMADI.\n"
              "     Umumiy hujjat ekaniga ishonchingiz komil bo'lsa: --allow-pii bilan "
              "qayta yuriting.")
        return

    doc_id = db.add_document(path.name, source_type, file_hash, num_pages=len(pages))

    # 2) Bo'laklarga bo'lish -> SQLite + Chroma
    chunk_index = 0
    batch_ids, batch_texts, batch_meta = [], [], []
    for page_no, page_text in enumerate(pages, start=1):
        for piece in chunk_text(page_text):
            cid = db.add_chunk(doc_id, chunk_index, piece, page=page_no)
            batch_ids.append(cid)
            batch_texts.append(piece)
            batch_meta.append({
                "document_id": doc_id,
                "filename": path.name,
                "page": page_no,
                "chunk_index": chunk_index,
            })
            chunk_index += 1

    print(f"  ✂  {chunk_index} bo'lak. Embedding hisoblanmoqda...")
    # Chroma ga to'plamlab qo'shamiz (embedding shu yerda hisoblanadi)
    B = 128
    for i in tqdm(range(0, len(batch_ids), B), desc="  embedding", unit="batch"):
        vectorstore.add_chunks(
            batch_ids[i:i + B], batch_texts[i:i + B], batch_meta[i:i + B]
        )
    db.update_document_meta(doc_id, title=None, summary=None, num_chunks=chunk_index)

    # 3) Claude bilan tushunish (faktlar/uylar/xulosa)
    if use_ai:
        _understand(doc_id, pages)
    else:
        print("  🤖 AI tahlili o'tkazib yuborildi (--no-ai).")

    print(f"  ✅ Tayyor. Baza holati: {db.stats()}")


def _understand(doc_id: int, pages: list[str]) -> None:
    from knowledge import understand

    blocks = understand.make_blocks(pages)
    print(f"  🤖 Claude {len(blocks)} blokni tahlil qilmoqda...")
    summaries, n_facts, n_props = [], 0, 0

    for block in tqdm(blocks, desc="  tahlil", unit="blok"):
        try:
            data = understand.extract_from_block(block)
        except Exception as e:  # noqa: BLE001 - bitta blok yiqilsa qolganini davom ettiramiz
            print(f"\n  ⚠  Blok tahlilida xato: {e}")
            continue

        if data.get("summary"):
            summaries.append(data["summary"])
        for fact in data.get("facts", []):
            db.add_fact(doc_id, fact.get("category", "umumiy"),
                        fact.get("question"), fact["answer"])
            n_facts += 1
        for prop in data.get("properties", []):
            db.add_property(doc_id, **{k: v for k, v in prop.items() if v not in (None, "")})
            n_props += 1

    full_summary = " ".join(summaries)[:2000]
    title = full_summary.split(".")[0][:120] if full_summary else None
    db.update_document_meta(doc_id, title=title, summary=full_summary)
    print(f"  🧠 {n_facts} fakt, {n_props} uy/ob'ekt ajratildi.")


def rebuild_vectors() -> None:
    """Chroma indeksini SQLite'dagi chunks'dan QAYTA quradi (hujjatlarni qayta o'qimasdan).
    Embedding modeli almashganda kerak (config.EMBED_MODEL / EMBED_MODEL env)."""
    chunks = db.get_all_chunks()
    if not chunks:
        print("SQLite'da bo'lak yo'q — qayta quradigan narsa yo'q.")
        return
    print(f"Chroma indeksi '{config.EMBED_MODEL}' bilan qayta qurilmoqda "
          f"({len(chunks)} bo'lak)...")
    vectorstore.reset_collection()
    B = 128
    for i in tqdm(range(0, len(chunks), B), desc="  embedding", unit="batch"):
        batch = chunks[i:i + B]
        vectorstore.add_chunks(
            [c["id"] for c in batch],
            [c["text"] for c in batch],
            [{"document_id": c["document_id"], "filename": c["filename"],
              "page": c["page"], "chunk_index": c["chunk_index"]} for c in batch],
        )
    print(f"✅ Tayyor: {vectorstore.count()} bo'lak yangi model bilan indekslandi.")


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG bazasini quradi (PDF/txt -> baza)")
    parser.add_argument("path", nargs="?", default=str(config.RAW_DIR),
                        help="Fayl yoki papka yo'li (default: data/raw/)")
    parser.add_argument("--no-ai", action="store_true",
                        help="Claude tahlilisiz, faqat qidiruv indeksini quradi")
    parser.add_argument("--rebuild", action="store_true",
                        help="Chroma indeksini SQLite chunks'dan qayta quradi "
                             "(embedding modeli almashganda)")
    parser.add_argument("--allow-pii", action="store_true",
                        help="PII himoyasini o'chirib, shaxsiy ma'lumot belgilari bor "
                             "faylni ham ingest qiladi (ehtiyot bo'ling!)")
    args = parser.parse_args()

    db.init_db()

    if args.rebuild:
        rebuild_vectors()
        return
    target = Path(args.path)

    if target.is_dir():
        files = sorted(
            [p for p in target.iterdir()
             if p.suffix.lower() in (".pdf", ".txt", ".md")]
        )
        if not files:
            print(f"'{target}' ichida PDF/txt fayl topilmadi. "
                  "Fayllarni data/raw/ ga tashlang.")
            return
    elif target.is_file():
        files = [target]
    else:
        print(f"Yo'l topilmadi: {target}")
        sys.exit(1)

    for f in files:
        ingest_file(f, use_ai=not args.no_ai, allow_pii=args.allow_pii)

    print(f"\n🎉 Hammasi bajarildi. Vektor bazada {vectorstore.count()} bo'lak bor.")


if __name__ == "__main__":
    main()
