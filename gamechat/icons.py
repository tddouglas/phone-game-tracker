"""Fetch a favicon per game (from games.json urls) into site/icons/ and record the path in games.json.

Hand-edit games.json to set a game's "url" or point "icon" at any image under site/ (it won't be overwritten
unless you pass force).
"""
from __future__ import annotations

import json
import re
import urllib.request
from urllib.parse import urljoin, urlparse

from . import config

GAMES_PATH = config.ROOT / "games.json"
ICON_DIR = config.SITE_DIR / "icons"
UA = {"User-Agent": "Mozilla/5.0 (gamechat icon fetch)"}
LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
EXT = {"image/svg+xml": ".svg", "image/png": ".png", "image/x-icon": ".ico",
       "image/vnd.microsoft.icon": ".ico", "image/jpeg": ".jpg", "image/webp": ".webp"}


def load() -> dict:
    return json.loads(GAMES_PATH.read_text()) if GAMES_PATH.exists() else {}


def _get(url: str, limit: int = 2_000_000):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=10) as r:
        return r.read(limit), (r.headers.get_content_type() or "").lower(), r.geturl()


def _candidates(url: str) -> list[str]:
    """Icon URLs for a page, best first: touch icon, svg, sized png, then /favicon.ico."""
    html, _, final = _get(url)
    ranked = []
    for tag in LINK_RE.findall(html.decode("utf-8", "ignore")):
        rel = re.search(r'rel=["\']([^"\']*)', tag, re.I)
        href = re.search(r'href=["\']([^"\']*)', tag, re.I)
        if not rel or not href or "icon" not in rel.group(1).lower() or href.group(1).startswith("data:"):
            continue
        h = href.group(1)
        score = 0 if "apple" in rel.group(1).lower() else 1 if h.split("?")[0].endswith(".svg") else 2
        ranked.append((score, urljoin(final, h)))
    p = urlparse(final)
    ranked.append((3, f"{p.scheme}://{p.netloc}/favicon.ico"))
    return [u for _, u in sorted(ranked, key=lambda x: x[0])]


def fetch(key: str, url: str) -> str | None:
    for cand in _candidates(url):
        try:
            body, ctype, _ = _get(cand)
        except Exception:
            continue
        ext = EXT.get(ctype) or ("." + cand.split("?")[0].rsplit(".", 1)[-1].lower())
        if ext not in EXT.values() or len(body) < 50 or body[:1] == b"<" and ext != ".svg":
            continue
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        for old in ICON_DIR.glob(f"{key}.*"):
            old.unlink()
        (ICON_DIR / f"{key}{ext}").write_bytes(body)
        return f"icons/{key}{ext}"
    return None


def run(force: bool = False, log=print) -> dict:
    meta = load()
    for key, g in meta.items():
        if not g.get("url") or (g.get("icon") and (config.SITE_DIR / g["icon"]).exists() and not force):
            continue
        try:
            icon = fetch(key, g["url"])
        except Exception as e:
            log(f"  ! {key}: {e}")
            continue
        log(f"  {key}: {icon or 'no icon found'}")
        if icon:
            g["icon"] = icon
    GAMES_PATH.write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    return meta
