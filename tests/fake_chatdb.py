"""Build a fake Messages chat.db with ~60 days of game shares, for testing without a Mac.

  python3 tests/fake_chatdb.py tests/fake_chat.db
"""
from __future__ import annotations

import datetime as dt
import random
import sqlite3
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
APPLE_EPOCH = dt.datetime(2001, 1, 1, tzinfo=dt.timezone.utc)
END = dt.date(2026, 10, 28)
DAYS = 60

PLAYERS = {  # handle -> (skill 0..1, play probability, joins on day index)
    "me": (0.7, 0.9, 0),
    "+12125550101": (0.8, 0.85, 0),
    "+12125550102": (0.5, 0.75, 0),
    "dana@example.com": (0.6, 0.6, 0),
    "+19175550199": (0.65, 0.8, 32),   # joins the chat partway through
}


def attributed_body(text: str) -> bytes:
    b = text.encode()
    n = bytes([len(b)]) if len(b) < 0x80 else b"\x81" + len(b).to_bytes(2, "little")
    return (b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSAttributedString\x00\x84\x84\x08NSObject"
            b"\x00\x85\x92\x84\x84\x84\x08NSString\x01\x94\x84\x01+" + n + b + b"\x86\x84\x02iI\x01")


def guesses(skill, maxg=6):
    g = 1 + int(random.expovariate(0.9 + skill) * 2.4) + (0 if random.random() < skill else 1)
    return g if g <= maxg else None


def wordle(day, skill):
    num = (day - dt.date(2021, 6, 19)).days
    g = guesses(skill)
    rows = ["⬛🟨⬛⬛🟩", "🟩⬛🟨🟩⬛", "🟩🟩⬛🟩🟩", "🟩🟩🟩🟩⬛", "🟩🟩🟩🟩⬛", "🟩🟩🟩🟩⬛"]
    body = rows[: (g or 6) - 1] + (["🟩🟩🟩🟩🟩"] if g else [rows[5]])
    return f"Wordle {num:,} {g or 'X'}/6\n\n" + "\n".join(body)


def connections(day, skill):
    num = (day - dt.date(2023, 6, 12)).days + 1
    colors = ["🟨", "🟩", "🟦", "🟪"]
    random.shuffle(colors)
    rows, solved, mistakes = [], 0, 0
    while solved < 4 and mistakes < 4:
        if random.random() < 0.55 + skill * 0.4:
            rows.append(colors[solved] * 4); solved += 1
        else:
            r = [colors[solved]] * 3 + [colors[(solved + 1) % 4]]; random.shuffle(r)
            rows.append("".join(r)); mistakes += 1
    return f"Connections\nPuzzle #{num}\n" + "\n".join(rows)


def strands(day, skill):
    num = (day - dt.date(2024, 3, 4)).days + 1
    hints = max(0, int(random.gauss(2.2 - 2 * skill, 1)))
    cells = ["💡"] * hints + ["🔵"] * 6 + ["🟡"]
    random.shuffle(cells)
    return f"Strands #{num}\n“Under the sea”\n" + "".join(cells[:4]) + "\n" + "".join(cells[4:])


def globle(day, skill):
    n = max(1, int(random.gauss(9 - 6 * skill, 3)))
    return (f"🌎 {day.strftime('%b')} {day.day}, {day.year} 🌍\n🔥 {random.randint(1, 30)} | Avg. Guesses: 6.1\n"
            + "🟧🟨🟩"[: min(3, n)] + f" = {n}\n\nhttps://globle-game.com\n#globle")


def mini(day, skill):
    secs = max(14, int(random.gauss(95 - 60 * skill, 25)))
    return f"I solved the {day.month}/{day.day}/{day.year} New York Times Mini Crossword in {secs // 60}:{secs % 60:02d}!"


def costcodle(day, skill):
    num = (day - dt.date(2023, 1, 1)).days
    g = guesses(skill)
    return f"Costcodle #{num} {g or 'X'}/6\n" + "⬇️🟥\n" * ((g or 6) - 1) + "✅\nhttps://costcodle.com"


def krillian(day, skill):
    num = (day - dt.date(2026, 4, 1)).days
    krill = max(0, int(random.gauss(4 + 6 * skill, 2)))
    return f"Krillian #{num} — {krill} krill 🦐\n🟦🟦🟩🟦🟩\n🌊🌊🦐🌊\nkrillian.fun"


GAMES = [  # (fn, starts on day index, popularity)
    (wordle, 0, 1.0), (connections, 0, 0.9), (strands, 0, 0.5), (globle, 0, 0.7),
    (mini, 10, 0.6), (costcodle, 20, 0.5), (krillian, 41, 0.8),
]
CHATTER = ["lol", "brutal one today", "Lunch at 12 then 2/3 of us left", "who's in for trivia thursday",
           "that connections purple was evil", "https://www.nytimes.com/2026/10/01/style/some-article.html"]


def build(path: Path):
    random.seed(7)
    path.unlink(missing_ok=True)
    c = sqlite3.connect(str(path))
    c.executescript("""
    CREATE TABLE handle (ROWID INTEGER PRIMARY KEY, id TEXT, service TEXT);
    CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, chat_identifier TEXT, display_name TEXT);
    CREATE TABLE chat_handle_join (chat_id INTEGER, handle_id INTEGER);
    CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER, message_date INTEGER);
    CREATE TABLE message (ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, attributedBody BLOB, date INTEGER,
                          is_from_me INTEGER, handle_id INTEGER, associated_message_type INTEGER DEFAULT 0);
    """)
    hid = {}
    for h in PLAYERS:
        if h != "me":
            cur = c.execute("INSERT INTO handle (id, service) VALUES (?, 'iMessage')", (h,))
            hid[h] = cur.lastrowid
    c.execute("INSERT INTO chat VALUES (1, 'iMessage;+;chat123', 'chat123', 'Game Chat')")
    c.execute("INSERT INTO chat VALUES (2, 'iMessage;-;+12125550101', '+12125550101', NULL)")  # a DM, ignored
    for h, i in hid.items():
        c.execute("INSERT INTO chat_handle_join VALUES (1, ?)", (i,))

    def post(handle, when: dt.datetime, text, body_only=False, assoc=0):
        ns = int((when.astimezone(dt.timezone.utc) - APPLE_EPOCH).total_seconds() * 1e9)
        cur = c.execute(
            "INSERT INTO message (guid, text, attributedBody, date, is_from_me, handle_id, associated_message_type)"
            " VALUES (?,?,?,?,?,?,?)",
            (f"G{random.random()}", None if body_only else text, attributed_body(text), ns,
             1 if handle == "me" else 0, hid.get(handle, 0), assoc))
        c.execute("INSERT INTO chat_message_join VALUES (1, ?, ?)", (cur.lastrowid, ns))

    events = []
    for di in range(DAYS):
        day = END - dt.timedelta(days=DAYS - 1 - di)
        for h, (skill, prob, joins) in PLAYERS.items():
            if di < joins:
                continue
            for fn, start, pop in GAMES:
                if di >= start and random.random() < prob * pop:
                    when = dt.datetime.combine(day, dt.time(7), TZ) + dt.timedelta(minutes=random.randint(0, 16 * 60))
                    events.append((when, h, fn(day, skill)))
        for _ in range(random.randint(0, 3)):
            when = dt.datetime.combine(day, dt.time(9), TZ) + dt.timedelta(minutes=random.randint(0, 600))
            events.append((when, random.choice(list(PLAYERS)), random.choice(CHATTER)))
    events.sort(key=lambda e: e[0])
    for i, (when, h, text) in enumerate(events):
        post(h, when, text, body_only=(i % 3 == 0))          # a third only in attributedBody
        if i % 25 == 0:                                       # modern tapback (filtered by type)
            post(random.choice(list(PLAYERS)), when + dt.timedelta(minutes=1), f'Loved “{text[:20]}”', assoc=2000)
        if i % 40 == 0 and text.startswith("Wordle"):         # duplicate repost
            post(h, when + dt.timedelta(minutes=3), text)
    post("+12125550102", dt.datetime.combine(END, dt.time(20), TZ), 'Laughed at “brutal one today”')  # old tapback
    c.commit()
    c.close()
    return len(events)


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("fake_chat.db"))
    print(f"wrote {build(out)} events to {out}")
