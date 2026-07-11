"""PDF va matn fayllardan matn ajratish.

Asosiy: pdfplumber (matn + jadvallarni yaxshi oladi).
Zaxira: pypdf (agar pdfplumber biror sahifada muvaffaqiyatsiz bo'lsa).
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def file_hash(path: Path) -> str:
    """Fayl mazmuni bo'yicha SHA-256 — takror yuklashni aniqlash uchun."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def read_pdf_pages(path: Path) -> list[str]:
    """PDF ni sahifama-sahifa matn ro'yxati sifatida qaytaradi (indeks 0 = 1-sahifa)."""
    import pdfplumber

    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            # Jadvallar ham qo'shiladi (narx jadvallari ko'chmas mulkda muhim)
            for table in page.extract_tables() or []:
                for row in table:
                    cells = [str(c).strip() for c in row if c is not None]
                    if cells:
                        text += "\n" + " | ".join(cells)
            pages.append(text.strip())

    # Agar pdfplumber deyarli hech narsa topmasa, pypdf bilan urinib ko'ramiz
    if sum(len(p) for p in pages) < 20:
        pages = _read_pdf_pypdf(path)
    return pages


def _read_pdf_pypdf(path: Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return [(page.extract_text() or "").strip() for page in reader.pages]


def read_text_file(path: Path) -> list[str]:
    """Oddiy .txt / .md fayl — bitta 'sahifa' sifatida."""
    return [path.read_text(encoding="utf-8", errors="ignore").strip()]


def read_any(path: Path) -> tuple[list[str], str]:
    """Fayl turini aniqlab, sahifalar ro'yxati va manba turini qaytaradi."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf_pages(path), "pdf"
    if suffix in (".txt", ".md"):
        return read_text_file(path), "text"
    raise ValueError(f"Qo'llab-quvvatlanmaydigan fayl turi: {suffix}")
