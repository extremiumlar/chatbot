"""Lokal chat — botni Telegram'siz, terminalda sinash.

Ishlatilishi:
    python chat.py

.env da ANTHROPIC_API_KEY bo'lishi shart. Suhbat tarixi eslab qolinadi (multi-turn).
Chiqish: 'exit' yoki Ctrl+C.
"""
from __future__ import annotations

import config
from knowledge import answer


def main() -> None:
    if not config.ANTHROPIC_API_KEY:
        print("⚠  .env da ANTHROPIC_API_KEY yo'q. Avval kalitni qo'ying.")
        return

    kb = answer.load_knowledge()
    print("🏠 Nuriddin buildings — sotuv yordamchisi (lokal test)")
    print(f"   Bilim bazasi yuklandi: {len(kb):,} belgi "
          f"({len(config.KB_FILES)} fayl).\n")
    print("   Savol yozing. Chiqish uchun 'exit'.\n")

    history: list[dict] = []
    try:
        while True:
            q = input("Siz: ").strip()
            if not q or q.lower() in ("exit", "chiqish", "quit"):
                break
            reply = answer.answer(q, history=history)
            print(f"\nBot: {reply}\n")
            # Tarixni saqlaymiz (kontekst uchun), lekin juda uzayib ketmasin
            history.append({"role": "user", "content": q})
            history.append({"role": "assistant", "content": reply})
            history = history[-8:]
    except (KeyboardInterrupt, EOFError):
        pass
    print("\nXayr! 👋")


if __name__ == "__main__":
    main()
