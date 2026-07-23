# Testlar

Barcha testlar **loyiha ildizidan** (`D:\Project\chatbot`) ishga tushiriladi,
`.venv\Scripts\python.exe` bilan. Production bazalarga (`storage/knowledge.db`,
`backend/db.sqlite3`) yozmaydi — har biri `tempfile`/mock bilan izolyatsiyalangan.

## Tezkor start

```powershell
# Barcha OFLAYN testlar (tavsiya — kundalik ishlatish, ~1 daqiqa):
.venv\Scripts\python.exe -m pytest -m "not live"

# Oflayn + JONLI (Gemini API kvotasi sarflaydi, ~1.5 daqiqa):
.venv\Scripts\python.exe -m pytest
```

## Nima uchun `pytest.ini`da `testpaths = tests/test_pytest_bridge.py`?

Eski standalone skriptlar (`test_hybrid_units.py`, `test_price_guard.py`,
`test_stage*.py`) ATAYIN modul DARAJASIDA `sys.exit()` chaqiradi — bu ularning
`python tests/xxx.py` orqali to'g'ridan-to'g'ri ishga tushirilishini
ta'minlaydi (standalone rejim). Lekin aynan shu sabab pytest ularni
TO'G'RIDAN-TO'G'RI import qilsa, kolleksiya bosqichida yiqiladi.

Yechim: `tests/test_pytest_bridge.py` ularni **subprocess** sifatida chaqiradi
va chiqish kodini/natijasini pytest'ga "tarjima qiladi" — asl fayllarga
BIRON-BIR o'zgartirish kiritilmagan, ikkala rejim ham ishlaydi.

## Fayllar va nima tekshiradi

| Fayl | Nima tekshiradi | Tarmoq/LLM | Standalone ishga tushirish |
|------|------------------|:---:|-----------------------------|
| `rag_eval.py` | RAG semantik qidiruv aniqligi — 30 savollik oltin to'plam (lotin/sinonim/erkin) | Yo'q (lokal e5 model) | `python tests\rag_eval.py --hybrid` |
| `script_eval.py` | Kirill/sheva/lahja savollarida RAG aniqligi (28 savol: 10 kirill, 13 sheva, 5 lotin nazorat) | Yo'q (lokal) | `python tests\script_eval.py` |
| `test_hybrid_units.py` | Gibrid qidiruv birlik testlari: kirill→lotin translit, sinonim kengaytmasi, kontrast-guard | Yo'q | `python tests\test_hybrid_units.py` |
| `test_price_guard.py` | Narx-filtr: taqiqlangan summalarni aniqlash, retry-mantiq, xavfsiz-matn fallback | Yo'q (Gemini mock'langan) | `python tests\test_price_guard.py` |
| `price_policy_eval.py` | Narx siyosati — **JONLI** Gemini bilan 6 adversarial tuzoq + 2 nazorat savoli | **Ha (Gemini)** | `python tests\price_policy_eval.py` |
| `test_stage1.py` | 1-bosqich: sotilgan-planirovka filtri, albom-yuborish, "схема" so'zi ajratilishi, telefon-PII filtri | Yo'q | `python tests\test_stage1.py` |
| `test_stage4.py` | 4-bosqich: `backend.inventory_summary()` — Layout jadvalidan qurilishi, narxsizlik | Yo'q | `python tests\test_stage4.py` |
| `test_stage5_debug.py` | 5-bosqich: `/debug` oynasi (3 daqiqa), savol-aniqlash, `/bekor`, `_awaiting_plan_choice` kalitlash | Yo'q | `python tests\test_stage5_debug.py` |
| `test_instagram_webhook.py` | Instagram webhook (`instagram_bot.py`): imzo tekshiruvi, GET tasdiqlash, mid-dedup, `is_echo` orqali inson-qo'lga-olish pauzasi | Yo'q (Graph API/LLM mock'langan) | `python tests\test_instagram_webhook.py` |
| `test_multi_session.py` | Ko'p-akkaunt (bir nechta Telegram lichka): sessiya nomidan port hosil qilish, bir xil sessiya bloklanishi/turli sessiya parallel ishlashi, `--session` argumenti | Yo'q (lokal TCP-socket qulf) | `python tests\test_multi_session.py` |
| `test_pytest_bridge.py` | Yuqoridagilarni **pytest** orqali bitta buyruq bilan yuritadi (subprocess ko'prigi) | Aralash (`live` marker bilan ajratilgan) | `pytest` yoki `pytest -m "not live"` |
| `backend/inventory/tests/test_sync.py` | 4.4-bosqich: Uysot sync N+1 kamayishi (so'rov soni ≤15) va muvaffaqiyatsizlik-backoff | Yo'q (mock'langan) | `cd backend && ..\.venv\Scripts\python.exe manage.py test inventory.tests.test_sync` |

## `live` marker

Faqat `price_policy_eval.py` (narx siyosati) haqiqiy Gemini API'ga so'rov
yuboradi — bepul kvotadan foydalanadi va sekinroq ishlaydi. Bu yagona `live`
deb belgilangan test:

```powershell
pytest -m "not live"   # shu testni O'TKAZIB YUBORADI (default tavsiya)
pytest -m live          # FAQAT shu testni ishga tushiradi
pytest                  # hammasini (live bilan) ishga tushiradi
```

`rag_eval.py`/`script_eval.py` lokal embedding modelidan (`intfloat/multilingual-e5-base`)
foydalanadi — birinchi ishga tushirishda HuggingFace keshiga yuklanadi (~1.1GB),
keyingi safar internetga chiqmaydi, shuning uchun `live` deb belgilanmagan.

## Bazaviy (pasaytirish taqiqlangan) natijalar

```
tests/rag_eval.py --hybrid       -> TOP-1 30/30 (100%)
tests/script_eval.py             -> KIRILL >=9/10, SHEVA >=11/13, LOTIN 5/5
tests/test_hybrid_units.py       -> 27/27
tests/test_price_guard.py        -> 36/36
tests/price_policy_eval.py       -> filtr hech qayerda normal javobga aralashmaydi,
                                     tarif savolida rasmiy m² narxi to'liq chiqadi
```
