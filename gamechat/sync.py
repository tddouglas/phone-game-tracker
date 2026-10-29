"""The ingest pipeline: chat.db -> parsed results in state.db."""
from __future__ import annotations

import datetime as dt
import hashlib
import os
from zoneinfo import ZoneInfo

from . import config, imessage, llm
from .parsers import Parser, Result, looks_like_share, slug
from .store import Store


def _llm_result(resp: dict) -> Result | None:
    if not resp.get("is_game_share") or not resp.get("game_name"):
        return None
    name = str(resp["game_name"]).strip()
    score = resp.get("score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    direction = resp.get("direction") if resp.get("direction") in ("lower", "higher") else "lower"
    mx = resp.get("max_score")
    try:
        mx = float(mx) if mx is not None else None
    except (TypeError, ValueError):
        mx = None
    pid = resp.get("puzzle_id")
    return Result(slug(name), name, score, str(resp.get("score_display") or score or "?"),
                  str(pid).replace(",", "") if pid not in (None, "") else None, mx, bool(resp.get("failed")),
                  direction, resp.get("unit") or "other", "llm")


def run(full: bool = False, use_llm: bool = True, db_path: str | None = None, log=print) -> dict:
    cfg = config.load()
    if not cfg.get("chat"):
        raise SystemExit("No chat selected. Run `python3 -m gamechat chats`, then `python3 -m gamechat use <id>`.")
    tz = ZoneInfo(cfg["timezone"])

    conn = imessage.open_snapshot(db_path or cfg["chat_db"])
    chat_ids = imessage.resolve_chat(conn, cfg["chat"])
    if not chat_ids:
        raise SystemExit(f"Chat {cfg['chat']!r} not found. Run `python3 -m gamechat chats` to list chats.")

    store = Store(config.STATE_PATH)
    if full:
        store.reset()
    parser = Parser(config.RULES_PATH, cfg.get("game_aliases"))
    parser.known_keys = store.game_keys()

    llm_cfg = cfg.get("llm") or {}
    api_key = os.environ.get(llm_cfg.get("api_key_env", "ANTHROPIC_API_KEY"), "")
    llm_on = use_llm and llm_cfg.get("enabled", True) and bool(api_key)
    if use_llm and llm_cfg.get("enabled", True) and not api_key:
        log(f"  (LLM fallback off: ${llm_cfg.get('api_key_env', 'ANTHROPIC_API_KEY')} not set)")

    last = int(store.get("last_rowid", 0))
    stats = {"messages": 0, "results": 0, "new_players": [], "new_games": [], "llm_calls": 0,
             "learned_rules": [], "unparsed": 0, "recovered": 0}
    known_games = set(parser.known_keys)

    def process(msg):
        """Parse one message; returns True if it produced results."""
        day = msg.ts.astimezone(tz).date().isoformat()
        results = parser.parse(msg.text)
        note = None
        if not results and looks_like_share(msg.text):
            h = hashlib.sha256(msg.text.encode()).hexdigest()
            resp = store.llm_get(h)
            if resp is None and llm_on:
                try:
                    resp = llm.classify(msg.text, api_key, llm_cfg["model"])
                    store.llm_put(h, resp)
                    stats["llm_calls"] += 1
                except llm.LLMError as e:
                    note = f"llm error: {e}"
            if resp is not None:
                r = _llm_result(resp)
                if r:
                    rule = resp.get("rule") or {}
                    if rule.get("detect"):
                        rule = {k: v for k, v in rule.items() if v is not None}
                        rule.update(name=r.game_name, key=r.game_key, direction=r.direction, unit=r.unit,
                                    source="llm")
                        if r.max_score is not None and "max_score" not in rule:
                            rule["max_score"] = r.max_score
                        if parser.learn(rule, r, msg.text):
                            stats["learned_rules"].append(r.game_name)
                            r.source = "llm-rule"
                    results = [parser._canon(r)]
                else:
                    note = note or "llm: not a game share"
            elif not note:
                note = "looks like a share; no parser matched (LLM off)"

        for r in results:
            store.add_result(msg, day, r, msg.text)
            stats["results"] += 1
            if r.game_key not in known_games:
                known_games.add(r.game_key)
                parser.known_keys.add(r.game_key)
                stats["new_games"].append(r.game_name)
        if not results and note:
            store.add_unparsed(msg, note)
        return bool(results)

    # Retry earlier misses first: rules may have been edited or the LLM turned on since.
    for row in store.unparsed(limit=100000):
        msg = imessage.Message(row["msg_rowid"], row["handle"], dt.datetime.fromisoformat(row["ts"]), row["text"])
        if process(msg):
            stats["recovered"] += 1

    first_run = last == 0
    for msg in imessage.fetch_messages(conn, chat_ids, last):
        stats["messages"] += 1
        if store.touch_handle(msg.handle, msg.ts) and not first_run:
            stats["new_players"].append(msg.handle)
        process(msg)
        last = msg.rowid

    stats["unparsed"] = len(store.unparsed(limit=100000))
    store.set("last_rowid", last)
    store.commit()
    return stats
