"""Best-effort lookup of display names from the macOS Contacts database."""
from __future__ import annotations

import glob
import os
import re
import sqlite3

AB_GLOBS = [
    "~/Library/Application Support/AddressBook/AddressBook-v22.abcddb",
    "~/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb",
]


def norm_handle(h: str) -> str:
    h = (h or "").strip().lower()
    if "@" in h:
        return h
    digits = re.sub(r"\D", "", h)
    return digits[-10:] if len(digits) >= 10 else digits


def load_contacts() -> dict[str, str]:
    """Map normalized phone/email -> 'First Last'. Empty dict if unavailable."""
    names: dict[str, str] = {}
    for pattern in AB_GLOBS:
        for path in glob.glob(os.path.expanduser(pattern)):
            try:
                conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
                q_phone = """SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, p.ZFULLNUMBER
                             FROM ZABCDRECORD r JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK"""
                q_email = """SELECT r.ZFIRSTNAME, r.ZLASTNAME, r.ZNICKNAME, e.ZADDRESS
                             FROM ZABCDRECORD r JOIN ZABCDEMAILADDRESS e ON e.ZOWNER = r.Z_PK"""
                for q in (q_phone, q_email):
                    for first, last, nick, val in conn.execute(q):
                        name = (nick or " ".join(x for x in (first, last) if x)).strip()
                        if name and val:
                            names.setdefault(norm_handle(val), name)
                conn.close()
            except Exception:
                continue
    return names
