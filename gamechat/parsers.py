"""Turn a chat message into zero or more game results.

Resolution order for each message:
  1. learned / user rules  (rules.json — editable, LLM-written rules land here)
  2. built-in parsers      (well-known games with quirky share formats)
  3. generic heuristic     ("<Name> #<num> <score>/<max>" + an emoji grid or link)
  4. LLM fallback          (handled in sync.py for messages that look like a share)
"""
from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from pathlib import Path

SQUARES = "🟥🟦🟧🟨🟩🟪🟫⬛⬜"
CIRCLES = "🔴🔵🟠🟡🟢🟣🟤⚫⚪"
GAME_SYMBOLS = set(SQUARES + CIRCLES + "💡🔥⭐🎯✅❌🏆🌎🌍🌏🎥🔉🔊")
KEYCAP = "⃣"
URL_RE = re.compile(r"https?://\S+|\b[\w-]+\.(?:com|net|org|io|app|co|gg|xyz|game|fun)\b/?\S*", re.I)


@dataclass
class Result:
    game_key: str
    game_name: str
    score: float | None
    score_display: str
    puzzle_id: str | None = None
    max_score: float | None = None
    failed: bool = False
    direction: str = "lower"   # "lower" or "higher" is better
    unit: str = "guesses"
    source: str = "builtin"


# ---------------------------------------------------------------- helpers

def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "game"


def parse_num(s: str | None) -> float | None:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if s.upper() == "E":   # golf-style "even" (par)
        return 0.0
    if re.fullmatch(r"\d+(:\d{2}){1,2}", s):
        total = 0
        for part in s.split(":"):
            total = total * 60 + int(part)
        return float(total)
    try:
        return float(s)
    except ValueError:
        return None


def fmt_num(v: float | None) -> str:
    if v is None:
        return "–"
    return str(int(v)) if float(v).is_integer() else f"{v:.2f}"


def fmt_seconds(v: float) -> str:
    v = int(round(v))
    h, rem = divmod(v, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def clean_pid(s: str | None) -> str | None:
    if s is None:
        return None
    s = s.strip().replace(",", "")
    return re.sub(r"(?<=\d)\.(?=\d{3}\b)", "", s) or None   # "1.593" (EU thousands) -> 1593


def grid_symbol_count(text: str) -> int:
    return sum(1 for c in text if c in GAME_SYMBOLS) + text.count(KEYCAP)


def has_grid_or_link(text: str) -> bool:
    return grid_symbol_count(text) >= 3 or bool(URL_RE.search(text))


# ---------------------------------------------------------------- built-ins

def p_wordle(t):
    m = re.search(r"\bWordle\s+([\d,.]+)\s+([1-6Xx])/6\*?", t)
    if not m:
        return None
    s = m.group(2).upper()
    failed = s == "X"
    return Result("wordle", "Wordle", 7.0 if failed else float(s), f"{s}/6", clean_pid(m.group(1)), 6, failed)


def p_connections(t):
    m = re.search(r"\bConnections\b\s*Puzzle\s*#\s*([\d,]+)", t, re.I)
    if not m:
        return None
    rows = []
    for line in t[m.end():].splitlines():
        cells = "".join(c for c in line if not c.isspace() and c != "️")
        if len(cells) == 4 and all(c in SQUARES for c in cells):
            rows.append(cells)
    if not rows:
        return None
    solved = sum(1 for r in rows if len(set(r)) == 1)
    mistakes = len(rows) - solved
    failed = solved < 4
    if failed:
        disp = "Failed"
    elif mistakes == 0:
        disp = "Perfect"
    else:
        disp = f"{mistakes} mistake{'s' if mistakes != 1 else ''}"
    return Result("connections", "Connections", float(4 if failed else mistakes), disp,
                  clean_pid(m.group(1)), 4, failed, "lower", "mistakes")


def p_strands(t):
    m = re.search(r"\bStrands\s*#\s*([\d,]+)", t)
    if not m:
        return None
    hints = t.count("💡")
    return Result("strands", "Strands", float(hints), f"{hints} hint{'s' if hints != 1 else ''}",
                  clean_pid(m.group(1)), None, False, "lower", "hints")


def p_mini(t):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+New York Times Mini Crossword in\s+(\d+:\d{2})", t)
    if m:
        pid = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
        secs = parse_num(m.group(4))
    else:
        m = re.search(r"nytimes\.com/badges/games/mini\.html\?d=(\d{4}-\d{2}-\d{2})&t=(\d+)", t)
        if not m:
            return None
        pid, secs = m.group(1), float(m.group(2))
    return Result("nyt-mini", "NYT Mini", secs, fmt_seconds(secs), pid, None, False, "lower", "seconds")


def p_globle(t):
    if not (re.search(r"globle", t, re.I) or ("🌎" in t and "Avg. Guesses" in t)):
        return None
    m = re.search(r"=\s*(\d+)", t)
    if not m:
        return None
    capitals = bool(re.search(r"capitals", t, re.I))
    key, name = ("globle-capitals", "Globle: Capitals") if capitals else ("globle", "Globle")
    pid = None
    d = re.search(r"\b([A-Z][a-z]{2})\.? (\d{1,2}),? (\d{4})", t)
    if d:
        try:
            pid = dt.datetime.strptime(f"{d.group(1)} {d.group(2)} {d.group(3)}", "%b %d %Y").date().isoformat()
        except ValueError:
            pid = None
    n = float(m.group(1))
    return Result(key, name, n, f"{int(n)} guess{'es' if n != 1 else ''}", pid, None, False, "lower", "guesses")


def p_worldle(t):
    m = re.search(r"#Worldle\s*#?\s*([\d,]+)[^\n]*?\b([1-6X])/6", t, re.I)
    if not m:
        return None
    s = m.group(2).upper()
    failed = s == "X"
    return Result("worldle", "Worldle", 7.0 if failed else float(s), f"{s}/6", clean_pid(m.group(1)), 6, failed)


def p_framed(t):
    m = re.search(r"\bFramed\s*#\s*([\d,]+)", t)
    if not m:
        return None
    cells = [c for c in t[m.end():] if c in SQUARES][:6]
    if not cells:
        return None
    failed = "🟩" not in cells
    score = 7.0 if failed else float(cells.index("🟩") + 1)
    return Result("framed", "Framed", score, "X/6" if failed else f"{int(score)}/6",
                  clean_pid(m.group(1)), 6, failed)


def p_quordle(t):
    m = re.search(r"\bDaily Quordle\s*#?\s*(\d+)", t, re.I)
    if not m:
        return None
    boards = re.findall(r"([1-9])️?⃣|(🟥)", t[m.end():])[:4]
    if len(boards) < 4:
        return None
    vals = [10 if red else int(d) for d, red in boards]
    failed = any(red for _, red in boards)
    disp = "-".join("X" if red else d for d, red in boards)
    return Result("quordle", "Quordle", float(sum(vals)), disp, m.group(1), None, failed, "lower", "guesses")


def p_waffle(t):
    m = re.search(r"#waffle\s*(\d+)\s+([0-5X])/5", t, re.I)
    if not m:
        return None
    s = m.group(2).upper()
    failed = s == "X"
    return Result("waffle", "Waffle", 0.0 if failed else float(s), f"{s}/5 ⭐", m.group(1), 5, failed,
                  "higher", "stars")


BUILTINS = [p_wordle, p_connections, p_strands, p_mini, p_globle, p_worldle, p_framed, p_quordle, p_waffle]

# "Costcodle #123 3/6", "#Tradle #965 3/6", "nerdlegame 123 3/6", "Bandle #540 2/6"
GENERIC_RE = re.compile(
    r"^\s*#?(?P<name>[A-Za-z][A-Za-z'’\- ]{1,28}?)[\s:]*(?:#|No\.?|Puzzle|Day|Game)?\s*#?\s*"
    r"(?P<num>\d[\d,]{0,6})\b[^\n/]{0,25}?(?P<score>\d{1,2}|X)\s*/\s*(?P<max>\d{1,2})\b",
    re.M,
)


# ---------------------------------------------------------------- rules

def _compile(p, flags=re.I | re.M):
    return re.compile(p, flags) if p else None


class Rule:
    """A data-driven parser. Fields (rules.json):
      name, key?, detect, puzzle?, score? (regex with ?P<score>/?P<max>), count? (symbol or list of symbols),
      fail? (regex), failed_score?, direction, unit, max_score?, display? ("{score} krill")
    """

    def __init__(self, d: dict):
        self.d = d
        self.name = d["name"]
        self.key = d.get("key") or slug(self.name)
        self.detect = _compile(d["detect"])
        self.puzzle = _compile(d.get("puzzle"))
        self.score = _compile(d.get("score"))
        self.fail = _compile(d.get("fail"))
        self.count = d.get("count")
        self.direction = d.get("direction", "lower")
        self.unit = d.get("unit", "guesses")
        self.max = d.get("max_score")
        self.failed_score = d.get("failed_score")
        self.display = d.get("display")   # e.g. "{score} krill"

    def apply(self, text: str) -> Result | None:
        if not self.detect.search(text):
            return None
        pid = None
        if self.puzzle:
            m = self.puzzle.search(text)
            if m:
                pid = clean_pid(m.group(1) if m.groups() else m.group(0))
        failed = bool(self.fail and self.fail.search(text))
        mx = self.max
        if self.count:
            symbols = [self.count] if isinstance(self.count, str) else self.count
            score = float(sum(text.count(s) for s in symbols))
        elif self.score:
            m = self.score.search(text)
            if not m:
                return None
            gd = m.groupdict()
            raw = gd.get("score") or (m.group(1) if m.groups() else m.group(0))
            if raw and raw.strip().upper() == "X":
                failed, score = True, None
            else:
                score = parse_num(raw)
                if score is None:
                    return None
            if gd.get("max"):
                mx = parse_num(gd["max"])
        else:
            return None
        if failed:
            if self.failed_score is not None:
                score = float(self.failed_score)
            elif self.direction == "lower":
                score = float(mx + 1) if mx else (score if score is not None else 0.0)
            else:
                score = 0.0
        if failed and self.direction == "lower" and mx:
            disp = f"X/{fmt_num(mx)}"
        elif failed:
            disp = "Failed"
        elif self.display:
            disp = self.display.replace("{score}", fmt_num(score)).replace("{max}", fmt_num(mx))
        elif self.unit == "seconds":
            disp = fmt_seconds(score)
        elif mx:
            disp = f"{fmt_num(score)}/{fmt_num(mx)}"
        else:
            disp = f"{fmt_num(score)} {self.unit}" if self.unit not in ("points", "other") else fmt_num(score)
        return Result(self.key, self.name, score, disp, pid, mx, failed, self.direction, self.unit,
                      self.d.get("source", "rule"))


# ---------------------------------------------------------------- parser

class Parser:
    def __init__(self, rules_path: Path, aliases: dict[str, str] | None = None):
        self.rules_path = Path(rules_path)
        self.aliases = {k.lower(): v for k, v in (aliases or {}).items()}
        self.known_keys: set[str] = set()
        self.reload()

    def reload(self):
        self.rules: list[Rule] = []
        if self.rules_path.exists():
            for d in json.loads(self.rules_path.read_text() or "[]"):
                try:
                    self.rules.append(Rule(d))
                except (re.error, KeyError) as e:
                    print(f"  ! skipping bad rule {d.get('name')!r}: {e}")

    def _canon(self, r: Result) -> Result:
        canon = self.aliases.get(r.game_name.lower()) or self.aliases.get(r.game_key)
        if canon:
            r.game_name, r.game_key = canon, slug(canon)
        return r

    def parse(self, text: str) -> list[Result]:
        found: dict[str, Result] = {}
        for rule in self.rules:
            try:
                r = rule.apply(text)
            except Exception:
                r = None
            if r and r.game_key not in found:
                found[r.game_key] = r
        for fn in BUILTINS:
            r = fn(text)
            if r and r.game_key not in found:
                found[r.game_key] = r
        if not found:
            r = self.generic(text)
            if r:
                found[r.game_key] = r
        return [self._canon(r) for r in found.values()]

    def generic(self, text: str) -> Result | None:
        m = GENERIC_RE.search(text)
        if not m:
            return None
        name = m.group("name").strip(" -'’")
        if len(name) < 3:
            return None
        key = slug(self.aliases.get(name.lower(), name))
        # Guard against chatter like "Lunch at 12 then 2/3 of us left": only accept
        # if the message looks like a share, or we've already seen this game.
        if not (has_grid_or_link(text) or key in self.known_keys):
            return None
        s, mx = m.group("score").upper(), parse_num(m.group("max"))
        if s != "X" and parse_num(s) > mx:
            return None
        failed = s == "X"
        score = mx + 1 if failed else parse_num(s)
        return Result(key, name, score, f"{s}/{fmt_num(mx)}", clean_pid(m.group("num")), mx, failed,
                      "lower", "guesses", "generic")

    def learn(self, rule_dict: dict, expected: Result, text: str) -> bool:
        """Validate an LLM-proposed rule against the message it came from; persist if it reproduces."""
        try:
            rule = Rule(rule_dict)
            got = rule.apply(text)
        except Exception:
            return False
        if not got:
            return False
        same_score = (got.score is None and expected.score is None) or (
            got.score is not None and expected.score is not None and abs(got.score - expected.score) < 0.01)
        same_pid = (got.puzzle_id or "") == (expected.puzzle_id or "") or not expected.puzzle_id
        if not (same_score and same_pid and got.failed == expected.failed):
            return False
        rules = json.loads(self.rules_path.read_text() or "[]") if self.rules_path.exists() else []
        rules = [r for r in rules if (r.get("key") or slug(r["name"])) != rule.key]
        rules.append(rule_dict)
        self.rules_path.write_text(json.dumps(rules, indent=2, ensure_ascii=False) + "\n")
        self.reload()
        return True


def looks_like_share(text: str) -> bool:
    """Cheap filter for which unparsed messages are worth sending to the LLM."""
    if len(text) > 800:
        return False
    if grid_symbol_count(text) >= 3:
        return True
    body = URL_RE.sub(" ", text)          # numbers inside a link (dates in article URLs) don't count
    lower = body.lower()
    has_score = bool(re.search(r"#\s?\d{2,}|\b\d{1,3}\s*/\s*\d{1,3}\b|\b\d+:\d{2}\b", body))
    has_word = bool(re.search(r"\b(puzzle|daily|solved|guess(es)?|streak|score|attempts?|tries|#\w+)\b", lower))
    if URL_RE.search(text) and has_score:
        return True
    return has_score and has_word
