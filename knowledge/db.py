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
-- external_id: kanal foydalanuvchi ID'si (ilgari faqat Telegram, endi Instagram-scoped ID).
CREATE TABLE IF NOT EXISTS leads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id  INTEGER UNIQUE,
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
    external_id  INTEGER NOT NULL,
    role         TEXT NOT NULL,      -- 'user' | 'assistant'
    content      TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- Test-menejerlar /debug orqali yuborgan bug-hisobotlari.
CREATE TABLE IF NOT EXISTS bug_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id  INTEGER NOT NULL,
    name         TEXT,
    username     TEXT,
    report       TEXT NOT NULL,
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc  ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_facts_cat   ON facts(category);
CREATE INDEX IF NOT EXISTS idx_messages_tg ON messages(external_id, id);
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
    """Jadvallarni yaratadi (agar mavjud bo'lmasa) va migratsiyalarni yuritadi."""
    with connect() as conn:
        conn.executescript(SCHEMA)
    migrate_timestamps()
    migrate_platform_id()


# Telegramdan Instagramga o'tish: eski jadvallarda ustun hali `telegram_id` nomida
# qolgan bo'lishi mumkin — bir martalik, idempotent ko'chirish.
_PLATFORM_ID_TABLES = ("leads", "messages", "bug_reports")


def migrate_platform_id() -> list[str]:
    """`telegram_id` ustunini `external_id`ga ko'chiradi (mavjud bo'lsa).

    SQLite `RENAME COLUMN` bog'liq indekslarni ham avtomatik yangilaydi.
    Idempotent: ustun allaqachon `external_id` bo'lsa, jadval o'tkazib yuboriladi.
    Qaytaradi: ko'chirilgan jadvallar ro'yxati."""
    conn = sqlite3.connect(config.SQLITE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    migrated: list[str] = []
    try:
        for t in _PLATFORM_ID_TABLES:
            cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({t})")]
            if not cols:              # jadval hali yaratilmagan (yangi baza)
                continue
            if "telegram_id" in cols and "external_id" not in cols:
                conn.execute(f"ALTER TABLE {t} RENAME COLUMN telegram_id TO external_id")
                migrated.append(t)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return migrated


# Vaqt migratsiyasida qayta quriladigan jadvallar: {jadval: siljitiladigan ustunlar}.
# leads.last_seen ATAYIN yo'q — u upsert_lead tomonidan allaqachon lokal vaqtda
# yangilanib turadi; bug_reports esa boshidan to'g'ri yaratilgan.
_MIGRATE_SHIFT_COLS: dict[str, list[str]] = {
    "documents": ["created_at"],
    "properties": ["created_at"],
    "facts": ["created_at"],
    "messages": ["created_at"],
    "leads": ["first_seen"],
}


def migrate_timestamps() -> dict[str, int]:
    """ESKI (UTC DEFAULT'li) jadvallarni lokal-vaqtli DDL'ga ko'chiradi.

    Muammo: `CREATE TABLE IF NOT EXISTS` mavjud jadvalning DEFAULT'ini
    o'zgartirmaydi — eski bazalarda `datetime('now')` (UTC) qolib, admin panelда
    vaqtlar 5 soat orqada ko'rinardi. Bu migratsiya har jadvalni:
      RENAME -> yangi (localtime DDL) yaratish -> ma'lumotni ko'chirish
      (eski UTC qiymatlarga +5 soat, Asia/Tashkent) -> eski jadvalni DROP.
    Idempotent: DDL'ida `localtime` bo'lgan jadval o'tkazib yuboriladi.
    Hammasi bitta tranzaksiyada; xato bo'lsa rollback. Qaytaradi:
    {jadval: ko'chirilgan qatorlar soni}."""
    conn = sqlite3.connect(config.SQLITE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    migrated: dict[str, int] = {}
    try:
        # PRAGMA tranzaksiya TASHQARISIDA bo'lishi shart (ichida no-op bo'ladi)
        conn.execute("PRAGMA foreign_keys = OFF")
        ddls = {r["name"]: (r["sql"] or "") for r in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table'")}
        targets = [t for t in _MIGRATE_SHIFT_COLS
                   if t in ddls and "datetime('now')" in ddls[t]
                   and "localtime" not in ddls[t]]
        if not targets:
            return {}

        conn.execute("BEGIN IMMEDIATE")
        for t in targets:
            cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({t})")]
            shift = set(_MIGRATE_SHIFT_COLS[t])
            conn.execute(f"ALTER TABLE {t} RENAME TO {t}_old")
            # Yangi jadval DDL'i — SCHEMA'dagi shu jadvalning o'zi
            # (executescript ishlatmaymiz: u tranzaksiyani commit qilib yuboradi)
            create_sql = _extract_create(t)
            conn.execute(create_sql)
            select_cols = ", ".join(
                f"datetime({c}, '+5 hours')" if c in shift else c for c in cols)
            conn.execute(
                f"INSERT INTO {t} ({', '.join(cols)}) "
                f"SELECT {select_cols} FROM {t}_old")
            migrated[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            conn.execute(f"DROP TABLE {t}_old")
            # AUTOINCREMENT hisoblagichi buzilmasin
            conn.execute(
                "UPDATE sqlite_sequence SET seq = (SELECT COALESCE(MAX(id),0) "
                f"FROM {t}) WHERE name = ?", (t,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.close()
    # DROP TABLE indekslarni ham o'chirgan — SCHEMA qayta yuritilib tiklanadi
    with connect() as c2:
        c2.executescript(SCHEMA)
    return migrated


def _extract_create(table: str) -> str:
    """SCHEMA matnidan bitta jadvalning CREATE TABLE blokini ajratib oladi
    (yagona haqiqat manbai SCHEMA bo'lib qolsin — DDL ikki joyda yashamasin)."""
    marker = f"CREATE TABLE IF NOT EXISTS {table} ("
    start = SCHEMA.index(marker)
    end = SCHEMA.index(");", start) + 2
    return SCHEMA[start:end]


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

def upsert_lead(external_id: int, name: str | None = None,
                username: str | None = None, phone: str | None = None) -> None:
    """Lidni qo'shadi yoki mavjudini yangilaydi. Har xabarda hisoblagichni oshiradi."""
    with connect() as conn:
        conn.execute(
            """INSERT INTO leads (external_id, name, username, phone, num_messages)
               VALUES (?, ?, ?, ?, 1)
               ON CONFLICT(external_id) DO UPDATE SET
                 name = COALESCE(excluded.name, leads.name),
                 username = COALESCE(excluded.username, leads.username),
                 phone = COALESCE(excluded.phone, leads.phone),
                 last_seen = datetime('now','localtime'),
                 num_messages = leads.num_messages + 1""",
            (external_id, name, username, phone),
        )


def get_lead(external_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM leads WHERE external_id = ?", (external_id,)
        ).fetchone()


# --- messages (suhbat tarixi — doimiy) ---

def add_message(external_id: int, role: str, content: str) -> None:
    """Bitta suhbat xabarini saqlaydi (bot qayta ishga tushsa ham kontekst qoladi)."""
    with connect() as conn:
        conn.execute(
            "INSERT INTO messages (external_id, role, content) VALUES (?, ?, ?)",
            (external_id, role, content),
        )


# --- bug_reports (test-menejerlar /debug hisobotlari) ---

def add_bug_report(external_id: int, name: str | None, username: str | None,
                   report: str) -> int:
    """Bug-hisobotni saqlaydi va uning tartib raqamini (#N) qaytaradi."""
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO bug_reports (external_id, name, username, report) "
            "VALUES (?, ?, ?, ?)",
            (external_id, name, username, report),
        )
        return cur.lastrowid


def get_bug_reports() -> list[sqlite3.Row]:
    """Barcha bug-hisobotlar (eskidan yangiga) — yakuniy hisobot uchun."""
    with connect() as conn:
        return conn.execute(
            "SELECT id, external_id, name, username, report, created_at "
            "FROM bug_reports ORDER BY id"
        ).fetchall()


def get_recent_messages(external_id: int, limit: int = 8) -> list[dict]:
    """Foydalanuvchining oxirgi `limit` ta xabarini tartib bilan qaytaradi
    ([{"role":..., "content":...}]). answer.answer() kutgan formatda."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT role, content FROM messages WHERE external_id = ? "
            "ORDER BY id DESC LIMIT ?",
            (external_id, limit),
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
            "bug_reports": count("bug_reports"),
        }


if __name__ == "__main__":
    init_db()
    print("Baza tayyor:", config.SQLITE_PATH)
    print("Holat:", stats())
