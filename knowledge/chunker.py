"""Matnni bo'laklarga (chunk) bo'lish.

Nega bo'lamiz: RAG da butun hujjatni emas, savolga eng mos KICHIK bo'lakni topamiz.
Bo'laklar orasida ozgina "overlap" qoldiramiz — jumla chegarada kesilib qolsa ham
kontekst yo'qolmasin.
"""
from __future__ import annotations

import re

import config


def _split_paragraphs(text: str) -> list[str]:
    # Ikki (yoki ko'p) qator tashlash = yangi paragraf
    parts = re.split(r"\n\s*\n", text)
    return [p.strip() for p in parts if p.strip()]


def chunk_text(text: str,
               size: int = config.CHUNK_SIZE,
               overlap: int = config.CHUNK_OVERLAP) -> list[str]:
    """Matnni ~size belgilik bo'laklarga bo'ladi, paragraf chegaralarini hurmat qilib."""
    text = text.strip()
    if not text:
        return []

    paragraphs = _split_paragraphs(text)
    chunks: list[str] = []
    buf = ""

    for para in paragraphs:
        # Agar bitta paragraf o'zi juda katta bo'lsa — uni majburan kesamiz
        if len(para) > size:
            if buf:
                chunks.append(buf.strip())
                buf = ""
            chunks.extend(_hard_split(para, size, overlap))
            continue

        if len(buf) + len(para) + 1 <= size:
            buf = f"{buf}\n{para}" if buf else para
        else:
            chunks.append(buf.strip())
            # overlap: oldingi bo'lakning oxiridan biroz olib, yangi bo'lakka ulaymiz.
            # buf[-overlap:] so'z O'RTASIDAN kesishi mumkin ("...konstruksiyasi" -> "ksiyasi"),
            # shuning uchun boshidagi chala so'zni (birinchi bo'sh joygacha) tashlaymiz.
            tail = buf[-overlap:] if overlap else ""
            if tail:
                m = re.search(r"\s", tail)
                if m and m.start() < len(tail) - 1:
                    tail = tail[m.start() + 1:]
            buf = f"{tail}\n{para}".strip()

    if buf.strip():
        chunks.append(buf.strip())
    return chunks


def _hard_split(text: str, size: int, overlap: int) -> list[str]:
    """Juda uzun uzluksiz matnni belgi bo'yicha kesish."""
    chunks = []
    start = 0
    step = max(1, size - overlap)
    while start < len(text):
        chunks.append(text[start:start + size].strip())
        start += step
    return [c for c in chunks if c]
