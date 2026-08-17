"""
updater.py — is there a newer Windrose than the one running?

Deliberately small and deliberately passive. This module *checks*; it never
installs anything. Applying an update is the launcher's job (a fast-forward
`git pull` before Python starts), so nothing swaps code out from under a
running process.

The check reads APP_VERSION straight from the published app.py on the default
branch. That means no GitHub API token, no release tagging required, and no
rate limits worth worrying about — raw.githubusercontent.com is a CDN.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
CACHE_FILE = BASE / ".update_check"
CACHE_TTL = 6 * 3600          # don't hammer GitHub on every page load

# Point these at your own fork if you publish one.
REPO = "Shaw54-eagle/windrose"
BRANCH = "main"
RAW_URL = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/app.py"
RELEASES_URL = f"https://github.com/{REPO}"


def _parse(v: str) -> tuple:
    """'4.10.1' -> (4, 10, 1). Unparseable pieces sort as 0 rather than crash."""
    out = []
    for part in str(v).strip().split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) + (0,) * (3 - len(out))


def is_newer(remote: str, local: str) -> bool:
    try:
        return _parse(remote) > _parse(local)
    except Exception:
        return False


def _cached() -> dict | None:
    try:
        d = json.loads(CACHE_FILE.read_text())
        if time.time() - d.get("ts", 0) < CACHE_TTL:
            return d
    except Exception:
        pass
    return None


def remote_version(timeout: float = 6.0, force: bool = False) -> str | None:
    """Published version, or None if GitHub can't be reached."""
    if not force:
        hit = _cached()
        if hit:
            return hit.get("remote")
    try:
        req = urllib.request.Request(RAW_URL, headers={"User-Agent": "windrose-update-check"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read(4000).decode("utf8", "ignore")
        m = re.search(r'APP_VERSION\s*=\s*["\']([^"\']+)["\']', text)
        version = m.group(1) if m else None
        try:
            CACHE_FILE.write_text(json.dumps({"ts": time.time(), "remote": version}))
        except Exception:
            pass
        return version
    except Exception:
        return None            # offline, rate-limited, repo renamed — all fine, just skip


def check(local_version: str, force: bool = False) -> dict:
    """What the UI needs to decide whether to nag the user."""
    is_git = (BASE / ".git").exists()
    remote = remote_version(force=force)
    return {
        "current": local_version,
        "latest": remote,
        "update_available": bool(remote and is_newer(remote, local_version)),
        "checked": remote is not None,
        # git clones can update themselves; zip installs have to re-download,
        # because silently unpacking code over a non-git folder is a bad idea.
        "method": "git" if is_git else "manual",
        "url": RELEASES_URL,
    }
