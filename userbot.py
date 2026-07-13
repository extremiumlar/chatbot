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
import logging
import time

from telethon import TelegramClient, events
from telethon.tl.types import User

import config
from knowledge import answer, db

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
log = logging.getLogger("userbot")

# Har foydalanuvchi uchun suhbat tarixi (RAM kesh; doimiy nusxa DB dagi messages jadvalida)
_history: dict[int, list[dict]] = {}
# chat_id -> qachongacha avtomatik javob to'xtatilgan (time.monotonic sekundlari)
_paused_until: dict[int, float] = {}
# Har mijoz uchun qulf — bir vaqtda uning ikkita xabari parallel ishlanmasin (tarix poygasi)
_locks: dict[int, asyncio.Lock] = {}
# chat_id -> bot yuborayotgan (chiquvchi sifatida ko'rinadigan) xabarlar soni.
# _handle_outgoing shu hisobga qarab "bu bot javobimi yoki menejer qo'ldami" ni ajratadi.
_pending_bot_sends: dict[int, int] = {}
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
    """Uzun javobni Telegram chegarasiga (4096) sig'adigan bo'laklarga bo'ladi."""
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
    return parts


async def _send(event: events.NewMessage.Event, chat_id: int, text: str) -> None:
    """Javobni yuboradi (kerak bo'lsa bo'lib). Har bo'lakни _pending_bot_sends da belgilaydi,
    shunda _handle_outgoing uni 'menejer qo'lda yozdi' deb xato hisoblamaydi."""
    for part in _split_message(text):
        _pending_bot_sends[chat_id] = _pending_bot_sends.get(chat_id, 0) + 1
        try:
            await event.reply(part)
        except Exception:
            _pending_bot_sends[chat_id] = max(0, _pending_bot_sends.get(chat_id, 1) - 1)
            raise


def _prune() -> None:
    """Xotira cheksiz o'smasligi uchun eski yozuvlarni tozalaydi."""
    now = time.monotonic()
    # Muddati o'tgan pauza va eskirgan rate-limit yozuvlarini olib tashlaymiz
    for cid in [c for c, u in _paused_until.items() if u < now]:
        _paused_until.pop(cid, None)
    for cid in [c for c, t in _msg_times.items() if not t or now - t[-1] > RATE_WINDOW]:
        _msg_times.pop(cid, None)
    # Kuzatiladigan foydalanuvchilar sonini cheklaymiz (eng eski qo'shilganini chiqaramiz)
    for d in (_history, _locks):
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

        history = _load_history(sender.id)
        try:
            loop = asyncio.get_running_loop()
            async with event.client.action(chat_id, "typing"):
                reply = await loop.run_in_executor(None, answer.answer, text, list(history))
        except Exception:  # noqa: BLE001
            log.exception("Javob xatosi")
            try:  # jim qolmaymiz — mijozga yumshoq xabar
                await _send(event, chat_id,
                            "Kechirasiz, hozir kichik texnik nosozlik bo'ldi 🙏 Biroz o'tib "
                            "qayta yozing yoki telefon raqamingizni qoldiring — "
                            "mutaxassisimiz siz bilan bog'lanadi.")
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
    chat_id = event.chat_id
    pending = _pending_bot_sends.get(chat_id, 0)
    if pending > 0:
        _pending_bot_sends[chat_id] = pending - 1
        return  # bu bizning avtomatik javobimiz — menejer aralashuvi emas
    pause_sec = config.HUMAN_TAKEOVER_MINUTES * 60
    _paused_until[chat_id] = time.monotonic() + pause_sec
    log.info("Chat %s: menejer qo'lda yozdi -> %d daqiqa avtomatik javob to'xtatildi.",
             chat_id, config.HUMAN_TAKEOVER_MINUTES)


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
