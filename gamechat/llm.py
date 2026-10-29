"""LLM fallback for game shares no parser recognises (stdlib only, no SDK needed)."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

API_URL = "https://api.anthropic.com/v1/messages"

PROMPT = """You are parsing one message from a group chat where friends post the "share" text from daily phone/web games (Wordle-style results).

<message>
{text}
</message>

Decide whether this message is a game result share. If it is, extract the result AND write a reusable parsing rule so future shares of the same game can be parsed without you.

Reply with ONLY a JSON object, no prose, no code fences:
{{
  "is_game_share": true,
  "game_name": "canonical game name, e.g. Globle",
  "puzzle_id": "puzzle number or date as it appears in the share, or null",
  "score": 3,
  "score_display": "short display, e.g. 3/6 or 1:42",
  "max_score": 6,
  "failed": false,
  "direction": "lower",
  "unit": "guesses",
  "rule": {{
    "detect": "Python regex matching ANY share of this game - anchor on the game's name, URL or hashtag, never on this puzzle's numbers",
    "puzzle": "Python regex with exactly one capture group for the puzzle id, or null",
    "score": "Python regex with a named group (?P<score>...) capturing the score (digits, m:ss, or X for a fail) and optionally (?P<max>...); null if using count",
    "count": "if the score is the number of times a symbol appears (e.g. hint bulbs), that symbol; else null",
    "fail": "Python regex that matches only failed attempts, or null",
    "failed_score": null,
    "display": "display template using {{score}} and {{max}}, e.g. {{score}}/{{max}} or {{score}} krill"
  }}
}}

Field rules:
- score: the single number that best ranks the result. Times are total seconds.
- direction: "lower" if a smaller score is better (guesses, time, mistakes), "higher" otherwise (points, stars, percent).
- unit: one of guesses, seconds, points, mistakes, hints, stars, percent, other.
- failed: true when the player did not solve it.
- Regexes are matched with re.IGNORECASE | re.MULTILINE. Escape special characters. Keep them general enough to match tomorrow's share.

If it is not a game share (chat, a reaction, a link to an article), reply exactly {{"is_game_share": false}}."""


class LLMError(RuntimeError):
    pass


def _extract_json(s: str) -> dict:
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.M).strip()
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j < 0:
        raise LLMError(f"no JSON in model reply: {s[:200]!r}")
    return json.loads(s[i:j + 1])


def classify(text: str, api_key: str, model: str, timeout: int = 60) -> dict:
    payload = {
        "model": model,
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": PROMPT.format(text=text)}],
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode(),
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        raise LLMError(f"API {e.code}: {e.read()[:300]!r}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"network error: {e.reason}") from e
    out = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return _extract_json(out)
