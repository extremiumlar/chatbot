# Nurli diyor — Telegram sotuv yordamchisi (lead-bot)

"Nuriddin buildings" kompaniyasining **Nurli diyor** turar-joy majmuasi bo'yicha
mijozlarga (lidlarga) avtomatik javob beruvchi Telegram bot. Narx, to'lov shartlari,
qurilish holati, shartnoma bandlari va joylashuv bo'yicha savollarga javob beradi;
yangi lidlarni bazaga yozadi.

## Bot javoblari qayerdan olinadi (3 manba)

1. **Toza bilim bazasi** — `knowledge_base/*.md` (qo'lda tayyorlangan, har javobga
   to'liq beriladi). Bu asosiy manba.
2. **Jonli inventar** — `uysot/showroom.py` orqali Uysot showroom API dan real
   vaqtda: qaysi blokda qanday xonadon sotuvda, m² narxi, bandlik. (~10 daq keshlanadi.)
3. **RAG (ingest qilingan hujjatlar)** — `ingest.py` bilan yuklangan PDF/txt fayllar.
   Qidiruv **gibrid**: `intfloat/multilingual-e5-base` embedding (query:/passage:
   prefikslari avtomatik) + o'zbekcha kalit-so'z/sinonim qatlami (`knowledge/hybrid.py`,
   `knowledge/uz_synonyms.py`). Sifat o'lchovi: `python tests/rag_eval.py --hybrid`
   (oltin to'plamda 97% top-1). Embedding modelini almashtirsangiz indeksni qayta
   quring: `python ingest.py --rebuild`.
   > ⚠️ Bu yerga faqat **umumiy** hujjatlar ingest qiling (narx, shartnoma shartlari,
   > hudud). Aynan bir mijozning shaxsiy shartnomasini ingest qilmang — shaxsiy
   > ma'lumot javobga chiqib ketishi mumkin.

Model provayderi almashtiriladigan: **Gemini** (asosiy) yoki **Claude** —
`config.LLM_PROVIDER` orqali.

## Qismlar

| Fayl | Vazifasi |
|------|----------|
| `userbot.py` | **Asosiy jonli bot** — Telegram AKKAUNT orqali (Telethon) shaxsiy xabarlarga javob |
| `bot.py` | Muqobil variant — BotFather boti (python-telegram-bot) |
| `chat.py` | Terminalda sinash (Telegram'siz) |
| `knowledge/answer.py` | Javob generatori (bot miyasi): bilim bazasi + inventar + RAG -> LLM |
| `uysot/showroom.py` | Jonli xonadon inventari (Uysot showroom API) |
| `config.py` | Barcha sozlamalar (kalitlar, modellar, RAG/temperatura parametrlari) |
| `knowledge/db.py` | SQLite (lidlar, suhbat tarixi, hujjatlar, bo'laklar, faktlar) |
| `knowledge/vectorstore.py` | ChromaDB — semantik qidiruv |
| `knowledge/{pdf_reader,chunker,understand}.py` | Ingest quvuri (o'qish/bo'lish/tushunish) |
| `ingest.py` | Hujjatlarni bazaga yuklaydi (RAG uchun) |
| `query.py` | RAG bazasini sinash (savol -> mos bo'laklar) |

## O'rnatish

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

copy .env.example .env
# .env ni ochib kerakli kalitlarni to'ldiring (kamida GEMINI_API_KEY va TELEGRAM_API_ID/HASH)
```

## Ishga tushirish

```powershell
# Asosiy jonli bot (shaxsiy akkaunt orqali). Birinchi marta telefon + kod so'raladi:
python userbot.py

# Terminalda sinash (Telegram'siz):
python chat.py

# (ixtiyoriy) RAG uchun umumiy hujjatlarni yuklash:
python ingest.py data/raw/narxlar.pdf
python query.py "3 xonali uy narxi qancha?"
```

## Muhim eslatmalar

- **Xavfsizlik:** `.env`, `storage/` va `*.pdf` git'ga kirmaydi (`.gitignore`).
  API kalitlari faqat `.env` da; ularni hech qayerda ochiq qoldirmang.
- **Telegram ToS:** `userbot.py` shaxsiy akkaunt orqali javob beradi — ko'p begonaga
  avtomatik yozish spam sifatida baholanib akkaunt banlanishi mumkin. Ehtiyot bo'ling.
- **Menejer aralashuvi:** menejer suhbatga qo'lda yozsa, bot o'sha chatda
  `HUMAN_TAKEOVER_MINUTES` daqiqaga jim bo'ladi.
