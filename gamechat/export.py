"""Build site/data.json from state.db. Only display names and opaque ids leave the Mac."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections import Counter, defaultdict

from . import config
from .contacts import load_contacts, norm_handle
from .store import Store

URL_STRIP = re.compile(r"\s*https?://\S+")


def mask(handle: str) -> str:
    if "@" in handle:
        user, _, domain = handle.partition("@")
        return f"{user[:1]}…@{domain}"
    digits = re.sub(r"\D", "", handle)
    return f"•••{digits[-4:]}" if digits else handle


def name_map(store: Store, cfg: dict) -> dict[str, tuple[str, str]]:
    """handle -> (display name, source). Handles that share a name merge into one player."""
    contacts = load_contacts()
    names = {norm_handle(k): v for k, v in (cfg.get("names") or {}).items()}
    out = {}
    for row in store.handles():
        h = row["handle"]
        if h == "me":
            out[h] = (cfg.get("me_name") or "Me", "config")
        elif norm_handle(h) in names:
            out[h] = (names[norm_handle(h)], "config")
        elif norm_handle(h) in contacts:
            out[h] = (contacts[norm_handle(h)], "contacts")
        else:
            out[h] = (mask(h), "masked")
    return out


def build(store: Store, cfg: dict) -> dict:
    names = name_map(store, cfg)
    pid = lambda name: "p" + hashlib.sha1(name.encode()).hexdigest()[:8]
    rows = [dict(r) for r in store.results()]

    # A puzzle belongs to the day most people posted it (late-night posts don't shift it).
    votes: dict[tuple, Counter] = defaultdict(Counter)
    for r in rows:
        if r["puzzle_id"]:
            votes[(r["game_key"], r["puzzle_id"])][r["day"]] += 1
    for r in rows:
        if r["puzzle_id"]:
            r["day"] = votes[(r["game_key"], r["puzzle_id"])].most_common(1)[0][0]

    # One result per player per game per puzzle/day: keep their first post.
    seen, results, games, players = set(), [], {}, {}
    for r in rows:  # ordered by ts
        name = names.get(r["handle"], (mask(r["handle"]), "masked"))[0]
        p = pid(name)
        key = (p, r["game_key"], r["puzzle_id"] or r["day"])
        if key in seen or r["score"] is None:
            continue
        seen.add(key)
        players[p] = name
        games[r["game_key"]] = {
            "key": r["game_key"], "name": r["game_name"], "direction": r["direction"],
            "unit": r["unit"], "max": r["max_score"],
        }
        item = {"p": p, "g": r["game_key"], "d": r["day"], "pz": r["puzzle_id"], "s": r["score"],
                "sd": r["score_display"], "f": r["failed"], "t": r["ts"][:16]}
        if cfg.get("export_raw", True):
            item["raw"] = URL_STRIP.sub("", r["raw"] or "").strip()[:500]
        results.append(item)

    return {
        "title": cfg.get("title") or "Game Chat",
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="minutes"),
        "timezone": cfg.get("timezone"),
        "players": sorted(({"id": k, "name": v} for k, v in players.items()), key=lambda x: x["name"].lower()),
        "games": sorted(games.values(), key=lambda g: g["name"].lower()),
        "results": results,
    }


def write(store: Store, cfg: dict, path=None) -> dict:
    data = build(store, cfg)
    path = path or (config.SITE_DIR / "data.json")
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    return data
