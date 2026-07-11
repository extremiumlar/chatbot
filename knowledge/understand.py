"""Claude yordamida hujjatni "tushunish" va tuzilgan ma'lumot ajratish.

Maqsad: PDF/data ni bir marta o'qib, undan
  - qisqa sarlavha + xulosa,
  - aniq FAKTLAR (savol-javobga yaroqli),
  - UYLAR/ob'ektlar (narx, xonalar, qurilish bosqichi...)
ajratamiz va bazaga saqlaymiz. Shunda bot keyin har safar PDF ni qayta o'qimaydi.

Katta PDF uchun matn bloklarga bo'lib yuboriladi (kontekst chegarasiga sig'ishi uchun).
"""
from __future__ import annotations

import json

from anthropic import Anthropic

import config

_client: Anthropic | None = None


def _get_client() -> Anthropic:
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY topilmadi. .env fayliga kalitni qo'ying."
            )
        _client = Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


# Claude ajratadigan tuzilma. JSON qaytarishga majburlash uchun "tool" ishlatamiz.
EXTRACT_TOOL = {
    "name": "save_extracted_knowledge",
    "description": "Hujjatdan ajratilgan tuzilgan bilimni saqlash.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Bu matn bo'lagining 2-4 gaplik qisqa mazmuni (o'zbekcha).",
            },
            "facts": {
                "type": "array",
                "description": "Mijoz so'rashi mumkin bo'lgan aniq faktlar.",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": "narx | qurilish | joylashuv | shartlar | tolov | umumiy",
                        },
                        "question": {"type": "string", "description": "Tipik savol ko'rinishi"},
                        "answer": {"type": "string", "description": "Aniq, qisqa javob"},
                    },
                    "required": ["category", "answer"],
                },
            },
            "properties": {
                "type": "array",
                "description": "Matnda tilga olingan uylar/kvartiralar/ob'ektlar (bo'lsa).",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "address": {"type": "string"},
                        "rooms": {"type": "integer"},
                        "area_m2": {"type": "number"},
                        "floor": {"type": "string"},
                        "price": {"type": "string"},
                        "build_stage": {"type": "string"},
                        "status": {"type": "string"},
                    },
                },
            },
        },
        "required": ["summary", "facts"],
    },
}

SYSTEM_PROMPT = (
    "Sen ko'chmas mulk (uy sotish) kompaniyasi uchun bilim bazasini tayyorlayapsan. "
    "Senga hujjatning bir qismi beriladi. Undan mijozlar so'rashi mumkin bo'lgan aniq "
    "faktlarni (narx, qurilish bosqichi, joylashuv, to'lov shartlari va h.k.) va agar "
    "bo'lsa uylar/ob'ektlar ma'lumotini ajrat. Faqat matnda ANIQ mavjud ma'lumotni yoz, "
    "hech narsani o'ylab topma. Javoblarni o'zbek tilida yoz. "
    "Natijani save_extracted_knowledge tool orqali qaytar."
)


def extract_from_block(text: str) -> dict:
    """Bitta matn blokidan tuzilgan bilim ajratadi."""
    client = _get_client()
    resp = client.messages.create(
        model=config.MODEL_INGEST,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[EXTRACT_TOOL],
        tool_choice={"type": "tool", "name": "save_extracted_knowledge"},
        messages=[{"role": "user", "content": f"Hujjat qismi:\n\n{text}"}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "save_extracted_knowledge":
            return block.input
    return {"summary": "", "facts": [], "properties": []}


def make_blocks(pages: list[str], max_chars: int = 12000) -> list[str]:
    """Sahifalarni Claude ga yuborish uchun ~max_chars lik bloklarga birlashtiradi."""
    blocks: list[str] = []
    buf = ""
    for page in pages:
        if not page:
            continue
        if len(buf) + len(page) + 2 > max_chars and buf:
            blocks.append(buf)
            buf = page
        else:
            buf = f"{buf}\n\n{page}" if buf else page
    if buf:
        blocks.append(buf)
    return blocks
