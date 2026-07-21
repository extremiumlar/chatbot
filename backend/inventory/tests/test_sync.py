"""4.4-BOSQICH: sync N+1 kamayishi va backoff testlari (mock, tarmoqsiz).

Ishlatilishi:
    cd backend && ..\.venv\Scripts\python.exe manage.py test inventory.tests.test_sync
"""
from __future__ import annotations

import time
from unittest import mock

from django.test import TestCase

from inventory import services
from inventory.models import Layout


def _fake_get_post(blocks: dict, floors: range, avail_flats: list[dict]):
    """_get/_post ni mock qiladi va chaqiruvlar sonini sanaydi.
    Qaytadi: (fake_get, fake_post, call_counter)."""
    calls = {"get": 0, "post": 0}

    def fake_get(path: str) -> dict:
        calls["get"] += 1
        if path.startswith("/filter-properties/"):
            return {"data": {
                "buildingCompactList": [{"id": bid, "name": name}
                                        for bid, name in blocks.items()],
                "minFloor": floors.start, "maxFloor": floors.stop - 1,
            }}
        if path.startswith("/block-flat-data/"):
            # bo'sh chessboard (sotilgan yo'q) — faqat so'rov sonini sanaymiz
            return {"data": {"blockFlatDataDtoList": []}}
        raise AssertionError(f"kutilmagan GET: {path}")

    def fake_post(path: str, body: dict) -> dict:
        calls["post"] += 1
        return {"data": {"data": avail_flats, "totalPages": 1, "currentPage": 1}}

    return fake_get, fake_post, calls


class SyncRequestCountTests(TestCase):
    """(a) so'rovlar soni ~257 o'rniga ANCHA kam (kichik mock bilan <=15)."""

    def test_request_count_small_building(self):
        blocks = {1: "1", 2: "2"}         # 2 blok
        floors = range(1, 4)               # 3 qavat -> 6 chessboard so'rovi
        avail = [
            {"id": 1, "rooms": 2, "area": 62.0, "block": "1", "floor": 1, "number": "10"},
            {"id": 2, "rooms": 3, "area": 74.6, "block": "2", "floor": 2, "number": "20"},
        ]
        fake_get, fake_post, calls = _fake_get_post(blocks, floors, avail)
        with mock.patch("inventory.services._get", side_effect=fake_get), \
             mock.patch("inventory.services._post", side_effect=fake_post), \
             mock.patch("django.conf.settings.UYSOT_SHOWROOM_TOKEN", "test-token"):
            summary = services.sync_all()

        total = calls["get"] + calls["post"]
        # 1 filter-properties (get) + 1 get-all-flat-by-filter (post) + 6 chessboard (get) = 8
        self.assertLessEqual(total, 15,
            f"so'rovlar soni {total} — 15 dan oshmasligi kerak (eski usulda ~257 edi)")
        self.assertEqual(calls["get"], 1 + 6)   # filter-properties + 2 blok x 3 qavat
        self.assertEqual(calls["post"], 1)      # get-all-flat-by-filter (1 sahifa)
        self.assertIn("Sync tugadi", summary)
        self.assertEqual(Layout.objects.filter(available_count__gt=0).count(), 2)


class SyncBackoffTests(TestCase):
    """(b) ketma-ket muvaffaqiyatsizliklarda darhol qayta urinilmasin."""

    def test_no_immediate_retry_after_failure(self):
        services._last_attempt = 0.0  # holatni tozalaymiz
        attempts = {"n": 0}

        def failing_sync(progress=None):
            attempts["n"] += 1
            raise RuntimeError("Uysot ishlamayapti")

        with mock.patch("inventory.services.sync_all", side_effect=failing_sync):
            services.maybe_auto_sync()   # 1-urinish (Layout bo'sh -> latest=None -> darhol)
            # threading.Thread daemon — natijani kutamiz
            time.sleep(0.3)
            self.assertEqual(attempts["n"], 1)

            services.maybe_auto_sync()   # 2-urinish — backoff ICHIDA, DARHOL qaytishi kerak
            time.sleep(0.1)
            self.assertEqual(attempts["n"], 1, "backoff ichida qayta urinmasligi kerak edi!")

            services.maybe_auto_sync()   # 3-urinish — hali ham backoff ichida
            time.sleep(0.1)
            self.assertEqual(attempts["n"], 1, "3-chi urinish ham darhol bo'lmasligi kerak!")

        # backoff muddatini o'tkazib yuboramiz (test uchun qisqartiramiz)
        services._last_attempt = time.monotonic() - services._RETRY_BACKOFF_SEC - 1
        with mock.patch("inventory.services.sync_all", side_effect=failing_sync):
            services.maybe_auto_sync()
            time.sleep(0.3)
            self.assertEqual(attempts["n"], 2, "backoff tugagach qayta urinishi kerak edi")
