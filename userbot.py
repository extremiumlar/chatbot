"""Telegram AKKAUNT orqali avtomatik javob beruvchi (userbot, Telethon).

Bot API (BotFather) EMAS — bu sizning shaxsiy Telegram akkauntingizga ulanadi va
sizga kelgan shaxsiy xabarlarga Nurli diyor bilim bazasi asosida javob beradi.

Ishga tushirish:
    python userbot.py

Birinchi marta telefon raqami va Telegram yuborgan KOD so'raladi (bir marta).
Keyin sessiya saqlanadi (storage/userbot.session) va qayta so'ralmaydi.

.env da kerak:
    ANTHROPIC_API_KEY   — Claude javoblari uchun
    TELEGRAM_API_ID     — my.telegram.org dan
    TELEGRAM_API_HASH   — my.telegram.org dan

Xususiyatlar:
  - Faqat SHAXSIY (1-1) suhbatlardagi KELGAN xabarlarga javob beradi
    (guruh/kanal/bot xabarlariga va o'zingiz yozgan xabarlarga tegmaydi).
  - Menejer QO'LDA javob yozsa — o'sha suhbatda avtomatik javob
    HUMAN_TAKEOVER_MINUTES daqiqaga to'xtaydi (o'zingiz gaplashishingiz uchun).
  - Har mijoz uchun suhbat tarixi (kontekst) saqlanadi.
  - Yangi mijoz (lid) bazaga yoziladi.
"""
from __future__ import annotations

import argparse
import asyncio
import io
import logging
import re
import time
import zlib
from collections import deque
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from telethon import TelegramClient, events
from telethon.tl.types import User

import config
from knowledge import answer, db
from uysot import backend, showroom

# Loglar konsolga HAM faylga yoziladi (storage/userbot.log yoki bir nechta
# akkaunt ishlatilsa storage/userbot_<sessiya>.log, 2MB dan aylanadi) —
# konsol oynasi yopilsa ham "nega javob bermadi?" ni keyin tekshirish mumkin.
# DIQQAT: handlerlar bu yerda EMAS, main() ichida (--session argumenti
# o'qilgandan KEYIN) ulanadi — shunda har akkaunt o'z faylига yozadi va bir
# nechta jarayon BITTA log faylini bir vaqtda ochib, yozuvlarni aralashtirmaydi.
log = logging.getLogger("userbot")


def _setup_logging(session_name: str) -> None:
    """Har sessiya (akkaunt) uchun alohida log fayl. Asosiy ("userbot") sessiya
    eski nomni saqlaydi (userbot.log) — orqaga moslik, hech narsa buzilmaydi."""
    suffix = "" if session_name == config.SESSION_NAME else f"_{session_name}"
    log_path = config.STORAGE_DIR / f"userbot{suffix}.log"
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=logging.INFO,
        handlers=[
            logging.StreamHandler(),
            RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
        ],
        force=True,   # userbot.py qayta import qilinadigan holatlarda (masalan testda) ham to'g'ri ulaydi
    )

# Jarayon boshlangan payt (UTC) — catch-up qayta o'ynatgan ESKI chiquvchi xabarlarni
# jonli menejer xabaridan ajratish uchun (pastda _handle_outgoing ga qarang).
_STARTED_AT = datetime.now(timezone.utc)

# Har foydalanuvchi uchun suhbat tarixi (RAM kesh; doimiy nusxa DB dagi messages jadvalida)
_history: dict[int, list[dict]] = {}
# chat_id -> qachongacha avtomatik javob to'xtatilgan (time.monotonic sekundlari)
_paused_until: dict[int, float] = {}
# Har mijoz uchun qulf — bir vaqtda uning ikkita xabari parallel ishlanmasin (tarix poygasi)
_locks: dict[int, asyncio.Lock] = {}
# chat_id -> bot yuborayotgan xabarlar MATNI (chiquvchi sifatida ko'rinadi).
# _handle_outgoing chiquvchi xabar matnini shu ro'yxat bilan solishtiradi: mos kelsa —
# bu bot javobi; kelmasa — menejer qo'lda yozdi. (Faqat sanoq bilan qilinsa, menejer
# xabari botning navbatdagi sanog'ini "yeb", noto'g'ri klassifikatsiya bo'lardi.)
_pending_bot_texts: dict[int, deque[str]] = {}
# Rate-limit: chat_id -> oxirgi xabarlar vaqtlari (monotonic)
_msg_times: dict[int, list[float]] = {}
# Bot "qaysi turining planirovkasini yuboray?" deb so'ragan foydalanuvchilar:
# user_id -> muddat (monotonic). Shu oynada mijoz shunchaki "2 xonali" desa ham
# bu planirovka tanlovi deb qabul qilinadi (aks holda LLM'ga ketib adashardi).
# 5.6: user_id bilan kalitlanadi (chat_id EMAS) — _awaiting_bug_text bilan BIR XIL
# semantika (shaxsiy chatda chat_id == sender.id, lekin "kimga tegishli" ma'nosi
# aniqroq bo'lishi uchun ikkalasi ham user_id ishlatadi).
_awaiting_plan_choice: dict[int, float] = {}
PLAN_CHOICE_WINDOW = 600.0   # sekund (10 daqiqa)

# /debug bug-hisobot tizimi (hamma foydalanuvchi uchun ochiq): kimdir "/debug" deb yozsa,
# tavsifni shu xabardan (yoki keyingi xabaridan) olib bazaga + hisobot fayliga yozamiz.
# user_id -> muddat (monotonic): "/debug" yolg'iz kelganda keyingi xabarni kutish oynasi.
_awaiting_bug_text: dict[int, float] = {}
# 5.3: 10 daqiqadan 3 daqiqaga qisqartirildi — foydalanuvchi "/debug" deb yozib, keyin
# oddiy mijoz kabi savol berib qo'ysa, uzoq vaqt bug-kutish rejimida "qotib"
# qolmasin (bu holat pastdagi _looks_like_question bilan ham avtomatik tuzatiladi).
BUG_TEXT_WINDOW = 180.0       # sekund (3 daqiqa)
BUG_REPORT_FILE = config.STORAGE_DIR / "bug_reports.md"

MAX_TRACKED_USERS = 1000   # xotira o'smasligi uchun kuzatiladigan foydalanuvchilar chegarasi
MAX_TG_LEN = 4096          # Telegram bitta xabar uzunligi chegarasi
RATE_MAX = 20              # bitta mijozdan RATE_WINDOW ichida qabul qilinadigan maks. xabar
RATE_WINDOW = 60.0         # sekund
HISTORY_TURNS = 8          # kontekstda saqlanadigan oxirgi xabarlar soni


def _full_name(user: User) -> str:
    parts = [p for p in (user.first_name, user.last_name) if p]
    return " ".join(parts) or (user.username or "Mijoz")


def _get_lock(uid: int) -> asyncio.Lock:
    lock = _locks.get(uid)
    if lock is None:
        lock = asyncio.Lock()
        _locks[uid] = lock
    return lock


def _rate_ok(uid: int) -> bool:
    """True — agar mijoz oxirgi RATE_WINDOW sekundda RATE_MAX dan kam xabar yozgan bo'lsa."""
    now = time.monotonic()
    times = [t for t in _msg_times.get(uid, []) if now - t < RATE_WINDOW]
    times.append(now)
    _msg_times[uid] = times
    return len(times) <= RATE_MAX


def _load_history(uid: int) -> list[dict]:
    """Kontekst tarixi: RAM keshda bo'lmasa DB dan (oxirgi xabarlar) yuklaydi."""
    h = _history.get(uid)
    if h is None:
        try:
            h = db.get_recent_messages(uid, limit=HISTORY_TURNS)
        except Exception:  # noqa: BLE001
            h = []
        _history[uid] = h
    return h


def _split_message(text: str, limit: int = MAX_TG_LEN) -> list[str]:
    """Uzun javobni Telegram chegarasiga (4096) sig'adigan bo'laklarga bo'ladi.
    Bo'sh/faqat-bo'shliq matn uchun [] qaytaradi (bo'sh xabar yuborilmaydi)."""
    if not text.strip():
        return []
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:                 # bitta juda uzun qator bo'lsa — majburan bo'lamiz
            if cur:
                parts.append(cur); cur = ""
            parts.append(line[:limit]); line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur); cur = line
        else:
            cur = line if not cur else f"{cur}\n{line}"
    if cur:
        parts.append(cur)
    return [p for p in parts if p.strip()]   # bo'sh bo'laklarni chiqarib tashlaymiz


def _mark_pending(chat_id: int, text: str) -> None:
    """Bot yubormoqchi bo'lgan xabar matnini ro'yxatga qo'shadi (chat uchun maks. 10 ta)."""
    dq = _pending_bot_texts.get(chat_id)
    if dq is None:
        dq = deque(maxlen=10)
        _pending_bot_texts[chat_id] = dq
    dq.append(text)


def _unmark_pending(chat_id: int, text: str) -> None:
    """Yuborish xato bo'lsa — qo'shilgan matnni ro'yxatdan olib tashlaydi."""
    dq = _pending_bot_texts.get(chat_id)
    if dq and text in dq:
        dq.remove(text)


async def _send(event: events.NewMessage.Event, chat_id: int, text: str) -> None:
    """Javobni yuboradi (kerak bo'lsa bo'lib). Bo'sh matn yuborilmaydi. Har bo'lak matni
    _pending_bot_texts ga qo'shiladi — _handle_outgoing uni 'menejer' deb hisoblamaydi."""
    text = (text or "").strip()
    if not text:
        log.warning("Chat %s: bo'sh javob — yuborilmadi.", chat_id)
        return
    for part in _split_message(text):
        if not part.strip():
            continue
        _mark_pending(chat_id, part)
        try:
            await event.reply(part)
        except Exception:
            _unmark_pending(chat_id, part)
            raise


async def _send_file(event: events.NewMessage.Event, chat_id: int, data: bytes,
                     filename: str, caption: str, force_document: bool = True) -> None:
    """Fayl/rasm yuboradi (planirovka). Chiquvchi hodisa matni = caption bo'lgani
    uchun caption'ni _pending_bot_texts ga qo'shamiz (menejer deb hisoblanmasin)."""
    bio = io.BytesIO(data)
    bio.name = filename
    _mark_pending(chat_id, caption)
    try:
        await event.client.send_file(chat_id, bio, caption=caption,
                                     force_document=force_document)
    except Exception:
        _unmark_pending(chat_id, caption)
        raise


# Planirovka (xonadon rejasi) so'rovini aniqlash. "to'lov rejasi/plani" bilan
# adashmaslik uchun faqat ANIQ so'zlar ishlatiladi — "reja"/"режа"/"план" yakka holda
# qo'shilmaydi (aks holda "to'lov rejasi" savoli planirovka deb yuborilib ketadi).
# Mijozlar kirill yozuvida / ruscha ham yozadi — kirill variantlar ham kiritilgan.
_PLAN_WORDS = ("planirovka", "planirofka", "planirov", "planirok", "planlanirovka",
               "layout", "chizma",
               "планировк", "чизма", "план квартиры",
               # "схема"/"sxema" YAKKA holda EMAS (to'lov sxemasi bilan adashadi) —
               # faqat uy-kontekstli birikmalar ("хонадон схемаси" ichida "хонадон схема" bor):
               "хонадон схема", "квартира схема", "уй схема", "планировка схема",
               "xonadon sxema", "kvartira sxema", "uy sxema", "planirovka sxema")
_PHOTO_WORDS = ("rasm", "surat", "foto", "photo", "fotka",
                "расм", "сурат", "фото")
# "Kuchsiz" plan-so'zlar: yakka holda ishonchsiz ("to'lov plani" bilan adashadi),
# lekin UY-KONTEKSTLI so'z bilan birga kelsa planirovka so'rovi ("uy planini
# yuboring"). Salbiy to'lov-kontekst tekshiruvi bulardan ham USTUN turadi.
_PLAN_WEAK = ("plan", "план", "reja", "режа")
_HOME_WORDS = ("uy", "uyni", "uyingiz", "xonadon", "kvartira", "kvartura",
               "уй", "хонадон", "квартир")
# To'lov/kredit kontekst so'zlari (apostroflar olib tashlangan holda solishtiriladi):
# bulardan biri bo'lsa savol PLANIROVKA EMAS — "to'lov sxemasi", "ipoteka sxemasi" va h.k.
_PAYMENT_CONTEXT = ("tolov", "тулов", "тўлов", "оплат", "ипотека", "ipoteka",
                    "кредит", "kredit", "рассрочка", "rassrochka",
                    "муддатли", "muddatli")


def _wants_plan(text: str) -> bool:
    t = text.lower().replace("'", "").replace("`", "").replace("ʻ", "")
    # Salbiy kontekst: to'lov/ipoteka/kredit savoli — planirovka deb tushunilmasin
    if any(w in t for w in _PAYMENT_CONTEXT):
        return False
    if any(w in t for w in _PLAN_WORDS):
        return True
    # "uy rasmini ko'rsating" / "uy planini yuboring" kabi — kuchsiz so'z (rasm,
    # plan, reja) faqat uy/xonadon so'zi bilan birga kelsa planirovka deb olinadi
    # (to'lov-kontekst yuqorida allaqachon False qaytargan)
    if any(w in t for w in _PHOTO_WORDS + _PLAN_WEAK) and any(w in t for w in _HOME_WORDS):
        return True
    return False


def _wanted_rooms(text: str) -> int | None:
    """Matndan xona sonini ajratadi ("3 xonali", "2 xona", "3 хонали",
    "2 комнатная", "2х/3х-комнатная"). Regex raqamni TO'LIQ o'qiydi (masalan
    "62 xonali" dan "62" ni, "2" emas) — shu tufayli quyidagi 1..9 chegarasi
    "0 xonali" kabi kesilgan qiymat emas, HAQIQIY (lekin bu majmuada mavjud
    bo'lmagan) sonni to'g'ri rad etadi. Majmuada 1–9 xonali variant bor, shuning
    uchun undan tashqarisi (masalan "62 m2 xonadon"dagi 62) e'tiborsiz qoldiriladi."""
    t = text.lower()
    # (?<![mм\d]) — "m2"/"м2" dagi raqam xona soni emas (oldida m/м bo'lsa o'tkazamiz).
    # raqamdan keyin ruscha "2х"/"2x" ko'paytirish harfi ham kelishi mumkin
    m = re.search(r"(?<![mм\d])(\d+)\s*[хx]?\s*[-\s]?\s*(?:xonal|хонал|комнат)", t)
    if not m:
        m = re.search(r"(?<![mм\d])(\d+)\s*(?:xona|хона)", t)
    if not m:
        return None
    rooms = int(m.group(1))
    return rooms if 1 <= rooms <= 9 else None


def _wanted_area(text: str) -> float | None:
    """Matndan maydonni ajratadi ("62 m2", "62.8 kv", yolg'iz "62,8").
    Bir xonali turda bir necha maydon varianti bo'lganda aniqlashtirish uchun."""
    t = text.lower().replace(",", ".")
    m = re.search(r"(\d{2,3}(?:\.\d+)?)\s*(?:m2|m²|м2|м²|кв|kv)", t)
    if not m:
        m = re.fullmatch(r"\s*(\d{2,3}(?:\.\d+)?)\s*", t)   # yolg'iz raqam ham
    if not m:
        return None
    val = float(m.group(1))
    return val if 20 <= val <= 200 else None    # aql bovar qiladigan maydon oralig'i


async def _send_album(event: events.NewMessage.Event, chat_id: int,
                      files: list[tuple[bytes, str]], caption: str) -> None:
    """Bir nechta rasmni BITTA xabar (albom) qilib yuboradi — rasm-spam bo'lmasin.
    Caption faqat birinchi rasmga beriladi; _pending_bot_texts ga bir marta yoziladi
    (albomning matnsiz bo'laklari _handle_outgoing'da alohida hisobga olinadi)."""
    bios = []
    for data, name in files:
        bio = io.BytesIO(data)
        bio.name = name
        bios.append(bio)
    _mark_pending(chat_id, caption)
    try:
        if len(bios) == 1:
            await event.client.send_file(chat_id, bios[0], caption=caption,
                                         force_document=False)
        else:
            caps = [caption] + [""] * (len(bios) - 1)
            await event.client.send_file(chat_id, bios, caption=caps,
                                         force_document=False)
    except Exception:
        _unmark_pending(chat_id, caption)
        raise


def _layout_line(g: dict) -> str:
    return (f"• {g['rooms']} xonali — {g['area']} m² "
            f"({', '.join(g['blocks'])}-bloklar)")


def _save_exchange(uid: int, user_text: str, bot_text: str) -> None:
    """Suhbat juftligini DB'ga HAM RAM tarixiga yozadi. RAM'siz keyingi LLM
    javobi bu almashinuvni "ko'rmay" qolardi (RAM keshi DB'dan ustun turadi)."""
    h = _load_history(uid)
    h.append({"role": "user", "content": user_text})
    h.append({"role": "assistant", "content": bot_text})
    _history[uid] = h[-HISTORY_TURNS:]
    try:
        db.add_message(uid, "user", user_text)
        db.add_message(uid, "assistant", bot_text)
    except Exception:  # noqa: BLE001
        log.warning("Suhbatni saqlashda xato", exc_info=True)


def _record_bug(sender: User, report: str) -> int:
    """Bug-hisobotni DB'ga va storage/bug_reports.md ga yozadi; #N raqamini qaytaradi."""
    name = _full_name(sender)
    bug_id = db.add_bug_report(sender.id, name, sender.username, report)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    uname = f" (@{sender.username})" if sender.username else ""
    entry = (f"\n## Bug #{bug_id} — {stamp} — {name}{uname} [id {sender.id}]\n\n"
             f"{report.strip()}\n")
    try:
        new_file = not BUG_REPORT_FILE.exists()
        with open(BUG_REPORT_FILE, "a", encoding="utf-8") as f:
            if new_file:
                f.write("# Nurli diyor bot — test bug-hisobotlari\n")
            f.write(entry)
    except Exception:  # noqa: BLE001 - fayl yozilmasa ham DB'da bor
        log.warning("bug_reports.md ga yozishda xato", exc_info=True)
    log.info("BUG #%d qayd etildi (%s): %.80s", bug_id, name, report)
    return bug_id


# 5.3: bug-kutish holatida kelgan xabar bular bilan boshlansa yoki "?" bilan
# tugasa — bu ehtimol oddiy mijoz savoli (test-menejer ham botni sinab, mijoz
# rolida savol bergan bo'lishi mumkin), bug matni EMAS. Kutish avtomatik bekor
# qilinadi va xabar odatdagi (LLM) yo'lga yuboriladi.
_QUESTION_STARTERS = ("nima", "nimaga", "nimadan", "nechchi", "necha", "qancha",
                     "qanday", "qanaqa", "qachon", "qayerda", "qayer", "bormi",
                     "bo'ladimi", "boladimi", "mumkinmi", "kere", "kerak")
_CANCEL_WORDS = ("/bekor", "/cancel")


def _looks_like_question(text: str) -> bool:
    t = text.strip().lower()
    if not t:
        return False
    if t.endswith("?"):
        return True
    first = t.split()[0]
    return first in _QUESTION_STARTERS


async def _handle_debug(event: events.NewMessage.Event, chat_id: int,
                        sender: User, text: str) -> bool:
    """/debug oqimi: "/debug <tavsif>" — darhol yozadi; yolg'iz "/debug" —
    tavsifni keyingi xabardan (BUG_TEXT_WINDOW ichida) kutadi. LLM'ga
    YUBORILMAYDI (kvota tejaladi). /bekor — kutishni qo'lda bekor qiladi.

    Qaytaradi: True — xabar shu yerda "iste'mol qilindi" (chaqiruvchi qaytishi
    kerak); False — bu aslida bug matni emas ekan (savolga o'xshaydi), kutish
    bekor qilindi va xabar ODATDAGI (LLM) yo'lga yuborilishi kerak."""
    stripped = re.sub(r"^/debug\b", "", text, flags=re.IGNORECASE).strip()
    awaiting = sender.id in _awaiting_bug_text

    if text.strip().lower() in _CANCEL_WORDS:
        was_awaiting = _awaiting_bug_text.pop(sender.id, None) is not None
        if was_awaiting:
            await _send(event, chat_id,
                        "Bekor qilindi. Yana bug xabar qilmoqchi bo'lsangiz /debug deb yozing.")
        return True

    if awaiting and not text.strip().lower().startswith("/debug") and _looks_like_question(text):
        # Kutish paytida savolga o'xshash xabar keldi — bug matni emas, oddiy
        # savol deb hisoblaymiz: kutishni bekor qilamiz va LLM yo'liga qaytaramiz
        _awaiting_bug_text.pop(sender.id, None)
        log.info("Chat %s: /debug kutishi bekor qilindi (savolga o'xshaydi): %.60s",
                 chat_id, text)
        return False

    if not stripped and not awaiting:
        # "/debug" yolg'iz keldi (birinchi marta) — tavsifni kutamiz
        _awaiting_bug_text[sender.id] = time.monotonic() + BUG_TEXT_WINDOW
        await _send(event, chat_id,
                    "🐞 Bug tavsifini yozing (bitta xabarda): nima noto'g'ri ishladi "
                    "va sizningcha qanday tuzatish kerak? (Bekor qilish: /bekor)")
        return True

    if not stripped and awaiting:
        # Kutish paytida yana yolg'iz "/debug" yubordi — takror so'ramaymiz,
        # eslatib qo'yamiz (aks holda "/debug" so'zining o'zi bug matni bo'lib qolardi)
        await _send(event, chat_id, "Bug tavsifini kutyapman — yozing (yoki /bekor).")
        return True

    report = stripped or text.strip()
    _awaiting_bug_text.pop(sender.id, None)
    bug_id = _record_bug(sender, report)
    await _send(event, chat_id,
                f"✅ Bug #{bug_id} qayd etildi. Rahmat! Davom etavering — "
                "yangi bug topsangiz yana /debug deb yozing.")
    return True


async def _handle_plan_request(event: events.NewMessage.Event, chat_id: int,
                               uid: int, text: str) -> None:
    """Planirovka so'rovi: SOTUVDA QOLGAN turning rasmini yuboradi.

    Qoidalar: (1) sotilib bo'lgan tur rasmi YUBORILMAYDI; (2) bitta so'rovda
    ko'pi bilan BITTA tur — 2D+3D bo'lsa albom qilib bitta xabarda; (3) bir
    nechta variant mos kelsa rasm o'rniga aniqlashtiruvchi savol."""
    loop = asyncio.get_running_loop()
    try:
        avail = await loop.run_in_executor(None, backend.layouts_with_image)
        all_img = await loop.run_in_executor(
            None, lambda: backend.layouts_with_image(only_available=False))
    except Exception:  # noqa: BLE001
        log.exception("Backenddan planirovka turlarini olishda xato")
        avail, all_img = [], []

    # Hech qaysi turga rasm yuklanmagan (yoki backend ishlamayapti)
    if not all_img:
        reply = ("Kechirasiz, planirovkalar hozir tayyor emas 🙏 Telefon raqamingizni "
                 "qoldiring — menejerimiz planirovkani yuboradi.")
        await _send(event, chat_id, reply)
        _save_exchange(uid, text, reply)
        return

    # Rasmlar bor, lekin HAMMA tur sotilib bo'lgan
    if not avail:
        reply = ("Hozir barcha xonadonlar band. Telefon raqamingizni qoldiring — "
                 "yangi xonadon chiqishi bilan menejerimiz sizga birinchi bo'lib "
                 "xabar beradi 😊")
        await _send(event, chat_id, reply)
        _save_exchange(uid, text, reply)
        return

    rooms = _wanted_rooms(text)
    area = _wanted_area(text)
    chosen = [l for l in avail if rooms is None or int(l["rooms"]) == rooms]
    if area is not None:
        by_area = [l for l in chosen if abs(float(l["area"]) - area) < 0.35]
        if by_area:
            chosen = by_area

    avail_types = ", ".join(sorted({str(l["rooms"]) for l in avail}, key=int))

    # So'ralgan xona turi sotuvda yo'q
    if rooms is not None and not chosen:
        sold_out = [l for l in all_img if int(l["rooms"]) == rooms]
        if sold_out:  # tur mavjud edi, lekin sotilib bo'lgan
            reply = (f"Hozircha {rooms} xonali xonadonlarimiz sotilib bo'lgan. "
                     f"Bizda {avail_types} xonali variantlar bor — qaysi birining "
                     "planirovkasini yuboray?")
        else:
            reply = (f"Hozircha {rooms} xonali planirovka mavjud emas. Bizda "
                     f"{avail_types} xonali planirovkalar bor — qaysi birini yuboray?")
        await _send(event, chat_id, reply)
        _save_exchange(uid, text, reply)
        # Keyingi "2 xonali" kabi qisqa javob ham planirovka tanlovi sifatida qabul qilinadi
        _awaiting_plan_choice[uid] = time.monotonic() + PLAN_CHOICE_WINDOW
        return

    # Xona turi aytilmagan va bir nechta xil xona turi bor — ortiqcha yubormay, so'raymiz
    if rooms is None and len({l["rooms"] for l in chosen}) > 1:
        lines = ["Bizda quyidagi xonadon turlari (planirovkalar) bor 👇"]
        lines += [_layout_line(l) for l in chosen]
        lines.append('\nQaysi birining planirovkasini yuboray? Masalan: "3 xonali planirovka".')
        reply = "\n".join(lines)
        await _send(event, chat_id, reply)
        _save_exchange(uid, text, reply)
        _awaiting_plan_choice[uid] = time.monotonic() + PLAN_CHOICE_WINDOW
        return

    # Bitta xona turi, lekin BIR NECHTA maydon varianti — rasm yubormay aniqlashtiramiz
    if len(chosen) > 1:
        r = chosen[0]["rooms"]
        variants_txt = " va ".join(f"{float(l['area']):g} m²" for l in chosen)
        reply = (f"{r} xonali xonadonlarimiz {variants_txt} variantlarida bor — "
                 f"qaysi biri qiziqtiradi? (masalan: \"{float(chosen[0]['area']):g} m2\")")
        await _send(event, chat_id, reply)
        _save_exchange(uid, text, reply)
        _awaiting_plan_choice[uid] = time.monotonic() + PLAN_CHOICE_WINDOW
        return

    # AYNAN BITTA tur qoldi — 2D+3D rasmlarini BITTA albom-xabar qilib yuboramiz
    l = chosen[0]
    blocks = ", ".join(l.get("blocks") or [])
    caption = (
        f"{l['rooms']} xonali — {float(l['area']):g} m² planirovka 📐\n"
        + (f"Bloklar: {blocks}\n" if blocks else "")
        + f"1 m² narxi: {config.tariff_text()}.\n"
        "Ofisga tashrif buyursangiz, menejerlarimiz sizga loyiha haqida batafsil "
        "tushuntirib, chiroyli chegirmalar qilib berishadi 😊\n\n"
        "Yana savol bo'lsa yozing, yoki telefon raqamingizni qoldiring — "
        "menejerimiz siz bilan bog'lanadi. 🏠"
    )
    files: list[tuple[bytes, str]] = []
    for label, url, suffix in (("2D", l.get("image_url"), "2d"),
                               ("3D", l.get("image_3d_url"), "3d")):
        if not url:
            continue
        try:
            img = await loop.run_in_executor(None, backend.fetch_image, url)
            files.append((img, f"planirovka_{l['rooms']}xona_{float(l['area']):g}m2_{suffix}.jpg"))
        except Exception:  # noqa: BLE001
            log.exception("Planirovka (%s) rasmini olishda xato (id=%s)", label, l.get("id"))

    if files:
        try:
            await _send_album(event, chat_id, files, caption)
            _save_exchange(uid, text, "[planirovka rasmi yuborildi]")
            return
        except Exception:  # noqa: BLE001
            log.exception("Planirovka albomini yuborishda xato")
    reply = ("Kechirasiz, planirovkani yuborib bo'lmadi 🙏 Telefon raqamingizni "
             "qoldiring — menejerimiz yuboradi.")
    await _send(event, chat_id, reply)
    _save_exchange(uid, text, reply)


def _prune() -> None:
    """Xotira cheksiz o'smasligi uchun eski yozuvlarni tozalaydi."""
    now = time.monotonic()
    # Muddati o'tgan pauza va eskirgan rate-limit yozuvlarini olib tashlaymiz
    for cid in [c for c, u in _paused_until.items() if u < now]:
        _paused_until.pop(cid, None)
    for cid in [c for c, t in _msg_times.items() if not t or now - t[-1] > RATE_WINDOW]:
        _msg_times.pop(cid, None)
    # Muddati o'tgan planirovka-tanlov kutishlarini olib tashlaymiz (user_id bilan)
    for uid in [u for u, t in _awaiting_plan_choice.items() if t < now]:
        _awaiting_plan_choice.pop(uid, None)
    # Muddati o'tgan /debug tavsif-kutishlarini olib tashlaymiz
    for uid in [u for u, t in _awaiting_bug_text.items() if t < now]:
        _awaiting_bug_text.pop(uid, None)
    # Bo'shab qolgan kutilayotgan-matn ro'yxatlarini olib tashlaymiz
    for cid in [c for c, dq in _pending_bot_texts.items() if not dq]:
        _pending_bot_texts.pop(cid, None)
    # Kuzatiladigan foydalanuvchilar sonini cheklaymiz (eng eski qo'shilganini chiqaramiz)
    for d in (_history, _locks, _pending_bot_texts):
        while len(d) > MAX_TRACKED_USERS:
            d.pop(next(iter(d)))


async def _handle_incoming(event: events.NewMessage.Event) -> None:
    """Kelgan shaxsiy xabar -> bilim bazasi + Claude orqali javob."""
    if not event.is_private:
        return
    sender = await event.get_sender()
    if not isinstance(sender, User) or sender.bot or sender.is_self:
        return

    chat_id = event.chat_id
    text = (event.raw_text or "").strip()
    if not text:
        return

    # /debug — hamma foydalanuvchi uchun ochiq bug-hisobot tizimi. Pauza va
    # rate-limitdan USTUN turadi: menejer test paytida chatga aralashib pauza
    # tushirgan bo'lsa ham bug yozilsin.
    awaiting_bug = _awaiting_bug_text.get(sender.id, 0.0) > time.monotonic()
    if text.lower().startswith("/debug") or awaiting_bug:
        handled = await _handle_debug(event, chat_id, sender, text)
        if handled:
            _prune()
            return
        # handled=False: _handle_debug bu xabarni savolga o'xshab ketgani uchun
        # bug sifatida qabul qilmadi va kutishni bekor qildi — pastdagi odatdagi
        # (planirovka/LLM) yo'lga davom etamiz (return QILMAYMIZ).

    # Menejer qo'lda gaplashayotgan bo'lsa — jim turamiz
    until = _paused_until.get(chat_id, 0.0)
    if until and time.monotonic() < until:
        log.info("Chat %s: menejer rejimida, javob berilmadi.", chat_id)
        return

    # Bitta mijozning xabarlarini ketma-ket ishlaymiz (tarix poygasining oldini oladi)
    async with _get_lock(sender.id):
        if not _rate_ok(sender.id):
            log.warning("Chat %s: juda ko'p xabar (rate-limit) — o'tkazib yuborildi.", chat_id)
            return

        db.upsert_lead(sender.id, name=_full_name(sender), username=sender.username)
        log.info("Mijoz %s (%s): %s", _full_name(sender), sender.id, text[:80])

        # Planirovka so'rovi bo'lsa — LLM emas, to'g'ridan-to'g'ri rasm yuboramiz.
        # Yoki: bot hozirgina "qaysi turini yuboray?" deb so'ragan bo'lsa, mijozning
        # qisqa "2 xonali" javobi ham planirovka tanlovi deb qabul qilinadi.
        awaiting = _awaiting_plan_choice.get(sender.id, 0.0) > time.monotonic()
        if _wants_plan(text) or (awaiting and (_wanted_rooms(text) is not None
                                               or _wanted_area(text) is not None)):
            _awaiting_plan_choice.pop(sender.id, None)
            async with event.client.action(chat_id, "document"):
                await _handle_plan_request(event, chat_id, sender.id, text)
            _prune()
            return

        history = _load_history(sender.id)
        try:
            loop = asyncio.get_running_loop()
            async with event.client.action(chat_id, "typing"):
                reply = await loop.run_in_executor(None, answer.answer, text, list(history))
        except Exception:  # noqa: BLE001
            log.exception("Javob xatosi")
            fallback = ("Kechirasiz, hozir kichik texnik nosozlik bo'ldi 🙏 Biroz o'tib "
                        "qayta yozing yoki telefon raqamingizni qoldiring — "
                        "mutaxassisimiz siz bilan bog'lanadi.")
            try:  # jim qolmaymiz — mijozga yumshoq xabar
                await _send(event, chat_id, fallback)
                _save_exchange(sender.id, text, "[XATOLIK fallback] " + fallback)
            except Exception:  # noqa: BLE001
                log.exception("Fallback yuborishda ham xato")
            return

        # RAM kesh + doimiy DB tarixini yangilaymiz
        history.append({"role": "user", "content": text})
        history.append({"role": "assistant", "content": reply})
        _history[sender.id] = history[-HISTORY_TURNS:]
        try:
            db.add_message(sender.id, "user", text)
            db.add_message(sender.id, "assistant", reply)
        except Exception:  # noqa: BLE001
            log.warning("Suhbat tarixini saqlashda xato", exc_info=True)

        await _send(event, chat_id, reply)

    _prune()


async def _handle_outgoing(event: events.NewMessage.Event) -> None:
    """O'zimiz yozgan xabar. Agar bu bot javobi bo'lmasa — menejer qo'lda
    yozdi, degani; o'sha suhbatda avtomatik javobni bir muddat to'xtatamiz."""
    if not event.is_private:
        return
    # MUHIM: catch_up=True bot qayta ulanganda O'ZINING eski yuborilgan javoblarini ham
    # qayta o'ynatadi. Yangi jarayonda _pending_bot_texts bo'sh — ular "menejer yozdi"
    # deb xato tasniflanib, o'sha chatlar 30 daqiqaga jimib qolardi (bug: restartdan
    # keyin ba'zi mijozlarga javob bermay qo'yish). Shu sabab jarayon boshlanishidan
    # OLDINGI chiquvchi xabarlarni umuman e'tiborsiz qoldiramiz:
    msg_date = getattr(event.message, "date", None)
    if msg_date and msg_date < _STARTED_AT - timedelta(seconds=15):
        return
    chat_id = event.chat_id
    raw = event.raw_text or ""
    dq = _pending_bot_texts.get(chat_id)
    # Albom (media group) bo'laklari: faqat birinchi rasmda caption bor, qolganlari
    # MATNSIZ chiquvchi hodisa bo'lib keladi. Shu chatda kutilayotgan bot-matn bo'lsa,
    # matnsiz chiquvchi xabar — bot yuborgan rasm bo'lagi, menejer emas.
    if dq and not raw.strip():
        return
    # Chiquvchi xabar matni bot yuborgan matnlardan biriga mos kelsa — bu bot javobi.
    # (Bir xil matnli ikki xabar — bot va menejer aynan bir xil yozsa — nazariy chekka
    #  holat; bu murosani qabul qilamiz, sanoqqa qaraganda ancha ishonchli.)
    if dq:
        for candidate in (raw, raw.strip()):
            if candidate in dq:
                dq.remove(candidate)
                return  # bizning avtomatik javobimiz — menejer aralashuvi emas
    pause_sec = config.HUMAN_TAKEOVER_MINUTES * 60
    _paused_until[chat_id] = time.monotonic() + pause_sec
    log.info("Chat %s: menejer qo'lda yozdi ('%.40s') -> %d daqiqa avtomatik javob "
             "to'xtatildi.", chat_id, raw, config.HUMAN_TAKEOVER_MINUTES)


_lock_socket = None


# Eski (yagona akkaunt) qulf porti — orqaga moslik uchun asosiy ("userbot")
# sessiya aynan shu portni ishlatadi. Boshqa har bir sessiya nomidan
# DETERMINISTIK (crc32) hosil qilingan alohida portga bog'lanadi — shu bilan
# BIR XIL sessiya ikki marta ishga tushmaydi, LEKIN turli sessiyalar (bir nechta
# menejer lichkasi) bemalol PARALLEL ishlaydi.
_DEFAULT_LOCK_PORT = 47654
_LOCK_PORT_BASE = 47700
_LOCK_PORT_RANGE = 300


def _lock_port_for_session(session_name: str) -> int:
    if session_name == config.SESSION_NAME:
        return _DEFAULT_LOCK_PORT
    return _LOCK_PORT_BASE + (zlib.crc32(session_name.encode("utf-8")) % _LOCK_PORT_RANGE)


def _acquire_single_instance_lock(session_name: str) -> None:
    """Bir vaqtda BIR XIL sessiya (akkaunt) uchun faqat BITTA jarayon ishlashini
    kafolatlaydi — ikki marta javob va kvota isrofining oldini oladi. Turli
    sessiya nomlari (--session bilan) mustaqil portlarga bog'lanadi, shuning
    uchun bir nechta akkaunt (lichka) parallel ishlashi mumkin."""
    global _lock_socket
    import socket
    port = _lock_port_for_session(session_name)
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_socket.bind(("127.0.0.1", port))
    except OSError:
        raise SystemExit(
            f"❌ '{session_name}' sessiyasi allaqachon ishlab turibdi (boshqa nusxa ochiq).\n"
            "   Ikki nusxa = ikki marta javob + kvota isrofi.\n"
            "   Avval eski oynani yoping, keyin qaytadan ishga tushiring.\n"
            "   (Boshqa akkaunt qo'shmoqchi bo'lsangiz: start.bat <sessiya_nomi>)"
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Nurli diyor Telegram userbot (bir nechta akkaunt qo'llab-quvvatlanadi)")
    parser.add_argument(
        "--session", default=None,
        help="Sessiya (akkaunt) nomi. Bir nechta menejer lichkasini ulash uchun "
             "har biriga turli nom bering, masalan --session shahnoza. "
             "Berilmasa .env dagi TELEGRAM_SESSION (default: userbot) ishlatiladi.")
    return parser.parse_args()


def _resolve_credentials(session_name: str) -> tuple[str, str]:
    """Sessiyaga XOS api_id/api_hash bo'lsa o'shani, bo'lmasa umumiy
    TELEGRAM_API_ID/HASH ni qaytaradi.

    Nomlash: TELEGRAM_API_ID_<SESSIYA> / TELEGRAM_API_HASH_<SESSIYA> (sessiya
    nomi KATTA HARFDA, harf/raqamdan boshqa belgilar "_" ga almashtiriladi).
    Masalan --session shahnoza uchun .env'da:
        TELEGRAM_API_ID_SHAHNOZA=...
        TELEGRAM_API_HASH_SHAHNOZA=...
    Bu ixtiyoriy — har akkaunt uchun alohida my.telegram.org ilovasi
    yaratilgan bo'lsa ishlatiladi (bitta ilova bir nechta akkaunt uchun ham
    ishlayveradi — o'shanda bu maxsus qiymatlar kerak emas, umumiy ishlatiladi)."""
    import os
    key = re.sub(r"[^A-Z0-9]", "_", session_name.upper())
    api_id = os.getenv(f"TELEGRAM_API_ID_{key}") or config.TELEGRAM_API_ID
    api_hash = os.getenv(f"TELEGRAM_API_HASH_{key}") or config.TELEGRAM_API_HASH
    return api_id, api_hash


def main() -> None:
    args = _parse_args()
    session_name = args.session or config.SESSION_NAME
    session_path = config.STORAGE_DIR / session_name
    api_id, api_hash = _resolve_credentials(session_name)

    _setup_logging(session_name)
    _acquire_single_instance_lock(session_name)

    if config.LLM_PROVIDER == "gemini" and not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY .env da yo'q.")
    if config.LLM_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        raise SystemExit("ANTHROPIC_API_KEY .env da yo'q.")
    if not api_id or not api_hash:
        raise SystemExit(
            f"TELEGRAM_API_ID/HASH topilmadi ('{session_name}' sessiyasi uchun ham, "
            "umumiy sozlamada ham). https://my.telegram.org -> API development "
            "tools dan oling.\n"
            "(Bitta api_id/api_hash BIR NECHTA akkaunt uchun ishlataveradi; har "
            "akkaunt o'z ilovasiga ega bo'lishini xohlasangiz — "
            f"TELEGRAM_API_ID_{session_name.upper()}/TELEGRAM_API_HASH_{session_name.upper()} "
            "ni .env'ga qo'shing.)"
        )

    db.init_db()
    # Bilim bazasi yuklanishini oldindan tekshiramiz (xato bo'lsa darrov ko'rinadi)
    log.info("Bilim bazasi: %d belgi", len(answer.load_knowledge()))
    if session_name != config.SESSION_NAME:
        log.info("Sessiya: '%s' (storage/%s.session)", session_name, session_name)

    client = TelegramClient(
        str(session_path),
        int(api_id),
        api_hash,
        # Uzilib qayta ulanganda, o'sha oraliqda kelgan xabarlarni tiklaydi:
        catch_up=True,
        # Ulanish uzilsa cheksiz qayta urinsin (jarayon o'lmasin):
        connection_retries=None,
        retry_delay=5,
        # Serverdan uzilishlarni tezroq sezish uchun:
        auto_reconnect=True,
    )
    client.add_event_handler(_handle_incoming, events.NewMessage(incoming=True))
    client.add_event_handler(_handle_outgoing, events.NewMessage(outgoing=True))

    # Ulanish/uzilishni logga yozamiz (debug uchun — qachon uzilib-ulanayotganini ko'rasiz)
    async def _run() -> None:
        me = await client.get_me()
        log.info("Kirildi: %s. Avtomatik javob yoqildi. To'xtatish: Ctrl+C",
                 me.username or me.first_name)
        while True:
            try:
                # Offline paytda o'tkazib yuborilgan update'larni majburan tiklaymiz
                await client.catch_up()
                await client.run_until_disconnected()
                # Bu yergacha yetdi = uzildi. auto_reconnect qayta ulaydi, biz kutamiz.
                log.warning("Ulanish uzildi — qayta ulanishni kutmoqda...")
                if not client.is_connected():
                    await client.connect()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("run_until_disconnected xatosi — 5s dan keyin qayta urinaman")
                await asyncio.sleep(5)

    log.info("Akkauntga ulanmoqda... (birinchi marta telefon + kod so'raladi)")
    client.start()  # interaktiv login (faqat birinchi marta)
    with client:
        client.loop.run_until_complete(_run())


if __name__ == "__main__":
    main()
