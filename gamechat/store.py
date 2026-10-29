"""Local SQLite state (state.db). Holds phone numbers - never published."""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS handles (handle TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT, messages INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY,
    msg_rowid INTEGER, handle TEXT, ts TEXT, day TEXT,
    game_key TEXT, game_name TEXT, puzzle_id TEXT,
    score REAL, score_display TEXT, max_score REAL, failed INTEGER,
    direction TEXT, unit TEXT, source TEXT, raw TEXT,
    UNIQUE (msg_rowid, game_key)
);
CREATE TABLE IF NOT EXISTS unparsed (msg_rowid INTEGER PRIMARY KEY, handle TEXT, ts TEXT, text TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS llm_cache (h TEXT PRIMARY KEY, response TEXT, created TEXT);
"""


class Store:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # meta
    def get(self, k, default=None):
        r = self.conn.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def set(self, k, v):
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (k, str(v)))

    def reset(self):
        self.conn.executescript("DELETE FROM results; DELETE FROM unparsed; DELETE FROM meta WHERE k='last_rowid';")

    # handles
    def touch_handle(self, handle: str, ts: dt.datetime) -> bool:
        iso = ts.isoformat()
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO handles (handle, first_seen, last_seen, messages) VALUES (?,?,?,1)",
            (handle, iso, iso))
        if cur.rowcount:
            return True
        self.conn.execute(
            "UPDATE handles SET last_seen=MAX(last_seen, ?), messages=messages+1 WHERE handle=?", (iso, handle))
        return False

    def handles(self):
        return self.conn.execute(
            """SELECT h.*, (SELECT COUNT(*) FROM results r WHERE r.handle=h.handle) AS results
               FROM handles h ORDER BY first_seen""").fetchall()

    # results
    def add_result(self, msg, day: str, r, raw: str):
        self.conn.execute(
            """INSERT OR REPLACE INTO results
               (msg_rowid, handle, ts, day, game_key, game_name, puzzle_id, score, score_display, max_score,
                failed, direction, unit, source, raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (msg.rowid, msg.handle, msg.ts.isoformat(), day, r.game_key, r.game_name, r.puzzle_id, r.score,
             r.score_display, r.max_score, int(r.failed), r.direction, r.unit, r.source, raw))
        self.conn.execute("DELETE FROM unparsed WHERE msg_rowid=?", (msg.rowid,))

    def results(self):
        return self.conn.execute("SELECT * FROM results ORDER BY ts").fetchall()

    def game_keys(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT DISTINCT game_key FROM results")}

    def games(self):
        return self.conn.execute(
            """SELECT game_key, game_name, COUNT(*) n, COUNT(DISTINCT handle) players, MIN(day) first, MAX(day) last,
                      GROUP_CONCAT(DISTINCT source) sources
               FROM results GROUP BY game_key ORDER BY n DESC""").fetchall()

    # unparsed candidates
    def add_unparsed(self, msg, note: str):
        self.conn.execute("INSERT OR REPLACE INTO unparsed VALUES (?,?,?,?,?)",
                          (msg.rowid, msg.handle, msg.ts.isoformat(), msg.text, note))

    def unparsed(self, limit=50):
        return self.conn.execute("SELECT * FROM unparsed ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()

    # llm cache
    def llm_get(self, h):
        r = self.conn.execute("SELECT response FROM llm_cache WHERE h=?", (h,)).fetchone()
        return json.loads(r[0]) if r else None

    def llm_put(self, h, resp: dict):
        self.conn.execute("INSERT OR REPLACE INTO llm_cache VALUES (?,?,?)",
                          (h, json.dumps(resp, ensure_ascii=False), dt.datetime.now().isoformat()))

    def commit(self):
        self.conn.commit()
