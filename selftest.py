#!/usr/bin/env python3
"""
selftest.py — is this install healthy?

Run it when something looks wrong, or before reporting a bug:

    ./venv/bin/python selftest.py            # offline checks only
    ./venv/bin/python selftest.py --online   # also verifies live data

It prints a report you can paste straight into a GitHub issue. It never prints
your API keys, your positions, your journal, or any file path outside this
folder — only whether things exist and work.

Exit code 0 means everything passed.
"""
from __future__ import annotations

import json
import platform
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
ONLINE = "--online" in sys.argv

PASS, WARN, FAIL = [], [], []


def ok(msg):
    PASS.append(msg)
    print(f"  \u2713 {msg}")


def warn(msg):
    WARN.append(msg)
    print(f"  ! {msg}")


def bad(msg):
    FAIL.append(msg)
    print(f"  \u2717 {msg}")


def section(title):
    print(f"\n{title}")
    print("-" * len(title))


# --------------------------------------------------------------------------- #
section("Environment")
# --------------------------------------------------------------------------- #
v = sys.version_info
print(f"  Python {v.major}.{v.minor}.{v.micro} on {platform.system()} {platform.release()} ({platform.machine()})")
if (v.major, v.minor) >= (3, 10):
    ok("Python version supported")
else:
    bad(f"Python 3.10+ required, found {v.major}.{v.minor}")

in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
if in_venv:
    ok("running inside the project's virtual environment")
else:
    warn("not running in the venv — use ./venv/bin/python selftest.py for a true picture")

if (BASE / ".git").exists():
    ok("installed as a git clone (auto-updates are possible)")
else:
    warn("installed from a zip — auto-update is disabled by design; re-clone to enable it")

# --------------------------------------------------------------------------- #
section("Dependencies")
# --------------------------------------------------------------------------- #
for mod, why in [("flask", "the web server"), ("pandas", "all analysis"),
                 ("numpy", "risk maths"), ("requests", "news and Alpaca"),
                 ("yfinance", "delayed quotes")]:
    try:
        __import__(mod)
        ok(f"{mod} available ({why})")
    except Exception as e:
        bad(f"{mod} missing — {why} will not work ({type(e).__name__})")

for mod, why in [("websocket", "Alpaca live streaming"), ("qrcode", "QR code for phone access"),
                 ("webview", "native app-mode window")]:
    try:
        __import__(mod)
        ok(f"{mod} available ({why})")
    except Exception:
        warn(f"{mod} not installed — {why} unavailable (optional)")

# --------------------------------------------------------------------------- #
section("Configuration")
# --------------------------------------------------------------------------- #
try:
    sys.path.insert(0, str(BASE))
    import app as A
    import market as M
    ok(f"app imports cleanly (version {A.APP_VERSION})")
except Exception as e:
    bad(f"app failed to import: {type(e).__name__}: {e}")
    A = M = None

if (BASE / ".env").exists():
    ok(".env present")
    if M:
        # never print key values — only whether they were accepted
        if M.have_alpaca():
            ok("Alpaca keys detected (live quotes possible)")
        else:
            warn("no usable Alpaca keys — using delayed Yahoo quotes (fine, and the default)")
        if M.have_finnhub():
            ok("Finnhub key detected (news and analyst outlook enabled)")
        else:
            warn("no usable Finnhub key — news panel will be empty (optional)")
        raw = (BASE / ".env").read_text()
        if "your_alpaca_key_here" in raw or "your_finnhub_key_here" in raw:
            warn("your .env still contains placeholder values — harmless now, "
                 "but comment those lines out to keep it tidy")
else:
    warn("no .env — Windrose runs on delayed quotes with no keys, which is fine")

# --------------------------------------------------------------------------- #
section("Your data files")
# --------------------------------------------------------------------------- #
for name, kind in [("holdings.json", list), ("journal.json", list),
                   ("alerts.json", list), ("settings.json", dict)]:
    p = BASE / name
    if not p.exists():
        warn(f"{name} not created yet (it appears on first run)")
        continue
    try:
        data = json.loads(p.read_text())
        if not isinstance(data, kind):
            bad(f"{name} is not a {kind.__name__} — the app may refuse to load it")
        else:
            n = len(data)
            ok(f"{name} is valid JSON ({n} {'entries' if n != 1 else 'entry'})")
    except Exception as e:
        bad(f"{name} is corrupt: {type(e).__name__}. Delete it and it will be recreated.")

# --------------------------------------------------------------------------- #
section("Supply chain map")
# --------------------------------------------------------------------------- #
try:
    chain = json.loads((BASE / "supply_chain.json").read_text())
    nets = chain.get("networks", {})
    total_n = total_e = 0
    problems, orphans = [], []
    all_tickers = set()
    for net_id, net in nets.items():
        ids = [n["id"] for n in net["nodes"]]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            problems.append(f"{net_id}: duplicate node ids {sorted(dupes)}")
        idset = set(ids)
        for e in net["edges"]:
            if e["from"] not in idset or e["to"] not in idset:
                problems.append(f"{net_id}: edge {e['from']} -> {e['to']} points at a missing node")
            if not e.get("rel"):
                problems.append(f"{net_id}: edge {e['from']} -> {e['to']} has no description")
        linked = {e["from"] for e in net["edges"]} | {e["to"] for e in net["edges"]}
        for orphan in sorted(idset - linked):
            orphans.append(f"{net_id}: '{orphan}' has no relationships (it floats unconnected)")
        for n in net["nodes"]:
            t = n.get("ticker", n["id"])
            if t:
                all_tickers.add(t)
        total_n += len(net["nodes"])
        total_e += len(net["edges"])

    print(f"  {len(nets)} industries, {total_n} nodes, {total_e} relationships, "
          f"{len(all_tickers)} distinct tickers")
    for p in problems[:12]:
        bad(p)
    if len(problems) > 12:
        bad(f"...and {len(problems) - 12} more")
    for o in orphans[:8]:
        warn(o)
    if len(orphans) > 8:
        warn(f"...and {len(orphans) - 8} more unconnected nodes")
    if not problems and not orphans:
        ok("every edge resolves, no duplicates, no orphans")
    elif not problems:
        ok("every edge resolves, no duplicates")
except Exception as e:
    bad(f"supply_chain.json unreadable: {type(e).__name__}: {e}")
    all_tickers = set()

# --------------------------------------------------------------------------- #
if ONLINE:
    section("Live data (--online)")
    try:
        q = M._yf_quotes(["AAPL", "MSFT"])
        if q.get("AAPL", {}).get("price"):
            ok(f"delayed quotes working (AAPL ${q['AAPL']['price']})")
        else:
            bad("could not fetch a quote for AAPL — Yahoo may be unreachable or rate-limiting")
    except Exception as e:
        bad(f"quote fetch failed: {type(e).__name__}: {e}")

    try:
        import updater
        r = updater.check(A.APP_VERSION, force=True)
        if not r["checked"]:
            warn("could not reach GitHub to check for updates")
        elif r["update_available"]:
            warn(f"you are on {r['current']}; {r['latest']} is published")
        else:
            ok(f"up to date ({r['current']})")
    except Exception as e:
        warn(f"update check failed: {type(e).__name__}")

    # A ticker that stops resolving usually means the company was acquired,
    # renamed, or delisted — the map is hand-curated and drifts over time.
    if all_tickers:
        sample = sorted(all_tickers)
        try:
            got = M._yf_quotes(sample)
            suspect = [t for t in sample if t not in got]
            # A batch request drops symbols for transient reasons, so re-check
            # each suspect on its own before accusing it. Without this the
            # report cries wolf, and a checker nobody believes is worthless.
            dead = []
            if suspect:
                print(f"  re-checking {len(suspect)} symbol(s) individually…")
                import time as _t
                for t in suspect[:25]:
                    again = M._yf_quotes([t, "AAPL"])
                    if t not in again:
                        dead.append(t)
                    _t.sleep(0.5)
            if not dead:
                ok(f"all {len(sample)} mapped tickers still resolve")
            else:
                warn(f"{len(dead)} mapped ticker(s) do not resolve: {', '.join(dead[:15])}")
                warn("  usually acquired, renamed or delisted — correct the symbol in "
                     "supply_chain.json, or set \"ticker\": null to keep the company "
                     "on the map without a price")
        except Exception as e:
            warn(f"could not verify mapped tickers: {type(e).__name__}")
else:
    print("\n(run with --online to also check live data, updates and mapped tickers)")

# --------------------------------------------------------------------------- #
print("\n" + "=" * 58)
print(f"  {len(PASS)} passed, {len(WARN)} warnings, {len(FAIL)} failures")
if FAIL:
    print("\n  Something is genuinely broken. The failures above are the place")
    print("  to start. Paste this whole report into a GitHub issue if stuck.")
elif WARN:
    print("\n  Nothing is broken. Warnings are optional extras you haven't set up.")
else:
    print("\n  Everything checks out.")
print("=" * 58)
sys.exit(1 if FAIL else 0)
