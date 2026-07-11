# Ko'chmas mulk lead-bot — bilim bazasi (RAG)

Telegram lead-bot uchun bilim bazasi. PDF va matn ma'lumotlarni **bir marta** qayta
ishlab, tuzilgan holda bazaga saqlaydi. Keyin bot har safar PDF ni qidirmaydi —
tayyor bazadan tez, arzon va aniq javob oladi.

## Qismlar

| Fayl | Vazifasi |
|------|----------|
| `config.py` | Sozlamalar (yo'llar, model nomlari, chunk parametrlari) |
| `knowledge/db.py` | SQLite baza (hujjatlar, bo'laklar, uylar, faktlar) |
| `knowledge/pdf_reader.py` | PDF/txt dan matn ajratish |
| `knowledge/chunker.py` | Matnni bo'laklarga bo'lish |
| `knowledge/vectorstore.py` | ChromaDB — semantik qidiruv |
| `knowledge/understand.py` | Claude bilan faktlar/uylarni ajratish |
| `ingest.py` | Hammasini birlashtiruvchi — bazani quradi |
| `query.py` | Bazani sinash (savol -> mos bo'laklar) |

## O'rnatish

```powershell
# 1. Virtual muhit
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Kutubxonalar
pip install -r requirements.txt

# 3. API kaliti
copy .env.example .env
# .env ni ochib ANTHROPIC_API_KEY ni qo'ying
```

## Ishlatish

```powershell
# Ma'lumot fayllarini data/raw/ ga tashlang, keyin:
python ingest.py                       # data/raw/ dagi barcha fayllar
python ingest.py data/raw/uylar.pdf    # bitta fayl
python ingest.py data/raw/uylar.pdf --no-ai   # Claude tahlilisiz (tez, tekin)

# Bazani sinash:
python query.py "3 xonali uy narxi qancha?"
python query.py                        # interaktiv rejim
```

## Keyingi bosqichlar

- [ ] Telegram bot (`/start`, telefon so'rash, lidni saqlash)
- [ ] Claude javob generatori (RAG + faktlar -> tabiiy javob)
- [ ] Admin panel / uylarni oson qo'shish
