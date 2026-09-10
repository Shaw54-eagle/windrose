"""Data-source health: pipeline.py's own logic, /api/status, and the rendered list.

The point of this feature is that a dead source becomes visible instead of
scrolling past in a terminal, so the browser checks read what actually
rendered. Seeding SOURCES and re-rendering is fair game — the assertion is
still on the DOM that came out, not on the variable that went in — but seed
and read happen in ONE evaluate, because pollStatus repaints the list every
5 seconds and will otherwise overwrite the fixture mid-check.

The server-side half matters just as much: the redaction in record_fail is the
only thing standing between a user's Finnhub key and the settings panel.

Named sources.py, not pipeline.py: these suites put tests/ on sys.path[0], so
a test file named after the module it tests shadows that module and imports
itself.
"""

import subprocess, sys, os, time, signal, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# Running a script puts its own directory on the path, not the repo root, and
# this suite checks pipeline.py directly rather than only through the browser.
sys.path.append(os.getcwd())

from fixture import preserve
preserve()          # before anything below rewrites the user's data

json.dump({"mode": "advanced", "accent": "#e87a41", "density": "comfortable",
           "hidden": [], "title": ""}, open("settings.json", "w"))
open(".tutorial_seen", "w").write("1")
srv = subprocess.Popen([sys.executable, "app.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(9)
P = F = 0
FAILS = []


def ok(name, cond):
    global P, F
    if cond:
        P += 1
        print("  PASS " + name)
    else:
        F += 1
        FAILS.append(name)
        print("  FAIL " + name)


try:
    # ---- pipeline.py itself, no browser needed ---------------------------
    print("-- registry --")
    import pipeline as PIPE
    import requests as RQ

    PIPE.record_fail("t-streak", RuntimeError("one"))
    PIPE.record_fail("t-streak", RuntimeError("two"))
    row = PIPE.snapshot()["t-streak"]
    ok("fail_streak accumulates", row["fail_streak"] == 2)
    ok("failure clears ok", row["ok"] is False)
    ok("last error is kept", "two" in (row["last_error"] or ""))
    ok("no success time invented", row["last_success_ts"] is None)

    PIPE.record_ok("t-streak")
    row = PIPE.snapshot()["t-streak"]
    ok("success resets the streak", row["fail_streak"] == 0)
    ok("success sets ok", row["ok"] is True)
    ok("the last error survives recovery", "two" in (row["last_error"] or ""))

    # The leak this test exists for: urllib3 puts the whole URL, query string
    # and all, into a connection error, and Finnhub authenticates by ?token=.
    PIPE.record_fail("t-secret", RuntimeError(
        "Max retries exceeded with url: /api/v1/news?category=general&token=SECRETKEY123"))
    stored = PIPE.snapshot()["t-secret"]["last_error"]
    ok("a token in an error string is redacted", "SECRETKEY123" not in stored)
    ok("redaction leaves the rest readable", "Max retries exceeded" in stored)

    try:
        RQ.get("http://127.0.0.1:1/api/v1/news",
               params={"category": "general", "token": "SECRETKEY123"}, timeout=3)
    except Exception as e:
        PIPE.record_fail("t-real", e)
    real = PIPE.snapshot().get("t-real", {}).get("last_error") or ""
    ok("a real requests exception carries no key", "SECRETKEY123" not in real)
    ok("the real failure is still described", "Error" in real or "error" in real)

    # Staleness applies only to sources that refresh on their own.
    PIPE._STATUS["t-ondemand"] = {"ok": True, "last_success_ts": time.time() - 86400,
                                  "last_error": None, "last_error_ts": None, "fail_streak": 0}
    PIPE._STATUS["t-cont"] = {"ok": True, "last_success_ts": time.time() - 86400,
                              "last_error": None, "last_error_ts": None, "fail_streak": 0}
    snap = PIPE.snapshot()
    ok("an idle on-demand source is not called stale", snap["t-ondemand"]["stale"] is False)
    ok("a continuous source is in the stale table", "alpaca-quotes" in PIPE.CONTINUOUS)
    PIPE._STATUS["alpaca-quotes"] = dict(PIPE._STATUS["t-cont"])
    ok("a silent continuous source is stale", PIPE.snapshot()["alpaca-quotes"]["stale"] is True)

    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 2:
            raise RQ.ConnectionError("boom")
        return "second try"
    ok("with_retry retries a network error", PIPE.with_retry(flaky) == "second try")

    bad = []

    def broken():
        bad.append(1)
        raise ValueError("not a network problem")
    try:
        PIPE.with_retry(broken)
    except ValueError:
        pass
    ok("with_retry does not retry a non-network error", len(bad) == 1)

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1500, "height": 1050}, color_scheme="dark")
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:7070/", wait_until="domcontentloaded")
        pg.wait_for_timeout(12000)

        # ---- the endpoint ------------------------------------------------
        print("-- endpoint --")
        st = pg.evaluate("fetch('/api/status').then(r=>r.json())")
        ok("status carries sources", isinstance(st.get("sources"), dict))
        srcs = st.get("sources") or {}
        ok("at least one source recorded", len(srcs) > 0)

        row = next(iter(srcs.values()), {})
        for field in ("ok", "stale", "fail_streak", "last_success_ts",
                      "last_error", "last_error_ts"):
            ok(f"source row has {field}", field in row)
        ok("a working source reads ok", any(r.get("ok") for r in srcs.values()))
        ok("history was recorded", "yfinance-history" in srcs or "alpaca-quotes" in srcs)
        ok("no source name is missing a label",
           all(pg.evaluate(f"!!SOURCE_LABELS[{json.dumps(k)}]") for k in srcs))

        # ---- the rendered list -------------------------------------------
        print("-- rendered --")
        pg.click("#settingsbtn")
        pg.wait_for_timeout(700)
        ok("settings opened", pg.evaluate("document.getElementById('settings').style.display") == "flex")
        ok("data sources block exists",
           pg.evaluate("!!document.getElementById('setsources')"))

        txt = pg.evaluate("document.getElementById('setsources').innerText")
        ok("block is not empty", len(txt.strip()) > 0)
        ok("a source is named", "Yahoo" in txt or "Alpaca" in txt or "Finnhub" in txt)
        ok("an age rendered", "ago" in txt or "never" in txt or "no success yet" in txt)
        ok("the heading rendered",
           "Data sources" in pg.evaluate("document.getElementById('settings').innerText"))
        ok("the copy says what ok does not mean",
           "not that the answer had anything in it" in
           pg.evaluate("document.getElementById('settings').innerText"))

        # The list must keep repainting while the panel sits open — without
        # that, a source dying under the user's eyes never changes on screen.
        pg.evaluate("document.getElementById('setsources').innerHTML = '<i>SENTINEL</i>'")
        pg.wait_for_timeout(7000)
        ok("the open list repaints on its own",
           "SENTINEL" not in pg.evaluate("document.getElementById('setsources').innerText"))

        # ---- seeded states: seed and read in ONE evaluate, no poll race ---
        print("-- states --")
        d = pg.evaluate("""() => {
          SOURCES = {'finnhub-news': {ok:false, stale:false, fail_streak:3,
                     last_success_ts:null, last_error:'HTTPError: 429 rate limited',
                     last_error_ts: 1}};
          const el = document.getElementById('setsources');
          el.innerHTML = sourceRows();
          return {text: el.innerText, off: !!el.querySelector('.dot.off')};
        }""")
        ok("failing source says failing", "failing" in d["text"])
        ok("failing source names itself", "Finnhub news" in d["text"])
        ok("failing source shows the error", "429" in d["text"])
        ok("failing source shows no success yet", "no success yet" in d["text"])
        ok("failing source gets the off dot", d["off"])

        s = pg.evaluate("""() => {
          SOURCES = {'alpaca-quotes': {ok:true, stale:true, fail_streak:0,
                     last_success_ts: (Date.now()/1000) - 7200,
                     last_error:null, last_error_ts:null}};
          const el = document.getElementById('setsources');
          el.innerHTML = sourceRows();
          return {text: el.innerText, warn: !!el.querySelector('.dot.warn')};
        }""")
        ok("stale source says stale", "stale" in s["text"])
        ok("stale source shows an age in hours", "2h ago" in s["text"])
        ok("stale source gets the warn dot", s["warn"])

        b2 = pg.evaluate("""() => {
          const out = {};
          SOURCES = {'a': {ok:true, stale:false, fail_streak:0,
                     last_success_ts:(Date.now()/1000) - 3580,
                     last_error:null, last_error_ts:null},
                     'b': {ok:true, stale:false, fail_streak:0,
                     last_success_ts:(Date.now()/1000) - 84700,
                     last_error:null, last_error_ts:null}};
          const el = document.getElementById('setsources');
          el.innerHTML = sourceRows();
          out.text = el.innerText;
          return out;
        }""")
        ok("no 60m ago at the hour boundary", "60m ago" not in b2["text"])
        ok("no 24h ago at the day boundary", "24h ago" not in b2["text"])

        # ---- the escaping rule -------------------------------------------
        print("-- escaping --")
        x = pg.evaluate("""() => {
          SOURCES = {'finnhub-news': {ok:false, stale:false, fail_streak:1,
                     last_success_ts:null,
                     last_error:'<img src=x onerror="window.__pwned=1">',
                     last_error_ts: 1}};
          const el = document.getElementById('setsources');
          el.innerHTML = sourceRows();
          return {text: el.innerText, img: !!el.querySelector('img')};
        }""")
        pg.wait_for_timeout(300)
        ok("no script ran from an error string", pg.evaluate("!window.__pwned"))
        ok("no element injected from an error string", not x["img"])
        ok("the error is shown as text", "<img" in x["text"])

        # ---- empty state -------------------------------------------------
        e = pg.evaluate("""() => {
          SOURCES = {};
          const el = document.getElementById('setsources');
          el.innerHTML = sourceRows();
          return el.innerText;
        }""")
        ok("empty state is a sentence, not a blank", "No source has reported yet" in e)
        ok("empty state claims nothing about what ran", "requested" not in e)

        print(f"\n-- page errors: {errs[:3] if errs else 'none'}")
        ok("no page errors", not errs)
        b.close()
finally:
    srv.send_signal(signal.SIGINT)
    time.sleep(1)
    srv.terminate()
    try:
        srv.wait(timeout=10)
    except subprocess.TimeoutExpired:
        srv.kill()

print(f"\n==== {P} passed, {F} failed ====")
if FAILS:
    print("FAILED:", FAILS)
