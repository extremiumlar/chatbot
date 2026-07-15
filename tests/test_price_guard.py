"""Narx-filtr birlik testlari (API'siz, tez).

Ishlatilishi:  .venv\\Scripts\\python.exe tests\\test_price_guard.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath("."))

import config  # noqa: E402
from knowledge import answer, price_guard  # noqa: E402
from knowledge.price_guard import contains_forbidden_sum as f  # noqa: E402

PASS = 0
FAIL: list[str] = []


def check(name: str, cond: bool) -> None:
    global PASS
    if cond:
        PASS += 1
    else:
        FAIL.append(name)
    print(f"  {'✓' if cond else '✗ FAIL'}  {name}")


print("=== 1) TOPISHI KERAK (taqiqlangan summalar) ===")
check("557 380 000 so'm", f("Jami 557 380 000 so'm bo'ladi") != [])
check("557,380,000", f("Total: 557,380,000") != [])
check("557380000 (uzluksiz)", f("62*8990000=557380000") != [])
check("40 921 800 so'm", f("boshlang'ich 40 921 800 so'm") != [])
check("40.921.800 (nuqtali)", f("40.921.800 so'm kerak") != [])
check("205 mln", f("eng arzoni 205 mln") != [])
check("550 millionga yaqin", f("550 millionga yaqin pul kerak") != [])
check("915 000 000 сум (kirill)", f("итого 915 000 000 сум") != [])
check("120 млн (kirill)", f("около 120 млн") != [])
check("1.2 mlrd", f("1.2 mlrd so'm") != [])
check("NBSP ajratkich", f("557 380 000 so'm") != [])

print("=== 2) O'TKAZISHI KERAK (ruxsat etilgan) ===")
check("8 990 000 so'm/m² (tarif)", f("1 m² narxi 8 990 000 so'm") == [])
check("8 490 000 (tarif)", f("6-9-qavatlar: 8 490 000") == [])
check("8490000 uzluksiz (tarif)", f("m2 8490000 so'mdan") == [])
check("8.49 mln (tarif)", f("m² narxi 8.49 mln so'm") == [])
check("8,99 mln (tarif, vergul)", f("8,99 mln so'm/m²") == [])
check("+998901079792 (telefon)", f("Tel: +998901079792") == [])
check("998 bilan uzluksiz telefon", f("raqamimiz 998901079792") == [])
check("2027-yil (sana)", f("2027-yil 4-chorakda topshiriladi") == [])
check("24.1 m² (maydon)", f("24.1 m² dan 83.9 m² gacha") == [])
check("62-62.81 m²", f("62 m² va 62.81 m² xonadonlar bor") == [])
check("36 oy (muddat)", f("36 oygacha muddatli to'lov") == [])
check("24 oydan 60 oygacha", f("24 oydan 60 oygacha") == [])
check("9 ball zilzila", f("9 ballgacha zilzilaga chidamli") == [])
check("46% yashil zona", f("hududning 46% i yashil") == [])
check("8 ta xonadon, 5-blok", f("5-blokda 8 ta xonadon qoldi") == [])
check("bo'sh matn", f("") == [])

print("=== 3) MULTI-TURN: mijoz summasini takrorlash ham ushlanadi ===")
check("«siz aytgan 557 380 000» ushlanadi",
      f("Siz aytgan 557 380 000 so'm taxminan to'g'ri") != [])

print("=== 4) RETRY MANTIQ (fake provayder bilan) ===")
calls = {"n": 0}
_orig_provider = config.LLM_PROVIDER
_orig_gemini = answer._answer_gemini
config.LLM_PROVIDER = "gemini"

# (a) 1-urinish leak, 2-urinish toza -> yakuniy javob toza, 2 chaqiruv
def fake_leak_then_clean(question, history):
    calls["n"] += 1
    if calls["n"] == 1:
        return "Jami 557 380 000 so'm bo'ladi."
    return "m² narxi 8 990 000 so'm, ofisga tashrif buyuring."
answer._answer_gemini = fake_leak_then_clean
r = answer.answer("umumiy narx?")
check("retry: 2-urinish toza javob qaytdi", "8 990 000" in r and "557" not in r)
check("retry: aynan 2 chaqiruv bo'ldi", calls["n"] == 2)
check("retry: eslatma ilova qilindi", True)  # quyida (c) da tekshiriladi

# (b) ikkala urinish ham leak -> SAFE_PRICE_REPLY, faqat 2 chaqiruv (sikl yo'q)
calls["n"] = 0
def fake_always_leak(question, history):
    calls["n"] += 1
    return "Umumiy summa 915 000 000 so'm."
answer._answer_gemini = fake_always_leak
r = answer.answer("narxi?")
check("ikkala leak -> xavfsiz matn", r == price_guard.SAFE_PRICE_REPLY)
check("ikkala leak -> faqat 2 chaqiruv (cheksiz sikl yo'q)", calls["n"] == 2)

# (c) retry'da savolga TIZIM ESLATMASI qo'shilganini tekshirish
seen_questions: list[str] = []
calls["n"] = 0
def fake_capture(question, history):
    calls["n"] += 1
    seen_questions.append(question)
    return "557 380 000 so'm" if calls["n"] == 1 else "toza javob"
answer._answer_gemini = fake_capture
answer.answer("qancha?")
check("retry savolida TIZIM ESLATMASI bor",
      len(seen_questions) == 2 and "TIZIM ESLATMASI" in seen_questions[1]
      and "TIZIM ESLATMASI" not in seen_questions[0])

# (d) toza javob -> 1 chaqiruv, filtr aralashmaydi
calls["n"] = 0
def fake_clean(question, history):
    calls["n"] += 1
    return "3 xonali xonadonlar 3- va 5-bloklarda bor, 59.3 m²."
answer._answer_gemini = fake_clean
r = answer.answer("3 xonali bormi?")
check("toza javob o'zgarishsiz o'tdi", "59.3" in r and calls["n"] == 1)

# (e) multi-turn: history'da mijoz summasi bor, model uni takrorlasa ushlanadi
calls["n"] = 0
hist = [{"role": "user", "content": "557 380 000 to'g'rimi?"},
        {"role": "assistant", "content": "Ofisda hisoblanadi."}]
def fake_echo_history(question, history):
    calls["n"] += 1
    if calls["n"] == 1:
        return "Ha, siz aytgan 557 380 000 so'm taxminan to'g'ri."
    return "Yakuniy hisob ofisda qilinadi, m² tarifi 8 490 000 so'm."
answer._answer_gemini = fake_echo_history
r = answer.answer("o'sha narxga bo'ladimi?", history=hist)
check("multi-turn: takrorlangan summa ushlandi, toza javob qaytdi",
      "557" not in r and "8 490 000" in r)

# tiklash
answer._answer_gemini = _orig_gemini
config.LLM_PROVIDER = _orig_provider

print()
total = PASS + len(FAIL)
print(f"NATIJA: {PASS}/{total} o'tdi" + (f" | YIQILDI: {FAIL}" if FAIL else " — hammasi toza ✅"))
sys.exit(1 if FAIL else 0)
