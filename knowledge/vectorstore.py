"""Vektor baza (ChromaDB) — semantik qidiruv.

Har bir matn bo'lagi "embedding" (raqamli vektor) ga aylantiriladi. Foydalanuvchi
savoli ham vektorlanadi va ma'no jihatdan eng yaqin bo'laklar topiladi — hatto
so'zlar aynan mos kelmasa ham (masalan "narx" va "qancha turadi").

Embedding modeli ko'p tilli (config.EMBED_MODEL). E5 oilasi (multilingual-e5-*)
uchun matnlarga maxsus prefiks kerak: hujjatga "passage: ", so'rovga "query: " —
bu shu modulda avtomatik qo'shiladi/olib tashlanadi (tashqi kod prefiksni ko'rmaydi).

DIQQAT: model almashtirilsa eski embeddinglar mos kelmaydi — kolleksiya metadata'siga
model nomi yoziladi va nomuvofiqlikda xato ko'tariladi (python ingest.py --rebuild).
"""
from __future__ import annotations

import logging

import chromadb
from chromadb.utils import embedding_functions

import config

log = logging.getLogger("vectorstore")

_collection = None

# E5 modellari uchun majburiy prefikslar (busiz sifat keskin tushadi)
_E5_QUERY = "query: "
_E5_PASSAGE = "passage: "


def _is_e5() -> bool:
    return "e5" in config.EMBED_MODEL.lower()


def get_collection():
    """Chroma kolleksiyasini (bir marta) ochadi/yaratadi.

    Mavjud kolleksiya boshqa embedding modeli bilan qurilgan bo'lsa:
      - bo'sh bo'lsa — jimgina o'chirib, joriy model bilan qayta yaratadi;
      - ma'lumotli bo'lsa — aniq xato ko'taradi (jimgina noto'g'ri qidirishdan yaxshi).
    """
    global _collection
    if _collection is not None:
        return _collection

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    try:
        existing = client.get_collection(name=config.COLLECTION_NAME)
        stored = (existing.metadata or {}).get("embed_model")
        if stored and stored != config.EMBED_MODEL:
            if existing.count() > 0:
                raise RuntimeError(
                    f"Chroma kolleksiyasi '{stored}' modeli bilan qurilgan, joriy model "
                    f"esa '{config.EMBED_MODEL}'. Indeksni qayta quring: "
                    f"python ingest.py --rebuild"
                )
            client.delete_collection(config.COLLECTION_NAME)  # bo'sh — bemalol qayta quramiz
        elif not stored and existing.count() > 0:
            log.warning("Chroma kolleksiyasida embed_model metadata yo'q (eski format) — "
                        "model mosligini tekshirib bo'lmaydi.")
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001 - kolleksiya hali yo'q, quyida yaratiladi
        pass

    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBED_MODEL
    )
    _collection = client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine", "embed_model": config.EMBED_MODEL},
    )
    return _collection


def reset_collection() -> None:
    """Kolleksiyani butunlay o'chiradi (masalan embedding modeli almashganda
    ingest.py --rebuild shu funksiyadan foydalanadi)."""
    global _collection
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    try:
        client.delete_collection(config.COLLECTION_NAME)
    except Exception:  # noqa: BLE001 - kolleksiya yo'q bo'lsa ham OK
        pass
    _collection = None


def add_chunks(chunk_ids: list[int], texts: list[str],
               metadatas: list[dict]) -> None:
    """Bo'laklarni vektor bazaga qo'shadi. id lar SQLite chunk id lari bilan bir xil."""
    if not chunk_ids:
        return
    docs = [f"{_E5_PASSAGE}{t}" for t in texts] if _is_e5() else texts
    get_collection().add(
        ids=[str(cid) for cid in chunk_ids],
        documents=docs,
        metadatas=metadatas,
    )


def search(query: str, top_k: int = 5) -> list[dict]:
    """Savolga eng mos bo'laklarni qaytaradi: [{chunk_id, text, score, meta}, ...].
    Qaytarilgan text PREFIKSSIZ (asl bo'lak matni)."""
    q = f"{_E5_QUERY}{query}" if _is_e5() else query
    res = get_collection().query(query_texts=[q], n_results=top_k)
    out: list[dict] = []
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    dists = res.get("distances", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    for cid, doc, dist, meta in zip(ids, docs, dists, metas):
        if _is_e5() and doc.startswith(_E5_PASSAGE):
            doc = doc[len(_E5_PASSAGE):]
        out.append({
            "chunk_id": int(cid),
            "text": doc,
            "score": 1 - dist,   # cosine masofani "o'xshashlik"ga aylantiramiz
            "meta": meta or {},
        })
    return out


def count() -> int:
    return get_collection().count()


def has_data() -> bool:
    """Bazada ma'lumot bor-yo'qligini EMBEDDING MODELINI YUKLAMASDAN aniqlaydi.

    get_collection() embedding funksiyasini (sentence-transformers + torch, ~400MB)
    yaratadi — bo'sh Chroma uchun buni bekorga qilmaslik kerak. Shuning uchun bu yerda
    alohida engil klient ochib, get_collection (get_or_create EMAS — yaratib qo'ymaslik
    uchun) bilan faqat count() ni o'qiymiz. Kolleksiya yo'q yoki bo'sh bo'lsa — False."""
    try:
        client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        col = client.get_collection(name=config.COLLECTION_NAME)
        return col.count() > 0
    except Exception:  # noqa: BLE001 - kolleksiya yo'q / baza ochilmadi -> ma'lumot yo'q
        return False
