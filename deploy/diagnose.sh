#!/usr/bin/env bash
# Nurli diyor bot — "bot ishlamay qoldi" holatida BIR BUYRUQLIK tekshiruv.
#
# Ishlatilishi (serverda):
#     bash /opt/nurli/chatbot/deploy/diagnose.sh
#
# Hech narsani O'ZGARTIRMAYDI — faqat o'qiydi va hisobot chiqaradi.
# Har bir tekshiruv OK / OGOH / XATO bilan belgilanadi; oxirida eng ehtimolli
# sabab va uni tuzatish buyrug'i yoziladi.
#
# MUHIM: chiqishda maxfiy qiymatlar (API kalitlar, tokenlar) KO'RSATILMAYDI —
# faqat "bor / yo'q" va uzunligi. Hisobotni bemalol nusxalab yuborsangiz bo'ladi.

set -uo pipefail

ROOT="${NURLI_ROOT:-/opt/nurli/chatbot}"
ENV_FILE="$ROOT/.env"
PY="$ROOT/.venv/bin/python"
BACKEND_URL_DEFAULT="http://127.0.0.1:8010"

RED=$'\033[31m'; YEL=$'\033[33m'; GRN=$'\033[32m'; DIM=$'\033[2m'; OFF=$'\033[0m'
PROBLEMS=()

ok()   { printf "  ${GRN}OK${OFF}    %s\n" "$1"; }
warn() { printf "  ${YEL}OGOH${OFF}  %s\n" "$1"; }
bad()  { printf "  ${RED}XATO${OFF}  %s\n" "$1"; PROBLEMS+=("$1"); }
head_() { printf "\n${DIM}=== %s ===${OFF}\n" "$1"; }

# .env dan bitta kalitni o'qiydi (qiymatni CHIQARMAYDI, faqat qaytaradi)
envval() {
    [ -r "$ENV_FILE" ] || return 1
    sed -n "s/^[[:space:]]*$1[[:space:]]*=[[:space:]]*//p" "$ENV_FILE" \
        | tail -n1 | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

# HTTP kodini qaytaradi. curl ulanolmasa o'zi "000" yozadi VA nol bo'lmagan kod
# bilan chiqadi — shuning uchun `|| echo 000` ishlatilmaydi (u "000000" berardi).
httpcode() {
    local out
    out="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$@" 2>/dev/null)"
    printf '%s' "${out:-000}"
}

# Maxfiy o'zgaruvchi bor-yo'qligini tekshiradi (qiymatni ko'rsatmaydi)
check_secret() {
    local key="$1" need="${2:-majburiy}" val
    val="$(envval "$key")"
    if [ -n "$val" ]; then
        ok "$key bor (${#val} belgi)"
    elif [ "$need" = "majburiy" ]; then
        bad "$key .env da YO'Q yoki bo'sh"
    else
        warn "$key yo'q (ixtiyoriy)"
    fi
}

printf "Nurli diyor bot — diagnostika | %s\n" "$(date '+%Y-%m-%d %H:%M:%S %Z')"
printf "Ildiz: %s\n" "$ROOT"

# ---------------------------------------------------------------- 1. Fayllar
head_ "1. Fayllar va muhit"
[ -d "$ROOT" ]     && ok "loyiha papkasi bor"        || bad "loyiha papkasi yo'q: $ROOT"
[ -r "$ENV_FILE" ] && ok ".env o'qiladi"             || bad ".env yo'q yoki o'qilmaydi: $ENV_FILE"
[ -x "$PY" ]       && ok "virtualenv python bor"     || bad "virtualenv yo'q: $PY"

# .env huquqlari — kalitlar hammaga ochiq bo'lmasin
if [ -r "$ENV_FILE" ]; then
    perm="$(stat -c '%a' "$ENV_FILE" 2>/dev/null || echo '?')"
    case "$perm" in
        600|640|660) ok ".env huquqlari $perm" ;;
        *) warn ".env huquqlari $perm — kalitlar boshqalarga ko'rinadi (chmod 600 .env)" ;;
    esac
fi

# Disk — to'lib qolsa SQLite yozolmaydi va bot JIM qoladi (tez-tez uchraydigan sabab)
use="$(df -P "$ROOT" 2>/dev/null | awk 'NR==2{gsub("%","",$5); print $5}')"
if [ -n "$use" ]; then
    if   [ "$use" -ge 98 ]; then bad  "disk ${use}% to'lgan — baza yozilmaydi, bot javob bermaydi"
    elif [ "$use" -ge 90 ]; then warn "disk ${use}% to'lgan"
    else ok "disk ${use}% band"; fi
fi

# SQLite yozilishi
STORAGE="$ROOT/storage"
if [ -d "$STORAGE" ]; then
    if [ -w "$STORAGE" ]; then ok "storage/ yoziladi"
    else bad "storage/ YOZILMAYDI — egasi/huquqini tekshiring (chown -R nurli: $STORAGE)"; fi
else
    warn "storage/ hali yo'q (birinchi ishga tushirishda yaratiladi)"
fi

# ------------------------------------------------------------- 2. Servislar
head_ "2. systemd servislari"
if command -v systemctl >/dev/null 2>&1; then
    for svc in nurli-backend nurli-sync.timer; do
        state="$(systemctl is-active "$svc" 2>/dev/null || true)"
        case "$state" in
            active) ok "$svc — active" ;;
            inactive|failed|"")
                bad "$svc — ${state:-topilmadi} (sudo systemctl status $svc)"
                systemctl status "$svc" --no-pager -n 8 2>/dev/null | sed 's/^/        /'
                ;;
            *) warn "$svc — $state" ;;
        esac
    done
    # Eski Telegram userbot: endi ISHLATILMAYDI (deploy/README.md 4-band)
    if [ "$(systemctl is-active nurli-bot 2>/dev/null || true)" = "active" ]; then
        warn "nurli-bot (eski Telegram userbot) hali ishlayapti — Instagram'ga o'tilgan, o'chirsa bo'ladi"
    fi
else
    warn "systemctl yo'q (cPanel/shared hosting?) — servis tekshiruvi o'tkazib yuborildi"
fi

# --------------------------------------------------------------- 3. Backend
head_ "3. Backend (Django) javob beryaptimi"
BACKEND_URL="$(envval BACKEND_API_URL)"; BACKEND_URL="${BACKEND_URL:-$BACKEND_URL_DEFAULT}"
BOT_TOKEN="$(envval BOT_API_TOKEN)"

code="$(httpcode -H "X-Bot-Token: $BOT_TOKEN" "$BACKEND_URL/api/layouts/")"
case "$code" in
    200) ok "GET $BACKEND_URL/api/layouts/ -> 200" ;;
    401|403) bad "layouts API -> $code — BOT_API_TOKEN bot va backend .env da BIR XIL emas" ;;
    000) bad "backend'ga ULANIB BO'LMADI ($BACKEND_URL) — nurli-backend o'chgan yoki port boshqa" ;;
    *)   bad "layouts API -> $code (kutilgan 200)" ;;
esac

# Tokensiz so'rov 401 qaytarishi kerak — aks holda API ochiq qolgan
nocode="$(httpcode "$BACKEND_URL/api/layouts/")"
[ "$nocode" = "401" ] && ok "tokensiz -> 401 (himoya ishlayapti)" \
                      || warn "tokensiz -> $nocode (401 kutilgandi)"

# Inventar BO'SH bo'lsa bot "sotuvda yo'q" deb javob bera boshlaydi — muhim signal
if [ "$code" = "200" ]; then
    n="$(curl -s --max-time 10 -H "X-Bot-Token: $BOT_TOKEN" "$BACKEND_URL/api/layouts/" \
         | tr ',' '\n' | grep -c '"id"' || true)"
    if [ "${n:-0}" -gt 0 ]; then ok "inventarda $n ta xonadon turi bor"
    else bad "inventar BO'SH — bot barcha turlarni 'sotuvda yo'q' deydi (manage.py sync_layouts)"; fi
fi

# ---------------------------------------------------------------- 4. Kalitlar
head_ "4. .env kalitlari (qiymatlar ko'rsatilmaydi)"
provider="$(envval LLM_PROVIDER)"; provider="${provider:-gemini}"
printf "  LLM_PROVIDER = %s\n" "$provider"
if [ "$provider" = "anthropic" ]; then
    check_secret ANTHROPIC_API_KEY majburiy
    check_secret GEMINI_API_KEY    ixtiyoriy   # zaxira
else
    check_secret GEMINI_API_KEY    majburiy
    check_secret ANTHROPIC_API_KEY ixtiyoriy   # zaxira
fi
check_secret UYSOT_SHOWROOM_TOKEN      majburiy
check_secret DJANGO_SECRET_KEY         majburiy
check_secret BOT_API_TOKEN             majburiy
check_secret INSTAGRAM_PAGE_ACCESS_TOKEN majburiy
check_secret INSTAGRAM_APP_SECRET      majburiy
check_secret INSTAGRAM_VERIFY_TOKEN    majburiy

pub="$(envval PUBLIC_BASE_URL)"
case "$pub" in
    https://*127.0.0.1*|https://*localhost*|http://*) bad "PUBLIC_BASE_URL='$pub' — public HTTPS domen bo'lishi SHART (planirovka rasmi yuborilmaydi)" ;;
    https://*) ok "PUBLIC_BASE_URL = $pub" ;;
    *) bad "PUBLIC_BASE_URL yo'q yoki noto'g'ri — planirovka rasmlari yuborilmaydi" ;;
esac

# ------------------------------------------------------- 5. Tashqi xizmatlar
head_ "5. Tashqi xizmatlar"

# 5a. LLM — bot "javob bermay qolishi"ning ENG TEZ-TEZ sababi (kvota/kalit)
if [ -x "$PY" ]; then
    ( cd "$ROOT" && "$PY" - <<'PYEOF'
import sys
sys.path.insert(0, ".")
try:
    import config
    from knowledge import answer
except Exception as e:
    print(f"  XATO  modul yuklanmadi: {e}"); sys.exit(0)
try:
    txt = answer._generate("Assalomu alaykum", None)
    print(f"  OK    LLM javob berdi ({len(txt)} belgi)")
except Exception as e:
    print(f"  XATO  LLM JAVOB BERMADI: {type(e).__name__}: {e}")
    print("        -> kalit muddati/kvota (429) yoki model nomi eskirgan bo'lishi mumkin.")
    print(f"        -> sinaladigan modellar: {', '.join(config.GEMINI_MODELS)}")
PYEOF
    ) 2>&1 | sed 's/^/  /' | sed 's/^  \(  \)/\1/'
else
    warn "python yo'q — LLM tekshiruvi o'tkazib yuborildi"
fi

# 5b. Uysot showroom
UY_BASE="$(envval UYSOT_SHOWROOM_BASE)"; UY_BASE="${UY_BASE:-https://srv.showroom.app.uysot.uz/v1/website}"
UY_TOK="$(envval UYSOT_SHOWROOM_TOKEN)"
UY_HOUSE="$(envval UYSOT_HOUSE_ID)"; UY_HOUSE="${UY_HOUSE:-880}"
uy="$(httpcode -H "X-Auth: $UY_TOK" "$UY_BASE/filter-properties/$UY_HOUSE")"
case "$uy" in
    200) ok "Uysot API -> 200" ;;
    401|403) bad "Uysot API -> $uy — UYSOT_SHOWROOM_TOKEN eskirgan (yangilash kerak)" ;;
    000) warn "Uysot API'ga ulanib bo'lmadi (tarmoq/DNS)" ;;
    *) warn "Uysot API -> $uy" ;;
esac

# 5c. Instagram Page Access Token — 60 kunda tugaydi, bot JIM qolishining asosiy sababi
IG_TOK="$(envval INSTAGRAM_PAGE_ACCESS_TOKEN)"
IG_VER="$(envval INSTAGRAM_GRAPH_API_VERSION)"; IG_VER="${IG_VER:-v21.0}"
if [ -n "$IG_TOK" ]; then
    ig="$(curl -s --max-time 15 "https://graph.facebook.com/$IG_VER/me?access_token=$IG_TOK" 2>/dev/null)"
    if printf '%s' "$ig" | grep -q '"error"'; then
        bad "Instagram TOKEN ISHLAMAYAPTI — bot Instagram'da javob bermaydi"
        printf '%s' "$ig" | sed 's/^/        /' | head -5
        echo "        -> Meta App Dashboard'da YANGI Page Access Token oling va .env ga yozing"
    else
        ok "Instagram token amal qilyapti"
    fi
fi

# 5d. Webhook tashqaridan ochiqmi (Meta shu manzilga xabar yuboradi)
VERIFY="$(envval INSTAGRAM_VERIFY_TOKEN)"
if [ -n "$pub" ] && [ -n "$VERIFY" ]; then
    body="$(curl -s --max-time 15 \
        "$pub/api/instagram/webhook/?hub.mode=subscribe&hub.verify_token=$VERIFY&hub.challenge=diagnose123" 2>/dev/null)"
    [ "$body" = "diagnose123" ] \
        && ok "webhook tashqaridan ishlayapti (challenge qaytdi)" \
        || bad "webhook JAVOB BERMADI — Meta xabarlarni yetkaza olmaydi (nginx/HTTPS/verify token)"
fi

# ------------------------------------------------------------------ 6. Loglar
head_ "6. Oxirgi xatolar (loglar)"
if command -v journalctl >/dev/null 2>&1; then
    # "-- No entries --" / "-- Logs begin --" sarlavhalari xato EMAS — ularni tashlaymiz
    errs="$(journalctl -u nurli-backend --since '24 hours ago' -p err --no-pager -n 20 2>/dev/null \
            | grep -v '^--' || true)"
    if [ -n "$errs" ]; then
        warn "oxirgi 24 soatda nurli-backend xatolari:"
        printf '%s\n' "$errs" | tail -20 | sed 's/^/        /'
    else
        ok "oxirgi 24 soatda backend xatosi yo'q"
    fi
else
    warn "journalctl yo'q — loglarni qo'lda ko'ring"
fi

# ------------------------------------------------------------------ Xulosa
head_ "XULOSA"
if [ ${#PROBLEMS[@]} -eq 0 ]; then
    printf "  ${GRN}Tekshiruvlar o'tdi — texnik nosozlik topilmadi.${OFF}\n"
    printf "  Bot baribir javob bermayotgan bo'lsa: Meta App Review holatini va\n"
    printf "  menejer aralashuvi (HUMAN_TAKEOVER_MINUTES) o'chirmayotganini tekshiring.\n"
else
    printf "  ${RED}%d ta muammo topildi:${OFF}\n" "${#PROBLEMS[@]}"
    for p in "${PROBLEMS[@]}"; do printf "    • %s\n" "$p"; done
    printf "\n  Yuqoridan pastga tuzating — birinchi muammo ko'pincha qolganlarining sababi.\n"
fi
exit 0
