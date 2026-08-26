import subprocess, sys, os, time, signal, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fixture import preserve
preserve()          # before anything below deletes or rewrites the user's data

try:
    os.remove(".tutorial_seen")
except FileNotFoundError:
    pass
json.dump({"mode": "advanced", "accent": "#e87a41", "density": "comfortable",
           "hidden": [], "title": ""}, open("settings.json", "w"))
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
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1500, "height": 1050}, color_scheme="dark")
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:7070/", wait_until="domcontentloaded")
        pg.wait_for_timeout(12000)

        print("\n-- TOUR --")
        ok("tour appears", pg.evaluate("document.getElementById('tourcard').style.display") == "block")
        steps = pg.evaluate("TOUR.length")
        for _ in range(steps - 1):
            pg.evaluate("""() => {
                const el = document.getElementById('tnext');
                if (!el) throw new Error('required element missing: #tnext');
                el.click();
            }""")
            pg.wait_for_timeout(420)
        ok(f"all {steps} tour stops step through", pg.evaluate("TOUR_I") == steps - 1)
        pg.evaluate("document.getElementById('tnext').click()")
        pg.wait_for_timeout(600)
        ok("tour closes", pg.evaluate("document.getElementById('tourcard').style.display") == "none")

        print("\n-- HOLDINGS --")
        pg.fill("#in-sym", "KO"); pg.fill("#in-shares", "3"); pg.fill("#in-cost", "60")
        pg.click("#addbtn")
        pg.wait_for_function("HOLDINGS.some(h=>h.symbol==='KO')", timeout=25000)
        ok("add a position", True)
        pg.wait_for_timeout(3000)
        # KO stays in the book through the checks below — several of them need at
        # least one holding to exist (per-holding news, the al-sym dropdown, the
        # workbench tabs). It gets deleted in -- CLEANUP -- at the end instead.

        print("\n-- ALERTS / JOURNAL --")
        pg.select_option("#al-sym", index=0)
        pg.fill("#al-val", "999")
        pg.click("#al-add")
        pg.wait_for_timeout(2500)
        ok("alert created", "No alerts yet" not in pg.evaluate("document.getElementById('al-rules').innerText"))
        gone = pg.evaluate("""(()=>{const d=document.querySelector('#al-rules [data-aldel]');
            if(d){d.click();return true;} return false;})()""")
        pg.wait_for_timeout(2000)
        ok("alert removed", gone)
        pg.fill("#j-price", "100"); pg.fill("#j-shares", "1")
        pg.fill("#j-reason", "sweep entry")
        pg.evaluate("document.getElementById('j-add').click()")
        pg.wait_for_timeout(2500)
        ok("journal entry logged", "Nothing logged" not in pg.evaluate("document.getElementById('journal').innerText"))

        print("\n-- WORKBENCH TABS --")
        for tab in ["rdcf", "comps", "stmts", "lbo", "mna", "mc", "stress", "lab"]:
            pg.evaluate(f"mwSwitch('{tab}')")
            try:
                pg.wait_for_function(
                    "!document.getElementById('modelbody').innerText.includes('Computing')", timeout=35000)
            except Exception:
                pass
            pg.wait_for_timeout(350)
            t = pg.evaluate("document.getElementById('modelbody').innerText").strip()
            ok(f"{tab:6} renders ({len(t)}c)", len(t) > 20 and "Computing" not in t)

        print("\n-- CHAIN --")
        pg.locator('[data-panel="chain"]').scroll_into_view_if_needed()
        pg.wait_for_timeout(400)
        nets = pg.evaluate("[...document.getElementById('chainnet').options].map(o=>o.value)")
        bad = []
        for n in nets:
            pg.select_option("#chainnet", n)
            try:
                pg.wait_for_function(f"CH.net==='{n}' && CH.nodes.length>0", timeout=40000)
            except Exception:
                bad.append(n)
            pg.wait_for_timeout(250)
        ok(f"all {len(nets)} networks load" + (f" — failed {bad}" if bad else ""), not bad)

        pg.select_option("#chainnet", "semiconductors")
        pg.wait_for_function("CH.net==='semiconductors' && CH.nodes.length>0", timeout=40000)
        pg.wait_for_timeout(2600)
        pg.evaluate("CH.nodes.forEach(n=>n.pinned=true); chainDraw()")
        for sym in ["AAPL", "TSM"]:
            pg.locator('[data-panel="chain"]').scroll_into_view_if_needed()
            pg.wait_for_timeout(300)
            rel = pg.evaluate("(id)=>{const n=CH.nodes.find(n=>n.id===id);"
                              "return {x:n.x*CH.scale+CH.tx,y:n.y*CH.scale+CH.ty};}", sym)
            pg.locator("#chaincanvas").click(position=rel)
            pg.wait_for_timeout(800)
            tgt = pg.evaluate("CH.sel?CH.sel.ticker:null")
            pg.evaluate("document.getElementById('ccanlz').click()")
            try:
                pg.wait_for_function(
                    "!document.getElementById('modelbody').innerText.includes('Computing')", timeout=35000)
            except Exception:
                pass
            pg.wait_for_timeout(500)
            body = pg.evaluate("document.getElementById('modelbody').innerText")
            ok(f"{tgt}: analyze handoff",
               pg.evaluate("document.getElementById('chaincard').style.display") == "none"
               and pg.evaluate("MW.sym") == tgt and len(body) > 100)

        pg.locator('[data-panel="chain"]').scroll_into_view_if_needed()
        pg.wait_for_timeout(400)
        pg.evaluate("CH.nodes.forEach(n=>n.pinned=true)")
        left0 = pg.evaluate("document.getElementById('chainbook').getBoundingClientRect().left")
        pg.fill("#chainsearch", "NV")
        pg.wait_for_timeout(400)
        left1 = pg.evaluate("document.getElementById('chainbook').getBoundingClientRect().left")
        ok(f"toolbar stable while typing ({round(left0)}->{round(left1)})", abs(left0 - left1) < 2)
        pg.fill("#chainsearch", "")
        pg.wait_for_timeout(250)
        path = pg.evaluate("window._chainPath('ASML','MSFT')")
        ok(f"path tracer {path}", bool(path) and len(path) >= 2)
        pg.evaluate("CH.path=null;CH.pathEdges=null;chainDraw()")
        pg.click("#chainbook")
        pg.wait_for_timeout(700)
        ok("book trace + hop buttons", pg.evaluate("document.querySelectorAll('.hopbtn').length") == 3)
        pg.click("#chainbook")
        pg.wait_for_timeout(300)
        pg.click("#chainlabels")
        pg.wait_for_timeout(400)
        ok("labels toggle", pg.evaluate("CH.labelsOn") is True)
        pg.click("#chainlabels")
        pg.wait_for_timeout(300)
        with pg.expect_download() as dl:
            pg.click("#chainexport")
        ok(f"png export ({dl.value.suggested_filename})", dl.value.suggested_filename.endswith(".png"))

        print("\n-- HEADER --")
        pg.click("#stripedit")
        pg.wait_for_timeout(400)
        pg.fill("#stripin", "NVDA, ^VIX")
        pg.click("#stripsave")
        pg.wait_for_timeout(5000)
        ok("strip saves", pg.evaluate("!document.querySelector('.stripform')")
           and "NVDA" in pg.evaluate("document.getElementById('futures').innerText"))
        pg.evaluate("localStorage.removeItem('ledger-strip')")
        pg.click("#newsbtn")
        pg.wait_for_timeout(3500)
        ok("market wire", pg.evaluate("document.getElementById('newsdd').classList.contains('open')"))
        pg.evaluate("document.getElementById('newsdd').classList.remove('open')")
        pg.evaluate("""() => {
            const el = document.querySelector('[data-news]');
            if (!el) throw new Error('required element missing: [data-news]');
            el.click();
        }""")
        pg.wait_for_timeout(3500)
        ok("per-holding news", pg.evaluate("!!document.querySelector('tr.symnews')"))

        print("\n-- ROUTES --")
        for route, want in [("/api/export.csv", "SYM"), ("/tutorial", "<html"),
                            ("/manifest.webmanifest", "windrose")]:
            try:
                txt = urllib.request.urlopen("http://127.0.0.1:7070" + route, timeout=30).read(600).decode("utf8", "ignore")
                ok(f"{route}", want.lower() in txt.lower())
            except Exception as e:
                ok(f"{route} — {type(e).__name__}", False)

        print("\n-- CLEANUP --")
        pg.evaluate("""() => {
            const el = document.querySelector('[data-del="KO"]');
            if (!el) throw new Error('required element missing: [data-del="KO"]');
            el.click();
        }""")
        pg.wait_for_function("!HOLDINGS.some(h=>h.symbol==='KO')", timeout=25000)
        ok("delete a position", True)
        pg.wait_for_timeout(1000)

        print(f"\n-- page errors: {errs[:3] if errs else 'none'}")
        ok("no page errors", not errs)
        b.close()
finally:
    srv.send_signal(signal.SIGINT)
    time.sleep(1)
    srv.terminate()
    # Wait for it to actually die. A server still running when the fixture
    # restores could write the test's holdings back over the real ones.
    try:
        srv.wait(timeout=10)
    except subprocess.TimeoutExpired:
        srv.kill()

print(f"\n==== {P} passed, {F} failed ====")
if FAILS:
    print("FAILED:", FAILS)
