from __future__ import annotations

import datetime as dt
import shutil
import subprocess

from . import config


def run(cfg: dict, log=print) -> bool:
    method = (cfg.get("publish") or "none").lower()
    if method == "none":
        return False
    if method == "git":
        root = str(config.ROOT)
        paths = [p for p in ("site/data.json", "rules.json") if (config.ROOT / p).exists()]
        subprocess.run(["git", "-C", root, "add", *paths], check=True)
        diff = subprocess.run(["git", "-C", root, "diff", "--cached", "--quiet"])
        if diff.returncode == 0:
            log("  nothing new to publish")
            return False
        msg = f"sync {dt.datetime.now():%Y-%m-%d %H:%M}"
        subprocess.run(["git", "-C", root, "commit", "-q", "-m", msg], check=True)
        subprocess.run(["git", "-C", root, "push", "-q"], check=True)
        log("  pushed to git — Vercel will redeploy in ~30s")
        return True
    if method == "vercel":
        if not shutil.which("vercel"):
            raise SystemExit("publish is 'vercel' but the Vercel CLI isn't installed (npm i -g vercel).")
        subprocess.run(["vercel", "deploy", "--prod", "--yes"], cwd=str(config.SITE_DIR), check=True)
        return True
    raise SystemExit(f"Unknown publish method {method!r} (use git, vercel or none).")
