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
import sys
from pathlib import Path

from tqdm import tqdm

import config
from knowledge import db, pdf_reader, vectorstore
from knowledge.chunker import chunk_text


def ingest_file(path: Path, use_ai: bool = True) -> None:
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


def main() -> None:
    parser = argparse.ArgumentParser(description="RAG bazasini quradi (PDF/txt -> baza)")
    parser.add_argument("path", nargs="?", default=str(config.RAW_DIR),
                        help="Fayl yoki papka yo'li (default: data/raw/)")
    parser.add_argument("--no-ai", action="store_true",
                        help="Claude tahlilisiz, faqat qidiruv indeksini quradi")
    args = parser.parse_args()

    db.init_db()
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
        ingest_file(f, use_ai=not args.no_ai)

    print(f"\n🎉 Hammasi bajarildi. Vektor bazada {vectorstore.count()} bo'lak bor.")


if __name__ == "__main__":
    main()
