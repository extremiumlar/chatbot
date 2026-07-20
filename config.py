"""Loyihaning markaziy sozlamalari. Barcha yo'llar va parametrlar shu yerda."""
from pathlib import Path
import os
import sys

from dotenv import load_dotenv

# Windows terminalida emoji/o'zbekcha belgilar chiqishi uchun UTF-8 ga o'tkazamiz
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# .env faylni yuklash. override=True — .env dagi qiymatlar tizim muhitidagi
# (masalan eski/yaroqsiz) o'zgaruvchilardan ustun turadi.
load_dotenv(override=True)

# --- Yo'llar ---
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"          # foydalanuvchi PDF/matn fayllarni shu yerga tashlaydi
STORAGE_DIR = BASE_DIR / "storage"  # baza fayllari (git ga kirmaydi)
SQLITE_PATH = STORAGE_DIR / "knowledge.db"
CHROMA_DIR = STORAGE_DIR / "chroma"

# --- Bilim bazasi (bot javoblarining asosiy manbai) ---
# Qo'lda tayyorlangan toza bilim. Kichik bo'lgani uchun har javobda to'liq
# Claude ga beriladi (RAG/embedding shart emas — eng aniq usul).
KB_DIR = BASE_DIR / "knowledge_base"
KB_FILES = [                        # tartib bo'yicha birlashtiriladi
    "nurli_diyor.md",
    "shartnoma_shartlari.md",
    "hudud_atrof.md",
]

# Kerakli papkalar avtomatik yaratiladi
for _p in (RAW_DIR, STORAGE_DIR, CHROMA_DIR):
    _p.mkdir(parents=True, exist_ok=True)

# --- API kalitlar ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")  # (eski) BotFather bot uchun

# --- Telegram AKKAUNT (userbot / Telethon) ---
# my.telegram.org -> API development tools dan olinadi:
TELEGRAM_API_ID = os.getenv("TELEGRAM_API_ID", "")
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
# Sessiya fayli (bir marta login qilingach, qayta kod so'ralmaydi):
SESSION_NAME = os.getenv("TELEGRAM_SESSION", "userbot")
SESSION_PATH = STORAGE_DIR / SESSION_NAME

# Odam qo'lda javob yozsa, o'sha suhbatda avtomatik javobni shu muddatga to'xtatadi
# (menejer o'zi gaplashishi uchun). Daqiqalarda:
HUMAN_TAKEOVER_MINUTES = int(os.getenv("HUMAN_TAKEOVER_MINUTES", "30"))

# --- Test-menejerlar (/debug bug-hisobot tizimi) ---
# Vergul bilan ajratilgan Telegram ID'lar: TESTER_IDS=123456,789012,345678
# Ro'yxat BO'SH bo'lsa /debug hamma uchun ochiq (sinov rejimi).
TESTER_IDS: frozenset[int] = frozenset(
    int(x) for x in os.getenv("TESTER_IDS", "").replace(";", ",").split(",")
    if x.strip().isdigit()
)

# --- LLM provayderi (bot javoblari uchun) ---
# "gemini" yoki "anthropic". Almashtirish uchun shuni o'zgartiring (yoki .env da LLM_PROVIDER).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")

# --- Google Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
# gemini-2.5-flash bepul tarifi juda kichik (kuniga ~20). flash-lite kvotasi kattaroq,
# tezroq va arzonroq. Sifat uchun to'lov yoqilsa "gemini-2.5-flash" ga qaytish mumkin.
MODEL_CHAT_GEMINI = os.getenv("MODEL_CHAT_GEMINI", "gemini-2.5-flash-lite")

# Kvota (429) tugaganda navbat bilan sinaladigan modellar zanjiri.
# Har bir modelning ALOHIDA kunlik bepul kvotasi bor — bittasi tugasa keyingisi ishlaydi.
# TARTIB MUHIM: eng BARQAROR (kam xato beradigan) model birinchi turishi kerak; kvotasi
# tez tugaydigan yoki sekin modelni zanjir OXIRIGA qo'ying — shunda birinchi urinish tez o'tadi.
# .env da GEMINI_MODELS="model1,model2,..." bilan o'zgartirish mumkin.
_gemini_chain = os.getenv(
    "GEMINI_MODELS",
    "gemini-2.5-flash-lite,gemini-2.0-flash,gemini-2.5-flash,gemini-2.0-flash-lite",
)
GEMINI_MODELS: list[str] = []
for _m in [MODEL_CHAT_GEMINI, *_gemini_chain.split(",")]:
    _m = _m.strip()
    if _m and _m not in GEMINI_MODELS:      # asosiy model birinchi, keyin zanjir (takrorsiz)
        GEMINI_MODELS.append(_m)

# --- Anthropic (Claude) ---
# Ingest (tushunish/tartiblash) uchun arzon va tez model:
MODEL_INGEST = "claude-haiku-4-5-20251001"
# Bot javoblari uchun (LLM_PROVIDER="anthropic" bo'lsa):
MODEL_CHAT = "claude-sonnet-5"

# --- Uysot showroom (inventar) API — jonli xonadonlar (qaysi blok, narx, m²) ---
UYSOT_SHOWROOM_BASE = os.getenv(
    "UYSOT_SHOWROOM_BASE", "https://srv.showroom.app.uysot.uz/v1/website")
UYSOT_SHOWROOM_TOKEN = os.getenv("UYSOT_SHOWROOM_TOKEN", "")
UYSOT_HOUSE_ID = os.getenv("UYSOT_HOUSE_ID", "880")   # Nurli Diyor Residence
UYSOT_CACHE_TTL = int(os.getenv("UYSOT_CACHE_TTL", "600"))  # inventar keshi (sekund)

# --- Django backend (xonadon turlari + yuklangan planirovka rasmlari) ---
BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://127.0.0.1:8010")
BACKEND_CACHE_TTL = int(os.getenv("BACKEND_CACHE_TTL", "300"))  # sekund

# --- Javob generatsiyasi ---
# Faktik (narx/shart) javoblar uchun past temperatura — kamroq "ijod", ko'proq aniqlik.
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.3"))

# --- RASMIY m² TARIF (yagona manba — narx o'zgarsa FAQAT shu yerda yangilanadi) ---
# Bot promptidagi narx qoidasi, narx-filtr (price_guard) ruxsati va planirovka
# izohlari hammasi shu qiymatlardan olinadi. .env orqali ham o'zgartirsa bo'ladi.
TARIFF_M2_LOW_FLOORS = int(os.getenv("TARIFF_M2_LOW_FLOORS", "8990000"))    # 1-5-qavat
TARIFF_M2_HIGH_FLOORS = int(os.getenv("TARIFF_M2_HIGH_FLOORS", "8490000"))  # 6-9-qavat


def tariff_text() -> str:
    """Rasmiy tarifning matnli ko'rinishi (prompt/izohlarda ishlatiladi)."""
    low = f"{TARIFF_M2_LOW_FLOORS:,}".replace(",", " ")
    high = f"{TARIFF_M2_HIGH_FLOORS:,}".replace(",", " ")
    return (f"1–5-qavatlar — {low} so'm/m², "
            f"6–9-qavatlar — {high} so'm/m²")

# --- RAG (semantik qidiruv botga ulanadi) ---
# RAG'ni butunlay o'chirish (masalan kichik VPS'da torch yuklanmasin uchun): RAG_ENABLED=0
RAG_ENABLED = os.getenv("RAG_ENABLED", "1") == "1"
# Har savolda vektor bazadan olinadigan mos bo'laklar soni:
RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
# Shu chegaradan pastdagi bo'laklar tashlanadi. Ball — GIBRID yakuniy ball
# (vektor*RAG_VECTOR_WEIGHT + kalit_so'z*(1-W)). e5+gibrid kalibrlash (tests/rag_eval.py):
# to'g'ri javoblarning eng pasti ~0.46 — shuning uchun 0.45 (to'g'rilar o'tadi):
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.45"))
# Gibrid qidiruvda VEKTOR ballning ulushi (qolgani kalit-so'z balli, 0..1):
RAG_VECTOR_WEIGHT = float(os.getenv("RAG_VECTOR_WEIGHT", "0.6"))
# Kontrast himoyasi: top-1 ball qolgan nomzodlar o'rtachasidan kamida shuncha
# yuqori bo'lmasa (hamma ball "yopishgan"), RAG natijasi promptga qo'shilmaydi:
RAG_MIN_CONTRAST = float(os.getenv("RAG_MIN_CONTRAST", "0.05"))

# --- Chunking (bo'laklarga bo'lish) parametrlari ---
CHUNK_SIZE = 900        # bir bo'lakdagi taxminiy belgilar soni
CHUNK_OVERLAP = 150     # qo'shni bo'laklar orasidagi ustma-ust qism (kontekst yo'qolmasligi uchun)

# --- Embedding modeli (ko'p tilli: o'zbek/rus/ingliz) ---
# intfloat/multilingual-e5-base — MiniLM'dan ancha kuchli kross-til qidiruv
# (oltin-to'plam bahosida MiniLM ~20% top-1 berdi — o'zbekchada yaroqsiz).
# E5 "query:"/"passage:" prefikslarini talab qiladi — vectorstore.py avtomatik qo'shadi.
# Model almashtirilsa indeksni qayta qurish shart: python ingest.py --rebuild
EMBED_MODEL = os.getenv("EMBED_MODEL", "intfloat/multilingual-e5-base")
COLLECTION_NAME = "knowledge"
