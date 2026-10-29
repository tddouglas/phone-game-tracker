"""Read-only access to the macOS Messages database (chat.db).

We never open the live database directly: Messages holds it open with WAL
journaling, so we copy chat.db (+ -wal/-shm) to a temp dir and read the copy.
"""
from __future__ import annotations

import atexit
import datetime as dt
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB = "~/Library/Messages/chat.db"
APPLE_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)

# Old-style (SMS / pre-iOS 14) tapbacks arrive as plain text messages.
TAPBACK_RE = re.compile(
    r'^(Loved|Liked|Disliked|Laughed at|Emphasized|Questioned|Reacted .{1,8} to|Removed an? .{1,24} from) [“"]'
)

FDA_HINT = (
    "Couldn't read the Messages database. Give your terminal app Full Disk Access "
    "(System Settings → Privacy & Security → Full Disk Access), then restart the terminal."
)


class MessagesAccessError(RuntimeError):
    pass


@dataclass
class Message:
    rowid: int
    handle: str          # phone number / email, or "me"
    ts: dt.datetime      # UTC
    text: str


def apple_time(value) -> dt.datetime:
    """message.date is seconds since 2001 on old macOS, nanoseconds on newer."""
    v = value or 0
    secs = v / 1e9 if abs(v) > 1e11 else v
    return APPLE_EPOCH + dt.timedelta(seconds=secs)


def decode_attributed_body(blob: bytes | None) -> str | None:
    """Pull the plain string out of an NSAttributedString typedstream blob.

    Since macOS Ventura many messages have text=NULL and the content only in
    attributedBody. Layout after the class name: b"NSString" 01 94 84 01 '+' <len> <utf8>,
    where <len> is 1 byte, or 0x81 + uint16-le, or 0x82 + uint32-le.
    """
    if not blob:
        return None
    try:
        i = blob.find(b"NSString")
        if i < 0:
            return None
        j = blob.find(b"+", i + 8, i + 20)
        if j < 0:
            return None
        j += 1
        n = blob[j]
        j += 1
        if n == 0x81:
            n = int.from_bytes(blob[j:j + 2], "little")
            j += 2
        elif n == 0x82:
            n = int.from_bytes(blob[j:j + 4], "little")
            j += 4
        return blob[j:j + n].decode("utf-8", errors="replace")
    except Exception:
        return None


def open_snapshot(db_path: str = DEFAULT_DB) -> sqlite3.Connection:
    src = Path(db_path).expanduser()
    tmp = Path(tempfile.mkdtemp(prefix="gamechat-"))
    atexit.register(shutil.rmtree, tmp, True)
    try:
        if not src.exists():
            raise MessagesAccessError(f"No Messages database at {src}. " + FDA_HINT)
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(src) + suffix)
            if p.exists():
                shutil.copy2(p, tmp / ("chat.db" + suffix))
    except PermissionError as e:
        raise MessagesAccessError(FDA_HINT) from e
    conn = sqlite3.connect(str(tmp / "chat.db"))
    conn.row_factory = sqlite3.Row
    return conn


def _columns(conn, table) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def list_chats(conn: sqlite3.Connection, limit: int = 40) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.ROWID AS id, c.guid, c.chat_identifier, c.display_name,
               (SELECT COUNT(*) FROM chat_handle_join chj WHERE chj.chat_id = c.ROWID) AS members,
               (SELECT COUNT(*) FROM chat_message_join cmj WHERE cmj.chat_id = c.ROWID) AS messages,
               (SELECT MAX(m.date) FROM chat_message_join cmj JOIN message m ON m.ROWID = cmj.message_id
                 WHERE cmj.chat_id = c.ROWID) AS last
        FROM chat c
        ORDER BY last DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["last"] = apple_time(d["last"]) if d["last"] else None
        out.append(d)
    return out


def chat_members(conn: sqlite3.Connection, chat_ids: list[int]) -> list[str]:
    qs = ",".join("?" * len(chat_ids))
    return [r[0] for r in conn.execute(
        f"""SELECT DISTINCT h.id FROM chat_handle_join chj JOIN handle h ON h.ROWID = chj.handle_id
            WHERE chj.chat_id IN ({qs})""", chat_ids)]


def resolve_chat(conn: sqlite3.Connection, selector) -> list[int]:
    """selector: chat ROWID, guid, chat_identifier, or display name (case-insensitive).

    A group can be split across several chat rows (e.g. iMessage + SMS), so a
    display-name match returns every row with that name.
    """
    s = str(selector).strip()
    if s.isdigit():
        if conn.execute("SELECT 1 FROM chat WHERE ROWID = ?", (int(s),)).fetchone():
            return [int(s)]
    rows = conn.execute(
        """SELECT ROWID FROM chat
           WHERE guid = ? OR chat_identifier = ? OR LOWER(COALESCE(display_name,'')) = LOWER(?)""",
        (s, s, s),
    ).fetchall()
    return [r[0] for r in rows]


def fetch_messages(conn: sqlite3.Connection, chat_ids: list[int], after_rowid: int = 0):
    cols = _columns(conn, "message")
    body = "m.attributedBody" if "attributedBody" in cols else "NULL"
    assoc = "AND COALESCE(m.associated_message_type, 0) = 0" if "associated_message_type" in cols else ""
    qs = ",".join("?" * len(chat_ids))
    q = f"""
        SELECT m.ROWID AS rowid, m.text, {body} AS body, m.date, m.is_from_me, h.id AS handle
        FROM message m
        JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
        LEFT JOIN handle h ON h.ROWID = m.handle_id
        WHERE cmj.chat_id IN ({qs}) AND m.ROWID > ? {assoc}
        ORDER BY m.ROWID
    """
    seen = set()
    for r in conn.execute(q, (*chat_ids, after_rowid)):
        if r["rowid"] in seen:
            continue
        seen.add(r["rowid"])
        text = r["text"] or decode_attributed_body(r["body"]) or ""
        text = text.replace("￼", "").replace(" ", "\n").strip()
        if not text or TAPBACK_RE.match(text):
            continue
        handle = "me" if r["is_from_me"] else (r["handle"] or "unknown")
        yield Message(r["rowid"], handle, apple_time(r["date"]), text)
