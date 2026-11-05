from __future__ import annotations

import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.db"
RULES_PATH = ROOT / "rules.json"
SITE_DIR = ROOT / "site"

DEFAULTS = {
    "chat": None,
    "title": "Game Chat",
    "timezone": "America/New_York",
    "me_name": "Me",
    "names": {},
    "game_aliases": {},
    "llm": {"enabled": True, "model": "claude-haiku-5-5", "api_key_env": "ANTHROPIC_API_KEY"},
    "export_raw": True,
    "publish": "none",
    "chat_db": "~/Library/Messages/chat.db",
}


def load_env():
    """Fill os.environ from .env / .env.local in the repo root. Variables already set in the shell win."""
    for name in (".env.local", ".env"):
        path = ROOT / name
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.removeprefix("export ").partition("=")
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            os.environ.setdefault(key.strip(), val)


def load() -> dict:
    load_env()
    cfg = json.loads(json.dumps(DEFAULTS))
    if CONFIG_PATH.exists():
        user = json.loads(CONFIG_PATH.read_text())
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def save(cfg: dict):
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def update(**changes):
    raw = json.loads(CONFIG_PATH.read_text()) if CONFIG_PATH.exists() else {}
    for k, v in changes.items():
        if isinstance(v, dict):
            raw.setdefault(k, {}).update(v)
        else:
            raw[k] = v
    save(raw)
