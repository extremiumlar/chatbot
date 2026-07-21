"""5-BOSQICH (5.3, 5.6) testlari: /debug oynasi qisqarishi, savol-aniqlash,
/bekor, va _awaiting_plan_choice endi user_id bilan ishlashi.

Ishlatilishi:  .venv\\Scripts\\python.exe tests\\test_stage5_debug.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import pathlib

sys.path.insert(0, os.path.abspath("."))

import config

_tmp = pathlib.Path(tempfile.mkdtemp())
config.SQLITE_PATH = _tmp / "t.db"
config.STORAGE_DIR = _tmp

import userbot
from knowledge import db
from telethon.tl.types import User

userbot.BUG_REPORT_FILE = _tmp / "bug_reports.md"
db.init_db()


class FakeEvent:
    def __init__(self, text, cid, sink):
        self.raw_text = text
        self.chat_id = cid
        self.is_private = True
        self._sink = sink
        self._sender = None
        class _C:
            def action(s, c, k):
                class A:
                    async def __aenter__(s2): return s2
                    async def __aexit__(s2, *a): return False
                return A()
        self.client = _C()

    async def get_sender(self):
        return self._sender

    async def reply(self, t):
        self._sink.append(t)
        class M: id = 1
        return M()


def mk_user(uid, name="Tester"):
    u = User(id=uid, first_name=name, bot=False)
    u.is_self = False
    u.username = None
    return u


async def send(uid, text):
    sink = []
    ev = FakeEvent(text, uid, sink)
    ev._sender = mk_user(uid)
    await userbot._handle_incoming(ev)
    return sink


PASS, FAIL = 0, []
def check(n, c):
    global PASS
    PASS += c
    if not c: FAIL.append(n)
    print(f"  {'✓' if c else '✗ FAIL'}  {n}")


async def main():
    llm_calls = {"n": 0}
    from knowledge import answer as ans
    def fake_answer(q, history=None):
        llm_calls["n"] += 1
        return "MOCK javob"
    ans.answer = fake_answer
    userbot.answer.answer = fake_answer

    print("=== 1) BUG_TEXT_WINDOW = 3 daqiqa (180s) ===")
    check("oyna 180s ga qisqartirilgan", userbot.BUG_TEXT_WINDOW == 180.0)

    print("=== 2) /debug -> savol kelsa avtomatik bekor, LLM'ga boradi ===")
    userbot._awaiting_bug_text.clear()
    out = await send(111, "/debug")
    check("tavsif so'raldi", any("tavsif" in t.lower() for t in out))
    check("awaiting holatga tushdi", 111 in userbot._awaiting_bug_text)

    out2 = await send(111, "narx qancha bo'ladi?")
    check("savol LLM'ga bordi (MOCK javob keldi)", any("MOCK" in t for t in out2))
    check("awaiting AVTOMATIK bekor qilindi", 111 not in userbot._awaiting_bug_text)
    check("bug YOZILMADI (savol edi)", len(db.get_bug_reports()) == 0)

    print("=== 3) /debug -> /bekor bilan qo'lda bekor qilish ===")
    userbot._awaiting_bug_text.clear()
    await send(111, "/debug")
    check("awaiting holatga tushdi", 111 in userbot._awaiting_bug_text)
    out3 = await send(111, "/bekor")
    check("bekor tasdiqlandi", any("bekor" in t.lower() for t in out3))
    check("awaiting tozalandi", 111 not in userbot._awaiting_bug_text)
    check("bug yozilmadi", len(db.get_bug_reports()) == 0)

    print("=== 4) /debug -> haqiqiy bug matni (savol emas) -> yoziladi ===")
    userbot._awaiting_bug_text.clear()
    await send(111, "/debug")
    out4 = await send(111, "Planirovka rasmi kelmadi, faqat matn keldi")
    check("bug qayd etildi", any("Bug #" in t for t in out4))
    check("DB'da 1 ta bug bor", len(db.get_bug_reports()) == 1)

    print("=== 5) /debug ikkinchi marta (allaqachon awaiting bo'lganda) -> eslatma, /debug matni yozilmaydi ===")
    userbot._awaiting_bug_text.clear()
    await send(111, "/debug")
    out5 = await send(111, "/debug")
    check("qayta eslatma berildi (bug emas)", any("kutyapman" in t.lower() for t in out5))
    check("'/debug' matni bug sifatida YOZILMADI", len(db.get_bug_reports()) == 1)  # hali 1 (4-qismdagi)

    print("=== 6) _awaiting_plan_choice endi user_id bilan (5.6) ===")
    userbot._awaiting_plan_choice.clear()
    userbot._awaiting_plan_choice[999] = 1e15  # uzoq kelajak (hech qachon tugamaydi)
    check("user_id kalit sifatida ishlaydi", 999 in userbot._awaiting_plan_choice)

    print(f"\nNATIJA: {PASS}/{PASS+len(FAIL)}" + (f" | YIQILDI: {FAIL}" if FAIL else " — ✅"))
    sys.exit(1 if FAIL else 0)


asyncio.run(main())
