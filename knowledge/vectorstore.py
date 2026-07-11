"""Vektor baza (ChromaDB) — semantik qidiruv.

Har bir matn bo'lagi "embedding" (raqamli vektor) ga aylantiriladi. Foydalanuvchi
savoli ham vektorlanadi va ma'no jihatdan eng yaqin bo'laklar topiladi — hatto
so'zlar aynan mos kelmasa ham (masalan "narx" va "qancha turadi").

Embedding modeli ko'p tilli: o'zbek, rus va ingliz tillarini biladi.
"""
from __future__ import annotations

import chromadb
from chromadb.utils import embedding_functions

import config

_collection = None


def get_collection():
    """Chroma kolleksiyasini (bir marta) ochadi/yaratadi."""
    global _collection
    if _collection is not None:
        return _collection

    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    embed_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name=config.EMBED_MODEL
    )
    _collection = client.get_or_create_collection(
        name=config.COLLECTION_NAME,
        embedding_function=embed_fn,
        metadata={"hnsw:space": "cosine"},
    )
    return _collection


def add_chunks(chunk_ids: list[int], texts: list[str],
               metadatas: list[dict]) -> None:
    """Bo'laklarni vektor bazaga qo'shadi. id lar SQLite chunk id lari bilan bir xil."""
    if not chunk_ids:
        return
    get_collection().add(
        ids=[str(cid) for cid in chunk_ids],
        documents=texts,
        metadatas=metadatas,
    )


def search(query: str, top_k: int = 5) -> list[dict]:
    """Savolga eng mos bo'laklarni qaytaradi: [{chunk_id, text, score, meta}, ...]."""
    res = get_collection().query(query_texts=[query], n_results=top_k)
    out: list[dict] = []
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    dists = res.get("distances", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    for cid, doc, dist, meta in zip(ids, docs, dists, metas):
        out.append({
            "chunk_id": int(cid),
            "text": doc,
            "score": 1 - dist,   # cosine masofani "o'xshashlik"ga aylantiramiz
            "meta": meta or {},
        })
    return out


def count() -> int:
    return get_collection().count()
