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
    "beriladi": ["topshiriladi", "topshirish"],
    "muddat": ["topshiriladi", "oy"],
    # pul/to'lov
    "pul": ["to'lov", "narx", "summa"],
    "narx": ["to'lov", "summa", "mln"],
    "arzon": ["chegirma"],
    "qimmat": ["narx", "chegirma"],
    # sheva / og'zaki nutq (script_eval'da yiqilgan so'zlar)
    "bitarkan": ["topshiriladi", "topshirish"],
    "bitadimi": ["topshiriladi", "topshirish"],
    "bitib": ["topshiriladi", "topshirish"],
    "kere": ["kerak"],
    "qog'oz": ["hujjat", "pasport", "kadastr"],
    # "jadval" qo'shildi: to'lov-jadvali bo'limini ("oylik jadval") to'lov
    # miqdori haqidagi boshqa bo'limlardan ("boshlang'ich to'lov") ajratish uchun
    "to'liymiz": ["to'lov", "to'lanadi", "jadval"],
    "to'liman": ["to'lov"],
    "to'lash": ["to'lov", "to'lanadi", "jadval"],
    # DIQQAT: "qancha" ATAYIN yo'q — u "chegirma" bo'limida ham uchraydi
    # ("...to'lov qancha ko'p bo'lsa...") va "nechchi pul..." kabi to'lov
    # savollarini noto'g'ri chegirma bo'limiga tortib ketardi (5.7 tuzatishi).
    "nechchi": ["narx"],
    "mustahkam": ["monolit", "zilzilaga", "chidamli"],
    "moshina": ["parkovka", "avtoturargoh", "mashina"],
    "arzonlashtirib": ["chegirma"],
    "qanaqasiga": ["qanday"],
    "oyiga": ["oylik", "to'lov"],
}
