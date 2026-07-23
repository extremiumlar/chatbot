"""Instagram webhook (instagram_bot.py) testlari: imzo tekshiruvi, GET tasdiqlash,
mid-dedup (Meta webhook'ni qayta yuborsa), is_echo orqali inson-qo'lga-olish
(human takeover) pauzasi.

Ishlatilishi:  .venv\\Scripts\\python.exe tests\\test_instagram_webhook.py
"""
from __future__ import annotations

import hashlib
import hmac
import os
import pathlib
import sys
import tempfile

sys.path.insert(0, os.path.abspath("."))

import config

_tmp = pathlib.Path(tempfile.mkdtemp())
config.SQLITE_PATH = _tmp / "t.db"
config.STORAGE_DIR = _tmp
config.INSTAGRAM_APP_SECRET = "test-secret"
config.INSTAGRAM_VERIFY_TOKEN = "test-verify"
config.INSTAGRAM_PAGE_ACCESS_TOKEN = "test-token"
config.INSTAGRAM_BUSINESS_ACCOUNT_ID = ""   # bo'sh — entry.id tekshiruvi o'chiq

import instagram_bot as ig
from knowledge import db

ig.BUG_REPORT_FILE = _tmp / "bug_reports.md"
db.init_db()

# Tarmoqqa chiqmasin: Graph API chaqiruvlarini xotiradagi ro'yxatga yozamiz.
sent: list[tuple[str, dict]] = []


def _fake_graph_post(path, payload):
    sent.append((path, payload))
    return {}


ig._graph_post = _fake_graph_post
ig._get_profile = lambda uid: (None, None)   # profil so'rovi ham tarmoqqa chiqmasin

from knowledge import answer as ans


def fake_answer(q, history=None):
    return "MOCK javob"


ans.answer = fake_answer
ig.answer.answer = fake_answer


def _incoming_payload(customer_id, text, mid):
    return {
        "object": "instagram",
        "entry": [{"id": "999000", "messaging": [{
            "sender": {"id": str(customer_id)},
            "recipient": {"id": "999000"},
            "message": {"mid": mid, "text": text},
        }]}],
    }


def _echo_payload(customer_id, text, mid):
    """Sahifa/menejer nomidan yuborilgan xabar (yoki bizning aksimiz) —
    Meta'da sender=sahifa, recipient=mijoz, is_echo=true."""
    return {
        "object": "instagram",
        "entry": [{"id": "999000", "messaging": [{
            "sender": {"id": "999000"},
            "recipient": {"id": str(customer_id)},
            "message": {"mid": mid, "text": text, "is_echo": True},
        }]}],
    }


PASS, FAIL = 0, []


def check(n, c):
    global PASS
    PASS += c
    if not c:
        FAIL.append(n)
    print(f"  {'✓' if c else '✗ FAIL'}  {n}")


def main():
    print("=== 1) Imzo tekshiruvi (X-Hub-Signature-256) ===")
    body = b'{"a":1}'
    good_sig = "sha256=" + hmac.new(b"test-secret", body, hashlib.sha256).hexdigest()
    check("to'g'ri imzo qabul qilinadi", ig.verify_signature(body, good_sig))
    check("noto'g'ri imzo rad etiladi", not ig.verify_signature(body, "sha256=deadbeef"))
    check("sarlavha yo'q bo'lsa rad etiladi", not ig.verify_signature(body, None))

    print("=== 2) GET tasdiqlash (hub.verify_token) ===")
    check("to'g'ri token qabul qilinadi", ig.verify_subscription("subscribe", "test-verify"))
    check("noto'g'ri token rad etiladi", not ig.verify_subscription("subscribe", "wrong"))
    check("mode != subscribe rad etiladi", not ig.verify_subscription("unsubscribe", "test-verify"))

    print("=== 3) Oddiy kiruvchi xabar -> javob yuboriladi va lead yoziladi ===")
    sent.clear()
    ig.handle_webhook_payload(_incoming_payload(111, "salom", "mid-1"))
    check("javob yuborildi", len(sent) == 1)
    check("MOCK javob matni", bool(sent) and "MOCK" in sent[0][1]["message"]["text"])
    check("lead bazaga yozildi", db.get_lead(111) is not None)

    print("=== 4) Takroriy webhook (bir xil mid) -> qayta ishlanmaydi ===")
    sent.clear()
    ig.handle_webhook_payload(_incoming_payload(111, "salom", "mid-1"))
    check("qayta javob yuborilmadi (dedup)", len(sent) == 0)

    print("=== 5) is_echo (bizning xabarimiz aksi) -> pauza QO'YILMAYDI ===")
    ig._paused_until.clear()
    sent.clear()
    ig.handle_webhook_payload(_incoming_payload(222, "yangi savol", "mid-2"))
    bot_reply_text = sent[0][1]["message"]["text"]
    ig.handle_webhook_payload(_echo_payload(222, bot_reply_text, "mid-2-echo"))
    check("bot o'z aksidan pauzaga tushmadi", 222 not in ig._paused_until)

    print("=== 6) is_echo (menejer qo'lda yozgan) -> pauza QO'YILADI ===")
    ig._paused_until.clear()
    ig.handle_webhook_payload(_echo_payload(222, "Salom, men shu yerdaman", "mid-3"))
    check("menejer xabari pauzani ishga tushirdi", 222 in ig._paused_until)

    print("=== 7) Pauza paytida kiruvchi xabarga avtomatik javob berilmaydi ===")
    sent.clear()
    ig.handle_webhook_payload(_incoming_payload(222, "yana savol", "mid-4"))
    check("pauza paytida javob yuborilmadi", len(sent) == 0)

    print(f"\nNATIJA: {PASS}/{PASS + len(FAIL)}" + (f" | YIQILDI: {FAIL}" if FAIL else " — ✅"))
    sys.exit(1 if FAIL else 0)


main()
