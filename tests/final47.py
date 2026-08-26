import sys, os, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fixture import preserve
preserve()          # this suite drives an already-running server against real data

from playwright.sync_api import sync_playwright

VIS = ("(id)=>{const p=document.querySelector('[data-panel='+id+']');"
       "if(!p)return false;const r=p.getBoundingClientRect();"
       "return r.width>0 && r.height>0;}")
SOLO_COUNT = "document.querySelectorAll('.solobtn').length"
P = F = 0


def ok(name, cond):
    global P, F
    if cond:
        P += 1
        print("  PASS " + name)
    else:
        F += 1
        print("  FAIL " + name)


with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1500, "height": 1000}, color_scheme="dark")
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.goto("http://127.0.0.1:7070/", wait_until="domcontentloaded")
    pg.wait_for_timeout(12000)
    pg.evaluate("""(()=>{const w=document.getElementById('welcome');
        if(w&&w.style.display!=='none'){const s=w.querySelector('[data-pick=advanced]');
        if(s)s.click();}})()""")
    pg.wait_for_timeout(4500)

    print("-- solo panel --")
    n = pg.evaluate(SOLO_COUNT)
    ok(f"solo button on every panel ({n})", n >= 6)
    pg.evaluate("soloPanel('alerts')")
    pg.wait_for_timeout(900)
    ok("isolates the chosen panel", pg.evaluate(VIS, "alerts") and not pg.evaluate(VIS, "risk"))
    pg.keyboard.press("Escape")
    pg.wait_for_timeout(700)
    ok("Esc restores the dashboard", pg.evaluate(VIS, "risk"))

    print("-- notifications --")
    lbl = pg.evaluate("document.getElementById('al-notif').textContent")
    ok(f"label is OS-neutral ('{lbl}')", "Mac" not in lbl)
    ok("unblock guidance available", len(pg.evaluate("notifUnblockHint()")) > 40)

    print("-- updater --")
    upd = pg.evaluate("fetch('/api/update/check').then(r=>r.json())")
    ok(f"check works (current {upd.get('current')}, latest {upd.get('latest')})",
       upd.get("current") is not None)
    ok("pill hidden while current",
       pg.evaluate("document.getElementById('updpill').style.display") == "none")

    print("-- feedback --")
    diag = pg.evaluate("fetch('/api/diagnostics').then(r=>r.json())")
    ok(f"diagnostics returns {len(diag)} safe fields", "version" in diag and "platform" in diag)
    leaky = [k for k, v in diag.items()
             if any(t in str(v) for t in ("LMT", "RTX", "PLTR", "braxton", "/Users"))]
    ok(f"diagnostics leaks nothing ({leaky or 'clean'})", not leaky)
    pg.click("#settingsbtn")
    pg.wait_for_timeout(1000)
    ok("report button in settings", pg.evaluate("!!document.getElementById('setreport')"))

    # Existence is not the feature. This button shipped broken once because
    # reportProblem was referenced and never defined, and a check that the
    # element was present said nothing about it. Click it and read the URL.
    # window.open is stubbed so the suite never actually reaches github.com.
    pg.evaluate("window.__opened=null; window.open=(u)=>{window.__opened=u; return null;};")
    pg.click("#setreport")
    try:
        pg.wait_for_function("window.__opened !== null", timeout=15000)
    except Exception:
        pass
    opened = pg.evaluate("window.__opened") or ""
    body = urllib.parse.parse_qs(urllib.parse.urlparse(opened).query).get("body", [""])[0]
    ok(f"report opens a prefilled issue ({opened.split('?')[0][:48] or 'nothing opened'})",
       "/issues/new" in opened and diag.get("version", "\0") in body)
    spill = [t for t in ("LMT", "RTX", "PLTR", "braxton", "/Users", "cost_basis") if t in body]
    ok(f"prefilled issue carries no holdings ({spill or 'clean'})", not spill)

    pg.keyboard.press("Escape")
    pg.wait_for_timeout(500)

    ok("no page errors across all of it", not errs)
    if errs:
        print("     ", errs[:2])
    b.close()

print(f"\n==== {P} passed, {F} failed ====")
