"""1-BOSQICH testlari: sotilgan-filtr, albom, 'схема' bugi, telefon-PII.

Ishlatilishi:  .venv\\Scripts\\python.exe tests\\test_stage1.py   (yoki pytest)
Tarmoq/LLM ishlatilmaydi; DB — vaqtinchalik.
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import pathlib

sys.path.insert(0, os.path.abspath("."))

import config  # noqa: E402

_tmp = pathlib.Path(tempfile.mkdtemp())
config.SQLITE_PATH = _tmp / "t.db"

import userbot  # noqa: E402
from knowledge import db, pii  # noqa: E402
from uysot import backend  # noqa: E402

db.init_db()

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
    print(f"  {'✓' if cond else '✗ FAIL'}  {name}")


# --------------------------------------------------------------- 1.3 схема
def test_wants_plan() -> None:
    print("=== 1.3: _wants_plan (схема/to'lov ajratish) ===")
    false_cases = [
        "to'lov схемаси қандай", "ipoteka схемаси", "тўлов схемаси",
        "kredit sxemasi", "рассрочка схемаси", "muddatli to'lov sxemasi",
        "tolov rejasi", "оплата схемаси", "kredit olsam bo'ladimi",
        "narx qancha",
    ]
    true_cases = [
        "планировка юборинг", "хонадон схемаси", "уй схемаси",
        "planirovka yuboring", "чизма", "uy rasmini yuboring",
        "3 хонали планировка", "xonadon sxemasi", "kvartira sxemasi",
        "planirovka sxemasi",
    ]
    for t in false_cases:
        check(f"False: {t!r}", userbot._wants_plan(t) is False)
    for t in true_cases:
        check(f"True:  {t!r}", userbot._wants_plan(t) is True)


# ------------------------------------------------- 1.1 layouts_with_image
FAKE_LAYOUTS = [
    {"id": 1, "rooms": 1, "area": 30.0, "blocks": ["3"], "available_count": 0,
     "total_count": 10, "image_url": "http://x/1.jpg", "image_3d_url": None},
    {"id": 2, "rooms": 2, "area": 62.0, "blocks": ["4"], "available_count": 5,
     "total_count": 20, "image_url": "http://x/2.jpg", "image_3d_url": "http://x/2b.jpg"},
    {"id": 3, "rooms": 2, "area": 62.8, "blocks": ["4"], "available_count": 2,
     "total_count": 6, "image_url": "http://x/3.jpg", "image_3d_url": None},
    {"id": 4, "rooms": 3, "area": 74.6, "blocks": ["1"], "available_count": 0,
     "total_count": 2, "image_url": "http://x/4.jpg", "image_3d_url": None},
    {"id": 5, "rooms": 4, "area": 90.0, "blocks": ["2"], "available_count": 1,
     "total_count": 3, "image_url": None, "image_3d_url": None},  # rasm yo'q
]


def test_layouts_filter() -> None:
    print("=== 1.1: layouts_with_image only_available filtri ===")
    orig = backend.get_layouts
    backend.get_layouts = lambda force=False: FAKE_LAYOUTS
    try:
        av = backend.layouts_with_image()
        check("default: faqat sotuvdagilar (2 ta: id2,id3)",
              sorted(l["id"] for l in av) == [2, 3])
        al = backend.layouts_with_image(only_available=False)
        check("only_available=False: rasmlilar hammasi (4 ta)",
              sorted(l["id"] for l in al) == [1, 2, 3, 4])
        check("rooms=3 sotuvda yo'q -> bo'sh", backend.layouts_with_image(rooms=3) == [])
        check("rasmsiz tur (id5) hech qachon kirmaydi",
              5 not in [l["id"] for l in al])
    finally:
        backend.get_layouts = orig


# ------------------------------------------- 1.1/1.2 plan handler oqimlari
class FakeClient:
    def __init__(self, sink):
        self.sink = sink

    def action(self, cid, kind):
        class A:
            async def __aenter__(s): return s
            async def __aexit__(s, *a): return False
        return A()

    async def send_file(self, cid, files, caption=None, force_document=False):
        n = len(files) if isinstance(files, list) else 1
        self.sink.append(("ALBUM", n, caption if isinstance(caption, str)
                          else (caption or [""])[0]))
        class M: id = 1
        return M()


class FakeEvent:
    def __init__(self, text, cid, sink):
        self.raw_text = text
        self.chat_id = cid
        self.is_private = True
        self.client = FakeClient(sink)

    async def reply(self, t):
        self.client.sink.append(("TEXT", t))
        class M: id = 2
        return M()


def run_plan(text, cid, layouts):
    sink: list = []
    orig_get, orig_fetch = backend.get_layouts, backend.fetch_image
    backend.get_layouts = lambda force=False: layouts
    backend.fetch_image = lambda url: b"IMGBYTES"
    userbot._pending_bot_texts.pop(cid, None)
    try:
        asyncio.run(userbot._handle_plan_request(FakeEvent(text, cid, sink), cid, cid, text))
    finally:
        backend.get_layouts, backend.fetch_image = orig_get, orig_fetch
    return sink


def test_plan_flow() -> None:
    print("=== 1.1/1.2: plan handler (sotilgan/albom/aniqlashtirish) ===")
    # (a) sotilgan tur so'raldi -> rasm YO'Q, mavjudlar ro'yxati
    s = run_plan("3 xonali planirovka", 901, FAKE_LAYOUTS)
    texts = [x[2] if x[0] == "ALBUM" else x[1] for x in s]
    check("(a) sotilgan 3-xonali: rasm yuborilmadi",
          not any(x[0] == "ALBUM" for x in s))
    check("(a) 'sotilib bo'lgan' + mavjud '2' taklifi",
          any("sotilib bo'lgan" in t and "2 xonali" in t for t in texts))

    # (b) bitta tur (62.8) -> 1 ta albom (bitta rasm)
    s = run_plan("2 xonali 62.8 m2 planirovka", 902, FAKE_LAYOUTS)
    albums = [x for x in s if x[0] == "ALBUM"]
    check("(b) bitta ALBOM chaqiruvi", len(albums) == 1)
    check("(b) 'Yana savol' caption ichida (alohida xabar YO'Q)",
          len(s) == 1 and "Yana savol" in albums[0][2])

    # (c) hammasi sotilgan -> telefon so'rash
    all_sold = [dict(l, available_count=0) for l in FAKE_LAYOUTS]
    s = run_plan("planirovka", 903, all_sold)
    check("(c) hammasi sotilgan: telefon so'raldi",
          any(x[0] == "TEXT" and "barcha xonadonlar band" in x[1] for x in s))

    # (d) 2 xonali: 2 maydon varianti -> rasm 0, aniqlashtirish 1
    s = run_plan("2 xonali planirovka", 904, FAKE_LAYOUTS)
    check("(d) rasm yo'q, aniqlashtiruvchi savol bor",
          not any(x[0] == "ALBUM" for x in s)
          and any("62" in x[1] and "62.8" in x[1] for x in s if x[0] == "TEXT"))

    # (e) 2D+3D bitta turda -> BITTA albom, ichida 2 rasm
    only62 = [FAKE_LAYOUTS[1]]  # id2: 2D+3D
    s = run_plan("2 xonali planirovka", 905, only62)
    albums = [x for x in s if x[0] == "ALBUM"]
    check("(e) 2D+3D -> 1 albom, 2 rasm", len(albums) == 1 and albums[0][1] == 2)


def test_outgoing_album() -> None:
    print("=== 1.2: _handle_outgoing albom bo'laklari pauza qo'ymaydi ===")
    from types import SimpleNamespace
    from datetime import datetime, timezone

    async def go():
        cid = 906
        userbot._paused_until.clear()
        userbot._pending_bot_texts.pop(cid, None)
        userbot._mark_pending(cid, "albom caption matni")
        ev = SimpleNamespace(is_private=True, chat_id=cid, raw_text="",
                             message=SimpleNamespace(date=datetime.now(timezone.utc)))
        await userbot._handle_outgoing(ev)          # matnsiz albom bo'lagi
        check("matnsiz chiquvchi (dq bor) -> pauza YO'Q", cid not in userbot._paused_until)
        ev2 = SimpleNamespace(is_private=True, chat_id=cid, raw_text="albom caption matni",
                              message=SimpleNamespace(date=datetime.now(timezone.utc)))
        await userbot._handle_outgoing(ev2)         # caption bo'lagi
        check("caption bo'lagi -> pauza YO'Q, dq bo'shadi",
              cid not in userbot._paused_until
              and not userbot._pending_bot_texts.get(cid))
        ev3 = SimpleNamespace(is_private=True, chat_id=cid, raw_text="menejer yozdi",
                              message=SimpleNamespace(date=datetime.now(timezone.utc)))
        await userbot._handle_outgoing(ev3)
        check("menejer matni -> pauza BOR", cid in userbot._paused_until)
        userbot._paused_until.clear()

    asyncio.run(go())


# --------------------------------------------------------------- 1.4 PII
def test_pii() -> None:
    print("=== 1.4: telefon-PII filtri ===")
    check("+998993870779 topiladi", pii.contains_phone("tel: +998993870779"))
    check("'+99897 444 00 8' topiladi", pii.contains_phone("+99897 444 00 8"))
    check("97 444 00 88 (guruhlangan) topiladi", pii.contains_phone("97 444 00 88"))
    check("oddiy matn topilmaydi", not pii.contains_phone("narx 8 990 000 so'm"))
    check("maydon/sana topilmaydi", not pii.contains_phone("62 m2, 2027-yil"))

    # answer: bazadagi telefonli fakt promptga chiqmasin (2.2 dan keyin faktlar
    # relevantlik bo'yicha filtrlanadi — shuning uchun so'rovni fakt matniga
    # MOS qilib beramiz: relevantlik filtridan o'tib, PII filtriga yetib borsin)
    from knowledge import answer
    db.add_fact(None, "aloqa", "Telefon raqami qanday?",
               "+998901234567 raqamiga qo'ng'iroq qiling")
    db.add_fact(None, "umumiy", "Kafolat necha yil?", "1 yil kafolat beriladi")

    blk = answer._rag_context_block("telefon raqami qanday, qo'ng'iroq qilsam bo'ladimi")
    check("relevant so'rovda ham telefonli fakt promptdan chiqarildi",
          "+99890" not in blk and "998901234567" not in blk)

    blk2 = answer._rag_context_block("kafolat necha yil beriladi")
    check("mos so'rovda toza (kafolat) fakt promptga kiradi", "kafolat" in blk2.lower())

    with db.connect() as c:
        c.execute("DELETE FROM facts")


if __name__ == "__main__":
    test_wants_plan()
    test_layouts_filter()
    test_plan_flow()
    test_outgoing_album()
    test_pii()
    total = PASS + len(FAIL)
    print(f"\nNATIJA: {PASS}/{total}" + (f" | YIQILDI: {FAIL}" if FAIL else " — ✅"))
    sys.exit(1 if FAIL else 0)
