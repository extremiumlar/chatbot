"""Gibrid qidiruv — vektor (semantik) + kalit-so'z mosligi.

Nega gibrid: ko'p tilli embedding modellari o'zbekcha qisqa so'rovlarda ba'zan
noto'g'ri bo'lakni yuqori baholaydi. Kalit-so'z qatlami buni tuzatadi: so'rovdagi
so'z (yoki uning sinonimi, uz_synonyms.py) bo'lak matnida bo'lsa — ball oshadi.

Yakuniy ball: RAG_VECTOR_WEIGHT * vektor + (1 - RAG_VECTOR_WEIGHT) * kalit_so'z.
config.RAG_MIN_SCORE shu YAKUNIY ballga qo'llanadi (answer.py da).

Torch faqat vektor qidiruv chaqirilganda yuklanadi — bu modul import'da yengil.
"""
from __future__ import annotations

import re

import config
from knowledge.uz_synonyms import SYNONYMS

# O'zbek apostrofining barcha ko'rinishlari bitta belgiga keltiriladi
_APOSTROPHES = str.maketrans({"ʻ": "'", "'": "'", "'": "'", "`": "'", "‛": "'"})

# O'zbek kirill -> lotin transliteratsiyasi. KB bo'laklari lotinchada, mijozlar esa
# ko'pincha kirillда yozadi ("чегирма борми") — bu jadval ikkala yozuvni bitta
# fazoga keltiradi, shunda kalit-so'z qatlami ham, e5 vektor ham to'g'ri solishtiradi.
# Nozikliklar:
#   - х→x, ҳ→h FARQLI ("хонадон"→"xonadon", "ҳужжат"→"hujjat" — KB imlosiga mos);
#   - ц→ts ("инвестиция"→"investitsiya");
#   - е→e — soddalashtirish (so'z boshida aslida "ye"): moslik-qidiruv uchun yetarli;
#   - jadvalda lotin harf YO'Q — lotin matn o'zgarmaydi (oltin-to'plam regressiyasiz).
_CYR2LAT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "'", "ь": "", "ы": "i", "э": "e", "ю": "yu", "я": "ya",
    "қ": "q", "ғ": "g'", "ў": "o'", "ҳ": "h",
})

# Juda umumiy so'zlar — moslik hisobiga kirmaydi
_STOPWORDS = frozenset({
    "bormi", "qancha", "necha", "qanday", "qanaqa", "nima", "nimadan", "qachon",
    "qayer", "qayerda", "mumkinmi", "kerak", "va", "uchun", "bilan", "ham",
    "bo'ladi", "qilinadi", "berish", "olsa", "olish", "bu", "u",
    # "beriladi" ATAYIN stopword emas — sinonim orqali "topshiriladi"ga yo'naltiriladi
    # ("kvartira qachon beriladi" savoli topshirish bo'lagini topishi uchun).
})


def normalize(text: str) -> str:
    """Kichik harf + apostrof birlashtirish + kirill→lotin + bo'shliqni yig'ish.

    lower() transliteratsiyadan OLDIN — katta kirill harflar ham qamrab olinadi.
    keyword_score ham so'rovni, ham bo'lakni shu funksiya orqali o'tkazadi,
    shuning uchun transliteratsiya ikkala tomonga avtomatik simmetrik."""
    text = text.lower().translate(_APOSTROPHES).translate(_CYR2LAT)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    """Ma'noli tokenlar: stopword'lar va 3 belgidan qisqalari tashlanadi."""
    return [t for t in re.findall(r"[\w']+", normalize(text), flags=re.UNICODE)
            if len(t) >= 3 and t not in _STOPWORDS]


def _expansions(token: str) -> list[str]:
    """Token + uning sinonimlari (lug'atdan).

    Qo'shimchali so'zlar uchun prefiks-kalit qidiruvi ham bor: "pulini" lug'atda
    yo'q, lekin "pul" kalitidan boshlanadi -> o'sha sinonimlar olinadi ("garantiyasi"
    -> "garantiya" ham shunday). Eng UZUN mos kalit tanlanadi; kalit kamida 3 belgi
    (token o'zi ham >=3, _tokens filtri)."""
    hit = SYNONYMS.get(token)
    if hit is not None:
        return [token] + hit
    best_key = ""
    for key in SYNONYMS:
        if len(key) >= 3 and len(key) > len(best_key) and token.startswith(key):
            best_key = key
    if best_key:
        return [token] + SYNONYMS[best_key]
    return [token]


def _token_in_text(token: str, text: str) -> bool:
    """Token matnda bormi — to'liq yoki o'zak (prefiks) ko'rinishida.
    O'zbek qo'shimchali til uchun yengil "stemming": uzun tokenning birinchi 6 belgisi
    ham tekshiriladi ("zilzilaga" -> "zilzil" ni "zilzilaga chidamli"da topadi).
    5 belgili prefiks juda qisqa — "joylashgan"[:5]="joyla" parkovkadagi "joylari"ga
    yolg'on moslashardi; shuning uchun kamida 6."""
    if token in text:
        return True
    if len(token) >= 7 and token[:6] in text:   # yengil "stemming" (prefiks)
        return True
    return False


def keyword_score(query: str, chunk_text: str) -> float:
    """So'rov tokenlarining (sinonimlar bilan kengaytirilgan) bo'lakda uchrash ulushi, 0..1."""
    q_tokens = _tokens(query)
    if not q_tokens:
        return 0.0
    text = normalize(chunk_text)
    matched = sum(
        1 for t in q_tokens
        if any(_token_in_text(e, text) for e in _expansions(t))
    )
    return matched / len(q_tokens)


def has_contrast(hits: list[dict], min_gap: float | None = None) -> bool:
    """True — qidiruv haqiqatan G'OLIB topgan bo'lsa.

    Top-1 ball qolgan nomzodlar O'RTACHASIDAN kamida min_gap ga yuqori bo'lishi
    kerak. Hamma ball bir-biriga yopishgan bo'lsa (masalan kirill savolda e5
    hammaga ~0.48 berganda) — qidiruv aslida hech narsa topmagan, RAG jim
    turgani ma'qul (chalg'ituvchi kontekst promptga kirmasin).

    min_gap default: config.RAG_MIN_CONTRAST. Nomzod bitta bo'lsa — True
    (solishtiradigan narsa yo'q, MIN_SCORE filtri yetarli)."""
    if min_gap is None:
        min_gap = config.RAG_MIN_CONTRAST
    if not hits:
        return False
    if len(hits) == 1:
        return True
    scores = sorted((h.get("score", 0.0) for h in hits), reverse=True)
    rest_avg = sum(scores[1:]) / len(scores[1:])
    return scores[0] - rest_avg >= min_gap


def hybrid_search(query: str, top_k: int = 5) -> list[dict]:
    """Vektor natijalarni kalit-so'z balli bilan qayta saralaydi.

    Qaytadi: [{chunk_id, text, score(YAKUNIY), vec_score, kw_score, meta}, ...]
    Eslatma: nomzodlar vektor qidiruvning kengaytirilgan (top_k*3) ro'yxatidan olinadi —
    vektor umuman topolmagan bo'lak kalit-so'z bilan ham kirmaydi (kichik korpusда muammo emas).
    """
    from knowledge import vectorstore  # torch shu yerda, chaqirilgandagina yuklanadi

    n_cand = min(max(top_k * 3, 10), max(vectorstore.count(), 1))
    # Vektorga ham NORMALIZE'langan so'rov beramiz: "кафолат неча йил" e5'ga
    # "kafolat necha yil" bo'lib boradi — lotin bo'laklar bilan bitta yozuv
    # fazosida solishtiriladi (kirillda e5 ballari yopishib qolishining davosi).
    hits = vectorstore.search(normalize(query), top_k=n_cand)

    w = config.RAG_VECTOR_WEIGHT
    for h in hits:
        h["vec_score"] = h["score"]
        h["kw_score"] = keyword_score(query, h["text"])
        h["score"] = w * h["vec_score"] + (1 - w) * h["kw_score"]

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]
