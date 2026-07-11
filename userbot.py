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

# Har foydalanuvchi uchun suhbat tarixi (RAM da; qayta ishga tushsa tozalanadi)
_history: dict[int, list[dict]] = {}
# chat_id -> qachongacha avtomatik javob to'xtatilgan (time.monotonic sekundlari)
_paused_until: dict[int, float] = {}
# O'zimiz (bot) yuborgan xabar id lari — ularni "qo'lda javob" deb hisoblamaslik uchun
_bot_sent_ids: set[int] = set()


def _full_name(user: User) -> str:
    parts = [p for p in (user.first_name, user.last_name) if p]
    return " ".join(parts) or (user.username or "Mijoz")


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

    db.upsert_lead(sender.id, name=_full_name(sender), username=sender.username)
    log.info("Mijoz %s (%s): %s", _full_name(sender), sender.id, text[:80])

    history = _history.get(sender.id, [])
    try:
        loop = asyncio.get_running_loop()
        async with event.client.action(chat_id, "typing"):
            reply = await loop.run_in_executor(None, answer.answer, text, history)
    except Exception:  # noqa: BLE001
        log.exception("Javob xatosi")
        return  # jim qolamiz; menejer keyin javob beradi

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    _history[sender.id] = history[-8:]

    sent = await event.reply(reply)
    _bot_sent_ids.add(sent.id)
    if len(_bot_sent_ids) > 2000:  # xotira o'smasin
        _bot_sent_ids.clear()


async def _handle_outgoing(event: events.NewMessage.Event) -> None:
    """O'zimiz yozgan xabar. Agar bu bot javobi bo'lmasa — menejer qo'lda
    yozdi, degani; o'sha suhbatda avtomatik javobni bir muddat to'xtatamiz."""
    if not event.is_private:
        return
    if event.message.id in _bot_sent_ids:
        return  # bu bizning avtomatik javobimiz — e'tibormaymiz
    pause_sec = config.HUMAN_TAKEOVER_MINUTES * 60
    _paused_until[event.chat_id] = time.monotonic() + pause_sec
    log.info("Chat %s: menejer qo'lda yozdi -> %d daqiqa avtomatik javob to'xtatildi.",
             event.chat_id, config.HUMAN_TAKEOVER_MINUTES)


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
