"""End-to-end test against a fake chat.db with a mocked LLM.

  python3 tests/test_e2e.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import fake_chatdb  # noqa: E402
from gamechat import config, export, llm, sync  # noqa: E402
from gamechat.parsers import Parser  # noqa: E402
from gamechat.store import Store  # noqa: E402

KRILLIAN_REPLY = {
    "is_game_share": True, "game_name": "Krillian", "puzzle_id": None, "score": None,
    "score_display": None, "max_score": None, "failed": False, "direction": "higher", "unit": "points",
    "rule": {"detect": r"Krillian\s*#\d+", "puzzle": r"Krillian\s*#(\d+)", "score": r"(?P<score>\d+)\s*krill\b",
             "count": None, "fail": None, "failed_score": None, "display": "{score} krill"},
}
calls = []


def fake_classify(text, api_key, model, timeout=60):
    calls.append(text)
    if text.startswith("Krillian"):
        import re
        r = dict(KRILLIAN_REPLY)
        r["puzzle_id"] = re.search(r"#(\d+)", text).group(1)
        r["score"] = int(re.search(r"(\d+) krill", text).group(1))
        r["score_display"] = f"{r['score']} krill"
        return r
    return {"is_game_share": False}


def unit_parsers(tmp):
    p = Parser(tmp / "r.json")
    cases = {
        "Wordle 1,593 3/6*\n\n⬛🟨⬛⬛🟩\n🟩🟩🟩🟩🟩": ("wordle", 3, False),
        "Wordle 1593 X/6\n⬛⬛⬛⬛⬛": ("wordle", 7, True),
        "Connections\nPuzzle #523\n🟨🟨🟨🟨\n🟩🟦🟩🟩\n🟩🟩🟩🟩\n🟦🟦🟦🟦\n🟪🟪🟪🟪": ("connections", 1, False),
        "Strands #250\n“Hi”\n💡🔵🔵\n🔵💡🟡": ("strands", 2, False),
        "I solved the 10/28/2026 New York Times Mini Crossword in 1:05!": ("nyt-mini", 65, False),
        "🌎 Oct 28, 2026 🌍\n🔥 3 | Avg. Guesses: 5.2\n🟧🟨🟩 = 4\n\nhttps://globle-game.com": ("globle", 4, False),
        "#Worldle #1012 (28.10.2026) 3/6 (100%)\n🟩🟩🟨⬜⬜": ("worldle", 3, False),
        "Framed #900\n🎥 🟥 🟥 🟩 ⬛ ⬛ ⬛": ("framed", 3, False),
        "Daily Quordle 1200\n6️⃣5️⃣\n🟥8️⃣\nm-w.com/games/quordle/": ("quordle", 29, True),
        "#waffle1234 4/5\n\n🔥 streak: 10": ("waffle", 4, False),
        "#Tradle #965 3/6\n🟩🟩🟩🟨⬜\nhttps://oec.world/en/tradle": ("tradle", 3, False),
    }
    for text, (key, score, failed) in cases.items():
        rs = p.parse(text)
        assert rs and rs[0].game_key == key and rs[0].score == score and rs[0].failed == failed, (text, rs)
    for chatter in ["Lunch at 12 then 2/3 of us left", "lol", "I got 3/6 today ugh"]:
        assert p.parse(chatter) == [], chatter
    two = p.parse("Wordle 1,593 4/6\n🟩🟩🟩🟩🟩\n\nStrands #250\n💡🔵🔵")
    assert {r.game_key for r in two} == {"wordle", "strands"}, two
    print(f"  parsers: {len(cases)} formats + chatter + multi-game message OK")


def main():
    tmp = Path(tempfile.mkdtemp())
    unit_parsers(tmp)
    db = tmp / "chat.db"
    fake_chatdb.build(db)

    config.CONFIG_PATH = tmp / "config.json"
    config.STATE_PATH = tmp / "state.db"
    config.RULES_PATH = tmp / "rules.json"
    config.RULES_PATH.write_text("[]")
    config.save({"chat": "Game Chat", "me_name": "Tyler",
                 "names": {"+12125550101": "Dave", "+12125550102": "Priya", "dana@example.com": "Dana"}})

    import os
    os.environ["ANTHROPIC_API_KEY"] = "test"
    llm.classify = fake_classify
    sync.llm.classify = fake_classify

    s = sync.run(db_path=str(db), log=lambda *a: None)
    print(f"  sync: {s['messages']} msgs → {s['results']} results; llm calls {s['llm_calls']}; "
          f"learned {set(s['learned_rules'])}; unparsed {s['unparsed']}")
    assert s["learned_rules"] == ["Krillian"], s["learned_rules"]
    assert s["llm_calls"] == 1, f"rule should have absorbed later Krillian posts, got {s['llm_calls']} calls"
    rules = json.loads(config.RULES_PATH.read_text())
    assert rules[0]["key"] == "krillian" and rules[0]["direction"] == "higher"

    store = Store(config.STATE_PATH)
    games = {g["game_key"] for g in store.games()}
    assert games == {"wordle", "connections", "strands", "globle", "nyt-mini", "costcodle", "krillian"}, games

    # incremental sync is a no-op
    s2 = sync.run(db_path=str(db), log=lambda *a: None)
    assert s2["messages"] == 0, s2

    # full rebuild reuses the learned rule + cache: zero LLM calls
    n = len(calls)
    s3 = sync.run(full=True, db_path=str(db), log=lambda *a: None)
    assert len(calls) == n and s3["results"] == s["results"], (len(calls), s3)

    cfg = config.load()
    data = export.build(store, cfg)
    names = sorted(p["name"] for p in data["players"])
    print(f"  export: {len(data['results'])} results, players {names}, {len(data['games'])} games")
    assert names == ["Dana", "Dave", "Priya", "Tyler", "•••0199"], names
    blob = json.dumps(data)
    assert "+1212" not in blob and "dana@example" not in blob, "phone numbers/emails leaked into export"
    # dedupe: one result per player/game/puzzle
    keys = [(r["p"], r["g"], r["pz"] or r["d"]) for r in data["results"]]
    assert len(keys) == len(set(keys))
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if out:
        out.write_text(json.dumps(data, ensure_ascii=False))
        print(f"  wrote demo data to {out}")
    print("ALL OK")


if __name__ == "__main__":
    main()
