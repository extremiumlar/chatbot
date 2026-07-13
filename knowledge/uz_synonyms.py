"""O'zbekcha sinonim lug'ati — gibrid qidiruvning kalit-so'z qatlami uchun.

Mijozlar rus/o'zbek aralash so'zlaydi ("skidka", "adres", "dokument") — vektor model
buni har doim ushlolmaydi. Bu lug'at so'rov tokenlarini kengaytiradi: kalit so'z
bo'lakda sinonimi orqali topilsa ham moslik hisoblanadi.

Qo'shish oson: {"so'rov_so'zi": ["bo'lakda_uchraydigan", "variantlar"]}.
Hammasi kichik harfda, o'zbek apostrofi to'g'ri (') ko'rinishда yozilsin.
"""
from __future__ import annotations

SYNONYMS: dict[str, list[str]] = {
    # ruscha/kundalik -> KB'da ishlatiladigan atama
    "garantiya": ["kafolat"],
    "skidka": ["chegirma"],
    "dokument": ["hujjat"],
    "adres": ["manzil", "joylashgan"],
    "manzil": ["joylashgan", "joylashuv"],
    "avtoturargoh": ["parkovka"],
    "parkovka": ["avtoturargoh", "mashina"],
    "mashina": ["parkovka", "avtoturargoh"],
    "rassrochka": ["muddatli", "bo'lib to'lash"],
    "kvartira": ["xonadon", "uy"],
    "vznos": ["boshlang'ich to'lov"],
    "pervonachalniy": ["boshlang'ich"],
    "remont": ["ta'mir"],
    "plan": ["planirovka", "reja"],
    "chizma": ["planirovka", "reja"],
    "sxema": ["planirovka", "reja"],
    # qurilish materiali haqidagi savollar -> material bo'lagi atamalari
    "g'isht": ["monolit", "gazoblok", "beton", "qurilgan"],
    "beton": ["monolit"],
    "zilzila": ["zilzilaga", "chidamli"],
    "seysmik": ["zilzilaga", "chidamli"],
    # topshirish/muddat
    "bitadi": ["topshiriladi", "topshirish"],
    "tugaydi": ["topshiriladi", "topshirish"],
    "muddat": ["topshiriladi", "oy"],
    # pul/to'lov
    "pul": ["to'lov", "narx", "summa"],
    "narx": ["to'lov", "summa", "mln"],
    "arzon": ["chegirma"],
    "qimmat": ["narx", "chegirma"],
}
