"""gamechat CLI.

  python3 -m gamechat chats                 list recent chats (pick your group)
  python3 -m gamechat use <id|name>         select the group chat
  python3 -m gamechat sync [--full] [--no-llm] [--no-publish]
  python3 -m gamechat players               who's been seen, and what they're called
  python3 -m gamechat name <handle> <name>  set a display name (same name on two handles = one player)
  python3 -m gamechat games                 games discovered so far
  python3 -m gamechat review                messages that looked like shares but weren't parsed
  python3 -m gamechat alias <from> <to>     merge a game name into another (then sync --full)
"""
from __future__ import annotations

import argparse
import sys

from . import config, export, imessage, publish, sync
from .store import Store


def cmd_chats(a):
    cfg = config.load()
    conn = imessage.open_snapshot(cfg["chat_db"])
    print(f"{'id':>5}  {'members':>7}  {'msgs':>6}  {'last message':16}  name / identifier")
    for c in imessage.list_chats(conn, a.limit):
        if a.groups and c["members"] < 2:
            continue
        label = c["display_name"] or ", ".join(imessage.chat_members(conn, [c["id"]])[:4]) or c["chat_identifier"]
        last = c["last"].astimezone().strftime("%Y-%m-%d %H:%M") if c["last"] else "-"
        print(f"{c['id']:>5}  {c['members']:>7}  {c['messages']:>6}  {last:16}  {label}")


def cmd_use(a):
    cfg = config.load()
    conn = imessage.open_snapshot(cfg["chat_db"])
    ids = imessage.resolve_chat(conn, a.chat)
    if not ids:
        sys.exit(f"No chat matches {a.chat!r}.")
    row = conn.execute("SELECT guid, display_name FROM chat WHERE ROWID=?", (ids[0],)).fetchone()
    # Prefer the display name (survives the group being split across rows); fall back to guid.
    selector = row["display_name"] or row["guid"]
    config.update(chat=selector)
    members = imessage.chat_members(conn, ids)
    print(f"Using chat {selector!r} ({len(members)} members). Next: python3 -m gamechat sync")


def cmd_sync(a):
    cfg = config.load()
    print("Syncing…")
    s = sync.run(full=a.full, use_llm=not a.no_llm, db_path=a.db)
    store = Store(config.STATE_PATH)
    data = export.write(store, cfg)
    print(f"  {s['messages']} new messages → {s['results']} results"
          + (f", {s['llm_calls']} LLM calls" if s["llm_calls"] else ""))
    if s["recovered"]:
        print(f"  recovered {s['recovered']} previously-unparsed shares")
    if s["new_players"]:
        print(f"  new people: {', '.join(s['new_players'])}  (name them: python3 -m gamechat name <handle> <name>)")
    if s["new_games"]:
        print(f"  new games: {', '.join(dict.fromkeys(s['new_games']))}")
    if s["learned_rules"]:
        print(f"  learned parse rules for: {', '.join(dict.fromkeys(s['learned_rules']))}")
    if s["unparsed"]:
        print(f"  {s['unparsed']} share-looking messages still unparsed (python3 -m gamechat review)")
    print(f"  site/data.json: {len(data['results'])} results, {len(data['players'])} players, {len(data['games'])} games")
    if not a.no_publish:
        publish.run(cfg)


def cmd_players(a):
    cfg = config.load()
    store = Store(config.STATE_PATH)
    names = export.name_map(store, cfg)
    print(f"{'handle':28} {'name':22} {'source':9} {'results':>7}  first seen")
    for h in store.handles():
        n, src = names.get(h["handle"], ("?", "?"))
        print(f"{h['handle']:28} {n:22} {src:9} {h['results']:>7}  {h['first_seen'][:10]}")


def cmd_name(a):
    if a.handle == "me":
        config.update(me_name=a.name)
    else:
        config.update(names={a.handle: a.name})
    print(f"{a.handle} → {a.name}. Re-export with: python3 -m gamechat sync")


def cmd_games(a):
    store = Store(config.STATE_PATH)
    print(f"{'key':22} {'name':22} {'results':>7} {'players':>7}  {'first':10}  {'last':10}  parsed by")
    for g in store.games():
        print(f"{g['game_key']:22} {g['game_name']:22} {g['n']:>7} {g['players']:>7}  {g['first']}  {g['last']}  {g['sources']}")


def cmd_review(a):
    store = Store(config.STATE_PATH)
    rows = store.unparsed(a.limit)
    if not rows:
        print("Nothing to review.")
    for r in rows:
        print(f"--- #{r['msg_rowid']} {r['ts'][:16]} {r['handle']}  [{r['note']}]")
        print(r["text"])


def cmd_alias(a):
    config.update(game_aliases={a.src: a.dst})
    print(f"Games named {a.src!r} will be recorded as {a.dst!r}. Rebuild with: python3 -m gamechat sync --full")


def main(argv=None):
    p = argparse.ArgumentParser(prog="gamechat", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("chats"); s.add_argument("--limit", type=int, default=40)
    s.add_argument("--groups", action="store_true", help="only group chats"); s.set_defaults(fn=cmd_chats)
    s = sub.add_parser("use"); s.add_argument("chat"); s.set_defaults(fn=cmd_use)
    s = sub.add_parser("sync")
    s.add_argument("--full", action="store_true", help="re-parse the whole chat history")
    s.add_argument("--no-llm", action="store_true"); s.add_argument("--no-publish", action="store_true")
    s.add_argument("--db", help=argparse.SUPPRESS); s.set_defaults(fn=cmd_sync)
    s = sub.add_parser("players"); s.set_defaults(fn=cmd_players)
    s = sub.add_parser("name"); s.add_argument("handle"); s.add_argument("name"); s.set_defaults(fn=cmd_name)
    s = sub.add_parser("games"); s.set_defaults(fn=cmd_games)
    s = sub.add_parser("review"); s.add_argument("--limit", type=int, default=30); s.set_defaults(fn=cmd_review)
    s = sub.add_parser("alias"); s.add_argument("src"); s.add_argument("dst"); s.set_defaults(fn=cmd_alias)

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except imessage.MessagesAccessError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
