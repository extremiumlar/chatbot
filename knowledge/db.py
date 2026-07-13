"""SQLite baza — tuzilgan ma'lumotlar (hujjatlar, bo'laklar, uylar, faktlar).

Chroma (vektor baza) semantik qidiruv uchun; bu yerda esa aniq, tuzilgan
ma'lumot saqlanadi: qaysi hujjat, qaysi sahifa, qaysi uy, va Claude ajratgan faktlar.

Vaqt belgilari: barcha DEFAULT'lar `datetime('now','localtime')` — lokal vaqt
(UTC emas). DIQQAT: `CREATE TABLE IF NOT EXISTS` mavjud jadvalni O'ZGARTIRMAYDI —
eskidan yaratilgan storage/knowledge.db da eski (UTC) DEFAULT'lar joyida qoladi;
faqat yangi INSERT'lar va upsert_lead lokal vaqt yozadi. To'liq migratsiya uchun
bazani qaytadan yaratish (yoki ALTER) kerak — bu qabul qilinadigan cheklov.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

import config

SCHEMA = """
-- Yuklangan har bir manba fayl (PDF, matn, va h.k.)
CREATE TABLE IF NOT EXISTS documents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    filename    TEXT NOT NULL,
    source_type TEXT NOT NULL DEFAULT 'pdf',   -- pdf | text | manual
    title       TEXT,                          -- Claude bergan sarlavha/xulosa
    summary     TEXT,                          -- Claude qisqa mazmuni
    num_pages   INTEGER,
    num_chunks  INTEGER DEFAULT 0,
    file_hash   TEXT UNIQUE,                   -- takror yuklashni oldini olish
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Hujjat matnining bo'laklari (RAG uchun). Har bo'lak Chroma da ham embed qilinadi.
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,              -- hujjat ichidagi tartib raqami
    page        INTEGER,                       -- taxminiy sahifa
    text        TEXT NOT NULL,
    UNIQUE(document_id, chunk_index)
);

-- Uylar / ob'ektlar — tuzilgan sotuv ma'lumotlari.
-- Claude PDF dan avtomatik to'ldirishi yoki qo'lda kiritilishi mumkin.
CREATE TABLE IF NOT EXISTS properties (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id    INTEGER REFERENCES documents(id) ON DELETE SET NULL,
    name           TEXT,          -- "Yunusobod 12-uy" yoki blok/kvartira nomi
    address        TEXT,
    rooms          INTEGER,       -- xonalar soni
    area_m2        REAL,          -- maydoni
    floor          TEXT,
    price          TEXT,          -- narx (matn, valyuta bilan)
    build_stage    TEXT,          -- qurilish bosqichi / topshirish sanasi
    status         TEXT,          -- sotuvda | band | sotilgan
    extra          TEXT,          -- qo'shimcha (JSON yoki erkin matn)
    created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Faktlar — Claude PDF/data dan ajratgan aniq "savol-javob"ga yaroqli faktlar.
-- Bot ba'zi savollarga qidiruvsiz, to'g'ridan-to'g'ri shu yerdan javob bera oladi.
CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER REFERENCES documents(id) ON DELETE CASCADE,
    category    TEXT,             -- narx | qurilish | joylashuv | shartlar | umumiy ...
    question    TEXT,             -- tipik savol ko'rinishi
    answer      TEXT NOT NULL,    -- aniq javob
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Lidlar — botga yozgan mijozlar (sotuv bo'limi keyin bog'lanadi).
CREATE TABLE IF NOT EXISTS leads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER UNIQUE,
    name         TEXT,
    username     TEXT,
    phone        TEXT,
    first_seen   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_seen    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    num_messages INTEGER DEFAULT 0
);

-- Suhbat tarixi — bot qayta ishga tushsa ham kontekst yo'qolmasligi uchun doimiy saqlanadi.
CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  INTEGER NOT NULL,
    role         TEXT NOT NULL,      -- 'user' | 'assistant'
    content      TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc  ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_facts_cat   ON facts(category);
CREATE INDEX IF NOT EXISTS idx_messages_tg ON messages(telegram_id, id);
"""


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Baza ulanishi (foreign key + WAL yoqilgan holda).

    WAL rejimi va busy_timeout — bir vaqtda bir nechta thread (Telethon executor)
    yozganda 'database is locked' xatosining oldini oladi."""
    conn = sqlite3.connect(config.SQLITE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Jadvallarni yaratadi (agar mavjud bo'lmasa)."""
    with connect() as conn:
        conn.executescript(SCHEMA)


# --- documents ---

def document_exists(file_hash: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM documents WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        return row is not None


def add_document(filename: str, source_type: str, file_hash: str,
                 num_pages: int | None = None) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO documents (filename, source_type, file_hash, num_pages) "
            "VALUES (?, ?, ?, ?)",
            (filename, source_type, file_hash, num_pages),
        )
        return cur.lastrowid


def update_document_meta(document_id: int, title: str | None, summary: str | None,
                         num_chunks: int | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE documents SET title = COALESCE(?, title), "
            "summary = COALESCE(?, summary), "
            "num_chunks = COALESCE(?, num_chunks) WHERE id = ?",
            (title, summary, num_chunks, document_id),
        )


# --- chunks ---

def add_chunk(document_id: int, chunk_index: int, text: str,
              page: int | None = None) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO chunks (document_id, chunk_index, page, text) "
            "VALUES (?, ?, ?, ?)",
            (document_id, chunk_index, page, text),
        )
        return cur.lastrowid


def get_all_chunks() -> list[sqlite3.Row]:
    """Barcha bo'laklar (id, text, page, chunk_index, document_id, filename) —
    Chroma indeksini qayta qurish (ingest.py --rebuild) uchun."""
    with connect() as conn:
        return conn.execute(
            """SELECT c.id, c.text, c.page, c.chunk_index, c.document_id, d.filename
               FROM chunks c JOIN documents d ON d.id = c.document_id
               ORDER BY c.id"""
        ).fetchall()


def get_chunk_texts(chunk_ids: list[int]) -> dict[int, sqlite3.Row]:
    """Chroma qaytargan chunk id lar bo'yicha to'liq matn va meta ma'lumotni oladi."""
    if not chunk_ids:
        return {}
    placeholders = ",".join("?" * len(chunk_ids))
    with connect() as conn:
        rows = conn.execute(
            f"""SELECT c.id, c.text, c.page, c.document_id, d.filename, d.title
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.id IN ({placeholders})""",
            chunk_ids,
        ).fetchall()
        return {row["id"]: row for row in rows}


# --- facts / properties ---

def add_fact(document_id: int | None, category: str, question: str | None,
             answer: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO facts (document_id, category, question, answer) "
            "VALUES (?, ?, ?, ?)",
            (document_id, category, question, answer),
        )
        return cur.lastrowid


def add_property(document_id: int | None, **fields) -> int:
    cols = ["document_id"] + list(fields.keys())
    vals = [document_id] + list(fields.values())
    placeholders = ",".join("?" * len(cols))
    with connect() as conn:
        cur = conn.execute(
            f"INSERT INTO properties ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        return cur.lastrowid


def get_all_facts(limit: int = 200) -> list[sqlite3.Row]:
    """Barcha faktlar (kichik bilim bazasida hammasini kontekstga qo'shamiz)."""
    with connect() as conn:
        return conn.execute(
            "SELECT category, question, answer FROM facts ORDER BY category LIMIT ?",
            (limit,),
        ).fetchall()


def get_all_properties(limit: int = 100) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(
            "SELECT name, address, rooms, area_m2, floor, price, build_stage, status "
            "FROM properties LIMIT ?",
            (limit,),
        ).fetchall()


# --- leads (botga yozgan mijozlar) ---

def upsert_lead(telegram_id: int, name: str | None = None,
                username: str | None = None, phone: str | None = None) -> None:
    """Lidni qo'shadi yoki mavjudini yangilaydi. Har xabarda hisoblagichni oshiradi."""
    with connect() as conn:
        conn.execute(
            """INSERT INTO leads (telegram_id, name, username, phone, num_messages)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(telegram_id) DO UPDATE SET
                 name = COALESCE(excluded.name, leads.name),
                 username = COALESCE(excluded.username, leads.username),
                 phone = COALESCE(excluded.phone, leads.phone),
                 last_seen = datetime('now','localtime'),
                 num_messages = leads.num_messages + 1""",
            (telegram_id, name, username, phone),
        )


def get_lead(telegram_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM leads WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()


# --- messages (suhbat tarixi — doimiy) ---

def add_message(telegram_id: int, role: str, content: str) -> None:
    """Bitta suhbat xabarini saqlaydi (bot qayta ishga tushsa ham kontekst qoladi)."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (telegram_id, role, content) VALUES (?, ?, ?)",
            (telegram_id, role, content),
        )


def get_recent_messages(telegram_id: int, limit: int = 8) -> list[dict]:
    """Foydalanuvchining oxirgi `limit` ta xabarini tartib bilan qaytaradi
    ([{"role":..., "content":...}]). answer.answer() kutgan formatda."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE telegram_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (telegram_id, limit),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def stats() -> dict:
    """Baza holati — nechta hujjat, bo'lak, uy, fakt bor."""
    with connect() as conn:
        def count(t: str) -> int:
            return conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        return {
            "documents": count("documents"),
            "chunks": count("chunks"),
            "properties": count("properties"),
            "facts": count("facts"),
            "leads": count("leads"),
        }


if __name__ == "__main__":
    init_db()
    print("Baza tayyor:", config.SQLITE_PATH)
    print("Holat:", stats())
