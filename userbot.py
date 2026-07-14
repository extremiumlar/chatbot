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

import asyncio
import io
import logging
import re
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler

from telethon import TelegramClient, events
from telethon.tl.types import User

import config
from knowledge import answer, db
from uysot import showroom

# Loglar konsolga HAM faylga yoziladi (storage/userbot.log, 2MB dan aylanadi) —
# konsol oynasi yopilsa ham "nega javob bermadi?" ni keyin tekshirish mumkin.
logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        RotatingFileHandler(config.STORAGE_DIR / "userbot.log",
                            maxBytes=2_000_000, backupCount=3, encoding="utf-8"),
    ],
)
log = logging.getLogger("userbot")

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
                     filename: str, caption: str) -> None:
    """Fayl (masalan planirovka PDF) yuboradi. Chiquvchi hodisa matni = caption bo'lgani
    uchun caption'ni _pending_bot_texts ga qo'shamiz."""
    bio = io.BytesIO(data)
    bio.name = filename
    _mark_pending(chat_id, caption)
    try:
        await event.client.send_file(chat_id, bio, caption=caption, force_document=True)
    except Exception:
        _unmark_pending(chat_id, caption)
        raise


# Planirovka (xonadon rejasi) so'rovini aniqlash. "to'lov rejasi/plani" bilan
# adashmaslik uchun faqat ANIQ so'zlar ishlatiladi — "reja"/"режа"/"план" yakka holda
# qo'shilmaydi (aks holda "to'lov rejasi" savoli planirovka deb yuborilib ketadi).
# Mijozlar kirill yozuvida / ruscha ham yozadi — kirill variantlar ham kiritilgan.
_PLAN_WORDS = ("planirovka", "planirofka", "planirov", "planirok", "planlanirovka",
               "layout", "chizma",
               "планировк", "чизма", "схема", "план квартиры")
_PHOTO_WORDS = ("rasm", "surat", "foto", "photo", "fotka",
                "расм", "сурат", "фото")
_HOME_WORDS = ("uy", "uyni", "uyingiz", "xonadon", "kvartira", "kvartura",
               "уй", "хонадон", "квартир")


def _wants_plan(text: str) -> bool:
    t = text.lower().replace("'", "").replace("`", "").replace("ʻ", "")
    if any(w in t for w in _PLAN_WORDS):
        return True
    # "uy rasmini ko'rsating" kabi — faqat uy/xonadon bilan birga bo'lsa
    if any(w in t for w in _PHOTO_WORDS) and any(w in t for w in _HOME_WORDS):
        return True
    return False


def _wanted_rooms(text: str) -> int | None:
    """Matndan xona sonini ajratadi ("3 xonali", "2 xona", "3 хонали",
    "2 комнатная", "2х/3х-комнатная")."""
    t = text.lower()
    # raqamdan keyin ruscha "2х"/"2x" ko'paytirish harfi ham kelishi mumkin
    m = re.search(r"(\d)\s*[хx]?\s*[-\s]?\s*(?:xonal|хонал|комнат)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d)\s*(?:xona|хона)", t)
    if m:
        return int(m.group(1))
    return None


def _layout_line(g: dict) -> str:
    return (f"• {g['rooms']} xonali — {g['area']} m² "
            f"({', '.join(g['blocks'])}-bloklar)")


def _save_exchange(uid: int, user_text: str, bot_text: str) -> None:
    """Suhbat juftligini bazaga yozadi (diagnostika: bot NIMA deb javob berganini
    keyin DB dan ko'rish mumkin — konsol yopilgan bo'lsa ham)."""
    try:
        db.add_message(uid, "user", user_text)
        db.add_message(uid, "assistant", bot_text)
    except Exception:  # noqa: BLE001
        log.warning("Suhbatni saqlashda xato", exc_info=True)


async def _handle_plan_request(event: events.NewMessage.Event, chat_id: int,
                               uid: int, text: str) -> None:
    """Planirovka so'rovi: mos turdagi PDF(lar)ni yuboradi yoki qaysi turini so'raydi."""
    loop = asyncio.get_running_loop()
    try:
        layouts = await loop.run_in_executor(None, showroom.list_layouts)
    except Exception:  # noqa: BLE001
        log.exception("Planirovka turlarini olishda xato")
        layouts = []

    if not layouts:
        reply = ("Kechirasiz, planirovkalarni hozir yuklab bo'lmadi 🙏 Telefon "
                 "raqamingizni qoldiring — menejerimiz planirovkani yuboradi.")
        await _send(event, chat_id, reply)
        _save_exchange(uid, text, reply)
        return

    rooms = _wanted_rooms(text)
    # API rooms'ni string qaytaradi ('3'); string bo'yicha solishtiramiz
    chosen = [g for g in layouts if rooms is None or str(g["rooms"]) == str(rooms)]

    # So'ralgan xona turi yo'q
    if rooms is not None and not chosen:
        avail = ", ".join(sorted({str(g["rooms"]) for g in layouts}))
        reply = (f"Hozircha {rooms} xonali xonadon sotuvda yo'q. Mavjud turlar: "
                 f"{avail} xonali. Qaysi birining planirovkasini yuboray?")
        await _send(event, chat_id, reply)
        _save_exchange(uid, text, reply)
        return

    # Xona turi aytilmagan va bir nechta variant bor — ortiqcha PDF yubormay, so'raymiz
    if rooms is None and len(chosen) > 1:
        lines = ["Bizda hozir quyidagi xonadon turlari (planirovkalar) bor 👇"]
        lines += [_layout_line(g) for g in chosen]
        lines.append("\nQaysi birining planirovkasini yuboray? "
                     'Masalan: "3 xonali planirovka".')
        reply = "\n".join(lines)
        await _send(event, chat_id, reply)
        _save_exchange(uid, text, reply)
        return

    # PDF(lar)ni yuboramiz (har turdan bitta namuna)
    sent_any = False
    for g in chosen:
        try:
            pdf = await loop.run_in_executor(None, showroom.flat_plan_pdf, g["flat"])
        except Exception:  # noqa: BLE001
            log.exception("Planirovka PDF olishda xato (flatId=%s)", g["flat"].get("id"))
            continue
        caption = (
            f"{g['rooms']} xonali — {g['area']} m² planirovka 📐\n"
            f"Bloklar: {', '.join(g['blocks'])}\n"
            "1 m² narxi: 1–5-qavatlar — 8 990 000 so'm, 6–9-qavatlar — 8 490 000 so'm.\n"
            "Ofisga tashrif buyursangiz, menejerlarimiz sizga loyiha haqida batafsil "
            "tushuntirib, chiroyli chegirmalar qilib berishadi 😊"
        )
        try:
            await _send_file(event, chat_id, pdf,
                             f"planirovka_{g['rooms']}xona_{g['area']:g}m2.pdf", caption)
            sent_any = True
        except Exception:  # noqa: BLE001
            log.exception("Planirovka faylini yuborishda xato")

    if sent_any:
        await _send(event, chat_id,
                    "Yana savol bo'lsa yozing, yoki telefon raqamingizni qoldiring — "
                    "menejerimiz siz bilan bog'lanadi. 🏠")
        try:
            db.add_message(uid, "user", text)
            db.add_message(uid, "assistant", "[planirovka PDF yuborildi]")
        except Exception:  # noqa: BLE001
            log.warning("Tarixni saqlashda xato", exc_info=True)
    else:
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
    # Menejer qo'lda gaplashayotgan bo'lsa — jim turamiz
    until = _paused_until.get(chat_id, 0.0)
    if until and time.monotonic() < until:
        log.info("Chat %s: menejer rejimida, javob berilmadi.", chat_id)
        return

    text = (event.raw_text or "").strip()
    if not text:
        return

    # Bitta mijozning xabarlarini ketma-ket ishlaymiz (tarix poygasining oldini oladi)
    async with _get_lock(sender.id):
        if not _rate_ok(sender.id):
            log.warning("Chat %s: juda ko'p xabar (rate-limit) — o'tkazib yuborildi.", chat_id)
            return

        db.upsert_lead(sender.id, name=_full_name(sender), username=sender.username)
        log.info("Mijoz %s (%s): %s", _full_name(sender), sender.id, text[:80])

        # Planirovka so'rovi bo'lsa — LLM emas, to'g'ridan-to'g'ri PDF yuboramiz
        if _wants_plan(text):
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


def _acquire_single_instance_lock() -> None:
    """Bir vaqtda faqat BITTA userbot ishlashini kafolatlaydi.
    Ikkinchi nusxa ishga tushmaydi — ikki marta javob va kvota isrofining oldini oladi."""
    global _lock_socket
    import socket
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_socket.bind(("127.0.0.1", 47654))
    except OSError:
        raise SystemExit(
            "❌ Userbot allaqachon ishlab turibdi (boshqa nusxa ochiq).\n"
            "   Ikki nusxa = ikki marta javob + kvota isrofi.\n"
            "   Avval eski oynani yoping, keyin qaytadan ishga tushiring."
        )


def main() -> None:
    _acquire_single_instance_lock()

    if config.LLM_PROVIDER == "gemini" and not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY .env da yo'q.")
    if config.LLM_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        raise SystemExit("ANTHROPIC_API_KEY .env da yo'q.")
    if not config.TELEGRAM_API_ID or not config.TELEGRAM_API_HASH:
        raise SystemExit(
            "TELEGRAM_API_ID / TELEGRAM_API_HASH .env da yo'q. "
            "https://my.telegram.org -> API development tools dan oling."
        )

    db.init_db()
    # Bilim bazasi yuklanishini oldindan tekshiramiz (xato bo'lsa darrov ko'rinadi)
    log.info("Bilim bazasi: %d belgi", len(answer.load_knowledge()))

    client = TelegramClient(
        str(config.SESSION_PATH),
        int(config.TELEGRAM_API_ID),
        config.TELEGRAM_API_HASH,
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
