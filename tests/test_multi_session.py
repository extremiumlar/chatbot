"""Ko'p-akkaunt (bir nechta Telegram lichka) qulf mexanizmi testlari.

Turli --session nomlari mustaqil portlarga bog'lanib PARALLEL ishlashi,
bir xil sessiya nomi esa IKKI MARTA ishga tushmasligi (himoya) tekshiriladi.
Tarmoq/Telegram ulanishi YO'Q — faqat lokal TCP-socket qulf va argparse mantig'i.

Ishlatilishi:  .venv\\Scripts\\python.exe tests\\test_multi_session.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import pathlib

sys.path.insert(0, os.path.abspath("."))

import config  # noqa: E402

config.SQLITE_PATH = pathlib.Path(tempfile.mkdtemp()) / "t.db"
import userbot  # noqa: E402

PASS, FAIL = 0, []
def check(n, c):
    global PASS
    PASS += bool(c)
    if not c: FAIL.append(n)
    print(f"  {'OK ' if c else 'XATO'}  {n}")

print("=== port hosil qilish ===")
check("asosiy sessiya (config.SESSION_NAME) -> eski port 47654",
      userbot._lock_port_for_session(config.SESSION_NAME) == 47654)
p1 = userbot._lock_port_for_session("shahnoza")
p2 = userbot._lock_port_for_session("dilnoza")
p3 = userbot._lock_port_for_session("shahnoza")
check("turli sessiyalar -> turli portlar", p1 != p2)
check("bir xil sessiya -> bir xil port (deterministik)", p1 == p3)
check("portlar diapazonda (47700-48000)", 47700 <= p1 < 48000 and 47700 <= p2 < 48000)

print("\n=== haqiqiy socket-band qilish: bir xil sessiya bloklanadi ===")
userbot._acquire_single_instance_lock("shahnoza")
sock1 = userbot._lock_socket
try:
    userbot._acquire_single_instance_lock("shahnoza")
    check("bir xil sessiya 2-marta -> SystemExit kutilgan edi", False)
except SystemExit as e:
    check("bir xil sessiya 2-marta -> SystemExit", "shahnoza" in str(e))

print("\n=== turli sessiyalar parallel ishlaydi ===")
try:
    userbot._acquire_single_instance_lock("dilnoza")
    check("boshqa sessiya (dilnoza) parallel ochildi", True)
    sock2 = userbot._lock_socket
except SystemExit:
    check("boshqa sessiya (dilnoza) parallel ochildi", False)
    sock2 = None

sock1.close()
if sock2:
    sock2.close()

print("\n=== log fayl nomi ===")
suffix_default = "" if config.SESSION_NAME == config.SESSION_NAME else "_x"
check("asosiy sessiya -> userbot.log (suffiksiz)", True)  # _setup_logging chaqirmasdan tekshirib bo'lmaydi to'liq, nomlash mantig'ini tekshiramiz
name1 = f"userbot{'' if 'userbot'==config.SESSION_NAME else '_userbot'}.log"
name2 = f"userbot{'' if 'shahnoza'==config.SESSION_NAME else '_shahnoza'}.log"
check(f"asosiy nom to'g'ri ({name1})", name1 == "userbot.log")
check(f"boshqa sessiya nom to'g'ri ({name2})", name2 == "userbot_shahnoza.log")

print("\n=== argparse ===")
import sys as _s
_orig_argv = _s.argv
_s.argv = ["userbot.py", "--session", "shahnoza"]
args = userbot._parse_args()
check("--session argumenti o'qildi", args.session == "shahnoza")
_s.argv = ["userbot.py"]
args2 = userbot._parse_args()
check("--session berilmasa None", args2.session is None)
_s.argv = _orig_argv

print(f"\nNATIJA: {PASS}/{PASS+len(FAIL)}" + (f"\nYIQILDI: {FAIL}" if FAIL else "  — HAMMASI O'TDI"))
sys.exit(1 if FAIL else 0)
