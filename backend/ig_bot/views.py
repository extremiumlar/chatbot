"""Instagram Messaging webhook — Meta bu manzilga xabar keldi deb POST qiladi.

Bot mantig'i shu yerda EMAS — faqat tasdiqlash (GET) va imzo tekshiruvi (POST)
qilib, qayta ishlashni repo ildizidagi `instagram_bot.py` moduliga topshiradi
(backend/core/settings.py repo ildizini sys.path'ga qo'shgan — shu tufayli
bevosita import qilish mumkin, alohida jarayon/port shart emas).
"""
from __future__ import annotations

import json
import logging

from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

import instagram_bot

log = logging.getLogger("ig_bot")


@csrf_exempt
@require_http_methods(["GET", "POST"])
def webhook(request):
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge", "")
        if instagram_bot.verify_subscription(mode, token):
            return HttpResponse(challenge, content_type="text/plain")
        log.warning("Instagram webhook: GET tasdiqlash rad etildi (mode=%s).", mode)
        return HttpResponseForbidden("Verification failed")

    # POST — Meta'dan kelgan hodisa
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not instagram_bot.verify_signature(request.body, signature):
        log.warning("Instagram webhook: imzo tekshiruvidan o'tmadi.")
        return HttpResponseForbidden("Invalid signature")

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        log.warning("Instagram webhook: JSON parse xatosi.")
        return JsonResponse({"error": "bad json"}, status=400)

    try:
        instagram_bot.handle_webhook_payload(payload)
    except Exception:  # noqa: BLE001 - Meta qayta-qayta urinib qolmasin, baribir 200
        log.exception("Instagram webhook payload'ni qayta ishlashda kutilmagan xato.")

    return HttpResponse("OK")
