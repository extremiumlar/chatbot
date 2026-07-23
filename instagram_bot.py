"""Instagram Direct xabarlariga avtomatik javob beruvchi (rasmiy Meta Graph API).

Telegram userbot.py bilan bir xil "miya"ni (knowledge/answer.py) ishlatadi, lekin
kanal qatlami butunlay boshqacha: Telethon o'rniga Meta webhook (qabul qilish —
backend/ig_bot/views.py) + Graph API "Send API" (yuborish). Bu modul ALOHIDA
JARAYON EMAS — Django webhook view'i to'g'ridan-to'g'ri shu moduldagi
`handle_webhook_payload()`ni chaqiradi (backend/core/settings.py repo ildizini
sys.path'ga qo'shgan).

.env da kerak: INSTAGRAM_APP_SECRET (imzo tekshiruvi), INSTAGRAM_PAGE_ACCESS_TOKEN
(xabar yuborish), INSTAGRAM_VERIFY_TOKEN (webhook GET tasdiqlash).

MUHIM CHEKLOV: holat (rate-limit, pauza, tarix keshi) shu modulning xotirasida
(module-level dict) saqlanadi. gunicorn bir nechta worker-JARAYON bilan ishlaydi —
har worker o'z nusxasini saqlaydi, ular orasida sinxronlashuv YO'Q. Hozirgi trafik
hajmida bu qabul qilinadigan chegara (deploy/README.md'da eslatilgan); kelajakda
ko'payib ketsa umumiy (Redis) holatga o'tish kerak bo'ladi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime

import config
from knowledge import answer, db
from uysot import backend

log = logging.getLogger("instagram_bot")

GRAPH_API_BASE = "https://graph.facebook.com"

# --- holat (userbot.py bilan bir xil naqsh) ---
_history: dict[int, list[dict]] = {}
_paused_until: dict[int, float] = {}
_pending_bot_texts: dict[int, deque[str]] = {}
_pending_bot_attachments: dict[int, int] = {}
_msg_times: dict[int, list[float]] = {}
_awaiting_plan_choice: dict[int, float] = {}
_awaiting_bug_text: dict[int, float] = {}
_profile_cache: dict[int, tuple[str | None, str | None]] = {}
_seen_mids: dict[str, float] = {}   # webhook takror yuborilishini oldini oladi

PLAN_CHOICE_WINDOW = 600.0   # sekund (10 daqiqa)
BUG_TEXT_WINDOW = 180.0      # sekund (3 daqiqa)
BUG_REPORT_FILE = config.STORAGE_DIR / "bug_reports.md"

MAX_TRACKED_USERS = 1000
MAX_IG_LEN = 1000            # Instagram Send API matn chegarasi (Telegram'nikidan qisqaroq)
RATE_MAX = 20
RATE_WINDOW = 60.0
HISTORY_TURNS = 8
MID_TTL = 3600.0             # bitta xabar mid'ini shuncha vaqt "ko'rilgan" deb saqlaymiz


# --- Webhook tasdiqlash / xavfsizlik ---

def verify_subscription(mode: str | None, token: str | None) -> bool:
    """Meta webhook sozlashda yuboradigan GET so'rovi (`hub.mode`/`hub.verify_token`)."""
    return (mode == "subscribe" and bool(config.INSTAGRAM_VERIFY_TOKEN)
            and token == config.INSTAGRAM_VERIFY_TOKEN)


def verify_signature(raw_body: bytes, header_value: str | None) -> bool:
    """`X-Hub-Signature-256` sarlavhasini App Secret bilan HMAC-SHA256 orqali tekshiradi."""
    if not header_value or not header_value.startswith("sha256="):
        return False
    if not config.INSTAGRAM_APP_SECRET:
        log.warning("INSTAGRAM_APP_SECRET .env da yo'q — webhook imzosi tekshirilmadi (RAD ETILDI).")
        return False
    expected = hmac.new(config.INSTAGRAM_APP_SECRET.encode("utf-8"), raw_body,
                        hashlib.sha256).hexdigest()
    got = header_value.split("=", 1)[1]
    return hmac.compare_digest(expected, got)


# --- Graph API ---

def _graph_url(path: str) -> str:
    return f"{GRAPH_API_BASE}/{config.INSTAGRAM_GRAPH_API_VERSION}/{path}"


def _graph_post(path: str, payload: dict) -> dict:
    url = _graph_url(path) + f"?access_token={config.INSTAGRAM_PAGE_ACCESS_TOKEN}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8") or "{}")


def _get_profile(uid: int) -> tuple[str | None, str | None]:
    """(name, username) — Instagram profilidan (keshlangan, xatoda (None, None))."""
    if uid in _profile_cache:
        return _profile_cache[uid]
    name = username = None
    try:
        url = (_graph_url(str(uid))
              + f"?fields=name,username&access_token={config.INSTAGRAM_PAGE_ACCESS_TOKEN}")
        with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
        name, username = data.get("name"), data.get("username")
    except Exception:  # noqa: BLE001
        log.debug("Instagram profili olinmadi (uid=%s)", uid, exc_info=True)
    _profile_cache[uid] = (name, username)
    return name, username


# --- Yuborish ---

def _mark_pending(recipient_id: int, text: str) -> None:
    dq = _pending_bot_texts.get(recipient_id)
    if dq is None:
        dq = deque(maxlen=10)
        _pending_bot_texts[recipient_id] = dq
    dq.append(text)


def _unmark_pending(recipient_id: int, text: str) -> None:
    dq = _pending_bot_texts.get(recipient_id)
    if dq and text in dq:
        dq.remove(text)


def _split_message(text: str, limit: int = MAX_IG_LEN) -> list[str]:
    """Uzun javobni Instagram chegarasiga sig'adigan bo'laklarga bo'ladi."""
    if not text.strip():
        return []
    if len(text) <= limit:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                parts.append(cur); cur = ""
            parts.append(line[:limit]); line = line[limit:]
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur); cur = line
        else:
            cur = line if not cur else f"{cur}\n{line}"
    if cur:
        parts.append(cur)
    return [p for p in parts if p.strip()]


def _send_text(recipient_id: int, text: str) -> None:
    text = (text or "").strip()
    if not text:
        log.warning("Foydalanuvchi %s: bo'sh javob — yuborilmadi.", recipient_id)
        return
    for part in _split_message(text):
        if not part.strip():
            continue
        _mark_pending(recipient_id, part)
        try:
            _graph_post("me/messages", {
                "recipient": {"id": str(recipient_id)},
                "message": {"text": part},
                "messaging_type": "RESPONSE",
            })
        except Exception:
            _unmark_pending(recipient_id, part)
            raise


def _send_image(recipient_id: int, image_url: str) -> None:
    """Rasmni URL orqali yuboradi — Instagram serveri o'zi yuklab oladi
    (2D/3D planirovka rasmlari Django /api/layouts/ dan ochiq HTTPS URL sifatida keladi)."""
    _graph_post("me/messages", {
        "recipient": {"id": str(recipient_id)},
        "message": {
            "attachment": {"type": "image", "payload": {"url": image_url, "is_reusable": True}},
        },
        "messaging_type": "RESPONSE",
    })
    _pending_bot_attachments[recipient_id] = _pending_bot_attachments.get(recipient_id, 0) + 1


def _consume_pending_attachment(recipient_id: int) -> bool:
    n = _pending_bot_attachments.get(recipient_id, 0)
    if n > 0:
        _pending_bot_attachments[recipient_id] = n - 1
        return True
    return False


# --- Planirovka so'rovini aniqlash (userbot.py bilan bir xil, kanaldan mustaqil) ---

_PLAN_WORDS = ("planirovka", "planirofka", "planirov", "planirok", "planlanirovka",
              "layout", "chizma",
              "планировк", "чизма", "план квартиры",
              "хонадон схема", "квартира схема", "уй схема", "планировка схема",
              "xonadon sxema", "kvartira sxema", "uy sxema", "planirovka sxema")
_PHOTO_WORDS = ("rasm", "surat", "foto", "photo", "fotka",
               "расм", "сурат", "фото")
_PLAN_WEAK = ("plan", "план", "reja", "режа")
_HOME_WORDS = ("uy", "uyni", "uyingiz", "xonadon", "kvartira", "kvartura",
              "уй", "хонадон", "квартир")
_PAYMENT_CONTEXT = ("tolov", "тулов", "тўлов", "оплат", "ипотека", "ipoteka",
                    "кредит", "kredit", "рассрочка", "rassrochka",
                    "муддатли", "muddatli")


def _wants_plan(text: str) -> bool:
    t = text.lower().replace("'", "").replace("`", "").replace("ʻ", "")
    if any(w in t for w in _PAYMENT_CONTEXT):
        return False
    if any(w in t for w in _PLAN_WORDS):
        return True
    if any(w in t for w in _PHOTO_WORDS + _PLAN_WEAK) and any(w in t for w in _HOME_WORDS):
        return True
    return False


def _wanted_rooms(text: str) -> int | None:
    t = text.lower()
    m = re.search(r"(?<![mм\d])(\d+)\s*[хx]?\s*[-\s]?\s*(?:xonal|хонал|комнат)", t)
    if not m:
        m = re.search(r"(?<![mм\d])(\d+)\s*(?:xona|хона)", t)
    if not m:
        return None
    rooms = int(m.group(1))
    return rooms if 1 <= rooms <= 9 else None


def _wanted_area(text: str) -> float | None:
    t = text.lower().replace(",", ".")
    m = re.search(r"(\d{2,3}(?:\.\d+)?)\s*(?:m2|m²|м2|м²|кв|kv)", t)
    if not m:
        m = re.fullmatch(r"\s*(\d{2,3}(?:\.\d+)?)\s*", t)
    if not m:
        return None
    val = float(m.group(1))
    return val if 20 <= val <= 200 else None


def _layout_line(g: dict) -> str:
    return (f"• {g['rooms']} xonali — {g['area']} m² "
           f"({', '.join(g['blocks'])}-bloklar)")


# --- Rate-limit / tarix ---

def _rate_ok(uid: int) -> bool:
    now = time.monotonic()
    times = [t for t in _msg_times.get(uid, []) if now - t < RATE_WINDOW]
    times.append(now)
    _msg_times[uid] = times
    return len(times) <= RATE_MAX


def _load_history(uid: int) -> list[dict]:
    h = _history.get(uid)
    if h is None:
        try:
            h = db.get_recent_messages(uid, limit=HISTORY_TURNS)
        except Exception:  # noqa: BLE001
            h = []
        _history[uid] = h
    return h


def _save_exchange(uid: int, user_text: str, bot_text: str) -> None:
    h = _load_history(uid)
    h.append({"role": "user", "content": user_text})
    h.append({"role": "assistant", "content": bot_text})
    _history[uid] = h[-HISTORY_TURNS:]
    try:
        db.add_message(uid, "user", user_text)
        db.add_message(uid, "assistant", bot_text)
    except Exception:  # noqa: BLE001
        log.warning("Suhbatni saqlashda xato", exc_info=True)


# --- /debug bug-hisobot oqimi ---

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


def _record_bug(uid: int, name: str | None, username: str | None, report: str) -> int:
    bug_id = db.add_bug_report(uid, name, username, report)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    uname = f" (@{username})" if username else ""
    entry = f"\n## Bug #{bug_id} — {stamp} — {name or 'Mijoz'}{uname} [id {uid}]\n\n{report.strip()}\n"
    try:
        new_file = not BUG_REPORT_FILE.exists()
        with open(BUG_REPORT_FILE, "a", encoding="utf-8") as f:
            if new_file:
                f.write("# Nurli diyor bot — test bug-hisobotlari\n")
            f.write(entry)
    except Exception:  # noqa: BLE001 - fayl yozilmasa ham DB'da bor
        log.warning("bug_reports.md ga yozishda xato", exc_info=True)
    log.info("BUG #%d qayd etildi (uid=%s): %.80s", bug_id, uid, report)
    return bug_id


def _handle_debug(uid: int, text: str) -> bool:
    """Qaytaradi: True — xabar shu yerda "iste'mol qilindi"; False — bu aslida
    bug matni emas ekan (savolga o'xshaydi), oddiy (LLM) yo'lga yuborilishi kerak."""
    stripped = re.sub(r"^/debug\b", "", text, flags=re.IGNORECASE).strip()
    awaiting = uid in _awaiting_bug_text

    if text.strip().lower() in _CANCEL_WORDS:
        was_awaiting = _awaiting_bug_text.pop(uid, None) is not None
        if was_awaiting:
            _send_text(uid, "Bekor qilindi. Yana bug xabar qilmoqchi bo'lsangiz /debug deb yozing.")
        return True

    if awaiting and not text.strip().lower().startswith("/debug") and _looks_like_question(text):
        _awaiting_bug_text.pop(uid, None)
        log.info("Foydalanuvchi %s: /debug kutishi bekor qilindi (savolga o'xshaydi): %.60s",
                 uid, text)
        return False

    if not stripped and not awaiting:
        _awaiting_bug_text[uid] = time.monotonic() + BUG_TEXT_WINDOW
        _send_text(uid, "🐞 Bug tavsifini yozing (bitta xabarda): nima noto'g'ri ishladi "
                        "va sizningcha qanday tuzatish kerak? (Bekor qilish: /bekor)")
        return True

    if not stripped and awaiting:
        _send_text(uid, "Bug tavsifini kutyapman — yozing (yoki /bekor).")
        return True

    report = stripped or text.strip()
    _awaiting_bug_text.pop(uid, None)
    name, username = _get_profile(uid)
    bug_id = _record_bug(uid, name, username, report)
    _send_text(uid, f"✅ Bug #{bug_id} qayd etildi. Rahmat! Davom etavering — "
                    "yangi bug topsangiz yana /debug deb yozing.")
    return True


# --- Planirovka so'rovi ---

def _handle_plan_request(uid: int, text: str) -> None:
    """Planirovka so'rovi: SOTUVDA QOLGAN turning rasmini yuboradi (userbot.py bilan
    bir xil qoidalar — sotilgan tur yuborilmaydi, bir nechta variant mos kelsa savol)."""
    try:
        avail = backend.layouts_with_image()
        all_img = backend.layouts_with_image(only_available=False)
    except Exception:  # noqa: BLE001
        log.exception("Backenddan planirovka turlarini olishda xato")
        avail, all_img = [], []

    if not all_img:
        reply = ("Kechirasiz, planirovkalar hozir tayyor emas 🙏 Telefon raqamingizni "
                 "qoldiring — menejerimiz planirovkani yuboradi.")
        _send_text(uid, reply)
        _save_exchange(uid, text, reply)
        return

    if not avail:
        reply = ("Hozir barcha xonadonlar band. Telefon raqamingizni qoldiring — "
                 "yangi xonadon chiqishi bilan menejerimiz sizga birinchi bo'lib "
                 "xabar beradi 😊")
        _send_text(uid, reply)
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

    if rooms is not None and not chosen:
        sold_out = [l for l in all_img if int(l["rooms"]) == rooms]
        if sold_out:
            reply = (f"Hozircha {rooms} xonali xonadonlarimiz sotilib bo'lgan. "
                     f"Bizda {avail_types} xonali variantlar bor — qaysi birining "
                     "planirovkasini yuboray?")
        else:
            reply = (f"Hozircha {rooms} xonali planirovka mavjud emas. Bizda "
                     f"{avail_types} xonali planirovkalar bor — qaysi birini yuboray?")
        _send_text(uid, reply)
        _save_exchange(uid, text, reply)
        _awaiting_plan_choice[uid] = time.monotonic() + PLAN_CHOICE_WINDOW
        return

    if rooms is None and len({l["rooms"] for l in chosen}) > 1:
        lines = ["Bizda quyidagi xonadon turlari (planirovkalar) bor 👇"]
        lines += [_layout_line(l) for l in chosen]
        lines.append('\nQaysi birining planirovkasini yuboray? Masalan: "3 xonali planirovka".')
        reply = "\n".join(lines)
        _send_text(uid, reply)
        _save_exchange(uid, text, reply)
        _awaiting_plan_choice[uid] = time.monotonic() + PLAN_CHOICE_WINDOW
        return

    if len(chosen) > 1:
        r = chosen[0]["rooms"]
        variants_txt = " va ".join(f"{float(l['area']):g} m²" for l in chosen)
        reply = (f"{r} xonali xonadonlarimiz {variants_txt} variantlarida bor — "
                 f"qaysi biri qiziqtiradi? (masalan: \"{float(chosen[0]['area']):g} m2\")")
        _send_text(uid, reply)
        _save_exchange(uid, text, reply)
        _awaiting_plan_choice[uid] = time.monotonic() + PLAN_CHOICE_WINDOW
        return

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
    image_urls = [u for u in (l.get("image_url"), l.get("image_3d_url")) if u]
    if image_urls:
        try:
            _send_text(uid, caption)
            for url in image_urls:
                _send_image(uid, url)
            _save_exchange(uid, text, "[planirovka rasmi yuborildi]")
            return
        except Exception:  # noqa: BLE001
            log.exception("Planirovka rasmini yuborishda xato")
    reply = ("Kechirasiz, planirovkani yuborib bo'lmadi 🙏 Telefon raqamingizni "
            "qoldiring — menejerimiz yuboradi.")
    _send_text(uid, reply)
    _save_exchange(uid, text, reply)


# --- Xotira tozalash ---

def _prune() -> None:
    now = time.monotonic()
    for cid in [c for c, u in _paused_until.items() if u < now]:
        _paused_until.pop(cid, None)
    for cid in [c for c, t in _msg_times.items() if not t or now - t[-1] > RATE_WINDOW]:
        _msg_times.pop(cid, None)
    for uid in [u for u, t in _awaiting_plan_choice.items() if t < now]:
        _awaiting_plan_choice.pop(uid, None)
    for uid in [u for u, t in _awaiting_bug_text.items() if t < now]:
        _awaiting_bug_text.pop(uid, None)
    for cid in [c for c, dq in _pending_bot_texts.items() if not dq]:
        _pending_bot_texts.pop(cid, None)
    for cid in [c for c, n in _pending_bot_attachments.items() if n <= 0]:
        _pending_bot_attachments.pop(cid, None)
    for mid in [m for m, t in _seen_mids.items() if now - t > MID_TTL]:
        _seen_mids.pop(mid, None)
    for d in (_history, _pending_bot_texts, _profile_cache):
        while len(d) > MAX_TRACKED_USERS:
            d.pop(next(iter(d)))


# --- Asosiy oqim (bitta yangi xabar) ---

def _handle_incoming(uid: int, text: str) -> None:
    awaiting_bug = _awaiting_bug_text.get(uid, 0.0) > time.monotonic()
    if text.lower().startswith("/debug") or awaiting_bug:
        handled = _handle_debug(uid, text)
        if handled:
            _prune()
            return

    until = _paused_until.get(uid, 0.0)
    if until and time.monotonic() < until:
        log.info("Foydalanuvchi %s: menejer rejimida, javob berilmadi.", uid)
        return

    if not _rate_ok(uid):
        log.warning("Foydalanuvchi %s: juda ko'p xabar (rate-limit) — o'tkazib yuborildi.", uid)
        return

    name, username = _get_profile(uid)
    db.upsert_lead(uid, name=name, username=username)
    log.info("Mijoz %s: %s", uid, text[:80])

    awaiting = _awaiting_plan_choice.get(uid, 0.0) > time.monotonic()
    if _wants_plan(text) or (awaiting and (_wanted_rooms(text) is not None
                                           or _wanted_area(text) is not None)):
        _awaiting_plan_choice.pop(uid, None)
        _handle_plan_request(uid, text)
        _prune()
        return

    history = _load_history(uid)
    try:
        reply = answer.answer(text, list(history))
    except Exception:  # noqa: BLE001
        log.exception("Javob xatosi")
        fallback = ("Kechirasiz, hozir kichik texnik nosozlik bo'ldi 🙏 Biroz o'tib "
                   "qayta yozing yoki telefon raqamingizni qoldiring — "
                   "mutaxassisimiz siz bilan bog'lanadi.")
        try:
            _send_text(uid, fallback)
            _save_exchange(uid, text, "[XATOLIK fallback] " + fallback)
        except Exception:  # noqa: BLE001
            log.exception("Fallback yuborishda ham xato")
        _prune()
        return

    history.append({"role": "user", "content": text})
    history.append({"role": "assistant", "content": reply})
    _history[uid] = history[-HISTORY_TURNS:]
    try:
        db.add_message(uid, "user", text)
        db.add_message(uid, "assistant", reply)
    except Exception:  # noqa: BLE001
        log.warning("Suhbat tarixini saqlashda xato", exc_info=True)

    _send_text(uid, reply)
    _prune()


def _handle_echo(recipient_id: int, msg: dict) -> None:
    """`is_echo` xabari: bizning Send API orqali yuborganimiz aksimi, yoki menejer
    Instagram ilovasi/inbox orqali qo'lda yozganmi — shuni ajratadi."""
    text = (msg.get("text") or "").strip()
    if text:
        dq = _pending_bot_texts.get(recipient_id)
        if dq and text in dq:
            dq.remove(text)
            return
    elif msg.get("attachments") and _consume_pending_attachment(recipient_id):
        return
    pause_sec = config.HUMAN_TAKEOVER_MINUTES * 60
    _paused_until[recipient_id] = time.monotonic() + pause_sec
    log.info("Foydalanuvchi %s: menejer qo'lda yozdi -> %d daqiqa avtomatik javob to'xtatildi.",
             recipient_id, config.HUMAN_TAKEOVER_MINUTES)


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _seen_mid(mid: str) -> bool:
    """True — bu mid avval ko'rilgan (Meta webhook'ni qayta yuborgan)."""
    now = time.monotonic()
    if mid in _seen_mids:
        return True
    _seen_mids[mid] = now
    return False


def _handle_messaging_event(me: dict) -> None:
    msg = me.get("message")
    if msg is None:
        return  # delivery/read/postback hodisalari — hozircha e'tiborsiz
    mid = msg.get("mid")
    if mid and _seen_mid(mid):
        log.debug("Takroriy webhook (mid=%s) — o'tkazib yuborildi.", mid)
        return

    if msg.get("is_echo"):
        recipient_id = _to_int((me.get("recipient") or {}).get("id"))
        if recipient_id is not None:
            _handle_echo(recipient_id, msg)
        return

    sender_id = _to_int((me.get("sender") or {}).get("id"))
    text = (msg.get("text") or "").strip()
    if sender_id is None or not text:
        return
    _handle_incoming(sender_id, text)


def handle_webhook_payload(payload: dict) -> None:
    """Meta'dan kelgan bitta webhook POST tanasi (allaqachon JSON-parse qilingan)."""
    if payload.get("object") != "instagram":
        return
    for entry in payload.get("entry", []):
        expected = config.INSTAGRAM_BUSINESS_ACCOUNT_ID
        if expected and entry.get("id") not in (None, expected):
            log.warning("Instagram webhook: kutilmagan entry.id=%s (kutilgan=%s)",
                       entry.get("id"), expected)
            continue
        for me in entry.get("messaging", []) or []:
            try:
                _handle_messaging_event(me)
            except Exception:  # noqa: BLE001
                log.exception("Instagram webhook hodisasini qayta ishlashda xato: %.200s", me)
