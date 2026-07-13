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

# Juda umumiy so'zlar — moslik hisobiga kirmaydi
_STOPWORDS = frozenset({
    "bormi", "qancha", "necha", "qanday", "qanaqa", "nima", "nimadan", "qachon",
    "qayer", "qayerda", "mumkinmi", "kerak", "va", "uchun", "bilan", "ham",
    "bo'ladi", "qilinadi", "beriladi", "berish", "olsa", "olish", "bu", "u",
})


def normalize(text: str) -> str:
    """Kichik harf + apostrof variantlarini birlashtirish + ortiqcha bo'shliqni yig'ish."""
    text = text.lower().translate(_APOSTROPHES)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text: str) -> list[str]:
    """Ma'noli tokenlar: stopword'lar va 3 belgidan qisqalari tashlanadi."""
    return [t for t in re.findall(r"[\w']+", normalize(text), flags=re.UNICODE)
            if len(t) >= 3 and t not in _STOPWORDS]


def _expansions(token: str) -> list[str]:
    """Token + uning sinonimlari (lug'atdan)."""
    return [token] + SYNONYMS.get(token, [])


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


def hybrid_search(query: str, top_k: int = 5) -> list[dict]:
    """Vektor natijalarni kalit-so'z balli bilan qayta saralaydi.

    Qaytadi: [{chunk_id, text, score(YAKUNIY), vec_score, kw_score, meta}, ...]
    Eslatma: nomzodlar vektor qidiruvning kengaytirilgan (top_k*3) ro'yxatidan olinadi —
    vektor umuman topolmagan bo'lak kalit-so'z bilan ham kirmaydi (kichik korpusда muammo emas).
    """
    from knowledge import vectorstore  # torch shu yerda, chaqirilgandagina yuklanadi

    n_cand = min(max(top_k * 3, 10), max(vectorstore.count(), 1))
    hits = vectorstore.search(query, top_k=n_cand)

    w = config.RAG_VECTOR_WEIGHT
    for h in hits:
        h["vec_score"] = h["score"]
        h["kw_score"] = keyword_score(query, h["text"])
        h["score"] = w * h["vec_score"] + (1 - w) * h["kw_score"]

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits[:top_k]
