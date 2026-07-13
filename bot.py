"""Telegram bot — Nuriddin buildings sotuv yordamchisi.

Ishlatilishi:
    python bot.py

.env da kerak:
    ANTHROPIC_API_KEY  — Claude javoblari uchun
    TELEGRAM_BOT_TOKEN — @BotFather dan olingan token

Bot nima qiladi:
  /start   -> salomlashadi va telefon raqami tugmasini ko'rsatadi
  telefon  -> lidni bazaga saqlaydi (sotuv bo'limi keyin bog'lanadi)
  savol    -> bilim bazasi + Claude orqali javob beradi
"""
from __future__ import annotations

import logging

from telegram import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config
from knowledge import answer, db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("bot")

WELCOME = (
    "Assalomu alaykum! 👋\n\n"
    "Men *Nuriddin buildings* kompaniyasining yordamchisiman. "
    "*Nurli diyor* turar-joy majmuasi — narxlar, to'lov shartlari, joylashuv va "
    "boshqa savollaringizga javob beraman.\n\n"
    "Sizga qulay bo'lishi uchun, iltimos, telefon raqamingizni qoldiring — "
    "mutaxassisimiz siz bilan bog'lanadi. Yoki to'g'ridan-to'g'ri savolingizni yozing. 🏠"
)

import asyncio

# Har foydalanuvchi uchun suhbat tarixi (RAM kesh; doimiy nusxa DB messages jadvalida)
_history: dict[int, list[dict]] = {}
# Bir mijozning xabarlari parallel ishlanmasin (kontekst poygasining oldini oladi)
_locks: dict[int, asyncio.Lock] = {}


def _get_lock(uid: int) -> asyncio.Lock:
    lock = _locks.get(uid)
    if lock is None:
        lock = asyncio.Lock()
        _locks[uid] = lock
    return lock


def _phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton("📞 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    db.upsert_lead(user.id, name=user.full_name, username=user.username)
    await update.message.reply_text(
        WELCOME, parse_mode="Markdown", reply_markup=_phone_keyboard()
    )


async def on_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Foydalanuvchi telefon raqamini yuborganda — lidni saqlaymiz."""
    contact = update.message.contact
    user = update.effective_user
    db.upsert_lead(user.id, name=user.full_name, username=user.username,
                   phone=contact.phone_number)
    log.info("Yangi lid telefoni: %s (%s)", contact.phone_number, user.full_name)
    await update.message.reply_text(
        "Rahmat! ✅ Raqamingiz qabul qilindi, tez orada bog'lanamiz.\n\n"
        "Endi bemalol savolingizni yozing — narx, to'lov, qurilish holati va h.k.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Oddiy matnli savol — bilim bazasi + Claude orqali javob."""
    user = update.effective_user
    question = update.message.text.strip()
    if not question:
        return

    async with _get_lock(user.id):
        db.upsert_lead(user.id, name=user.full_name, username=user.username)
        await context.bot.send_chat_action(update.effective_chat.id, "typing")

        # Kontekst: RAM keshda bo'lmasa DB dan yuklaymiz
        history = _history.get(user.id)
        if history is None:
            try:
                history = db.get_recent_messages(user.id, limit=8)
            except Exception:  # noqa: BLE001
                history = []
            _history[user.id] = history

        try:
            reply = await asyncio.to_thread(answer.answer, question, list(history))
        except Exception:  # noqa: BLE001
            log.exception("Javob xatosi")
            await update.message.reply_text(
                "Kechirasiz, texnik nosozlik yuz berdi. Biroz o'tib qayta urinib ko'ring "
                "yoki sotuv bo'limimizga qo'ng'iroq qiling."
            )
            return

        history.append({"role": "user", "content": question})
        history.append({"role": "assistant", "content": reply})
        _history[user.id] = history[-8:]
        try:
            db.add_message(user.id, "user", question)
            db.add_message(user.id, "assistant", reply)
        except Exception:  # noqa: BLE001
            log.warning("Suhbat tarixini saqlashda xato", exc_info=True)

    await update.message.reply_text(reply)


def main() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        raise SystemExit("TELEGRAM_BOT_TOKEN topilmadi. .env fayliga qo'ying (@BotFather).")
    # Kalitni tanlangan provayderga qarab tekshiramiz (gemini yoki anthropic)
    if config.LLM_PROVIDER == "gemini" and not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY topilmadi. .env fayliga qo'ying.")
    if config.LLM_PROVIDER == "anthropic" and not config.ANTHROPIC_API_KEY:
        raise SystemExit("ANTHROPIC_API_KEY topilmadi. .env fayliga qo'ying.")

    db.init_db()
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.CONTACT, on_contact))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))

    log.info("Bot ishga tushdi. To'xtatish: Ctrl+C")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
