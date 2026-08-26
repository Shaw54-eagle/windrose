import subprocess, sys, os, time, signal, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fixture import preserve
preserve()          # before anything below deletes or rewrites the user's data

for f in (".tutorial_seen", "settings.json"):
    try:
        os.remove(f)
    except FileNotFoundError:
        pass
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


VIS = "(id)=>{const p=document.querySelector('[data-panel=\"'+id+'\"]');return !!p && p.offsetParent!==null;}"

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1500, "height": 1050}, color_scheme="dark")
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:7070/", wait_until="domcontentloaded")
        pg.wait_for_timeout(12000)

        print("\n-- FIRST RUN: mode chooser --")
        ok("welcome overlay shows", pg.evaluate("document.getElementById('welcome').style.display") == "flex")
        ok("offers both modes", pg.evaluate("document.querySelectorAll('#welcome [data-pick]').length") == 2)
        ok("tour has NOT started yet", pg.evaluate("document.getElementById('tourcard').style.display") != "block")

        # v5.2 turned the one-click welcome into a four-step wizard:
        # mode -> keys -> portfolio -> finish. Picking a mode advances to step 2
        # rather than closing, so the whole thing has to be walked. Seed the
        # example book, because the risk assertions below need a book to read.
        print("\n-- PICK SIMPLE (walking the four-step wizard) --")
        pg.evaluate("document.querySelector('#welcome [data-pick=\"simple\"]').click()")
        pg.wait_for_timeout(1800)
        saved = json.load(open("settings.json"))
        ok(f"mode persisted at step 1 ({saved.get('mode')})", saved.get("mode") == "simple")
        ok("step 2 asks about keys", pg.evaluate("!!document.getElementById('wz-skip')"))
        pg.evaluate("""() => {
            const el = document.getElementById('wz-skip');
            if (!el) throw new Error('required element missing: #wz-skip');
            el.click();
        }""")
        pg.wait_for_timeout(1800)
        ok("step 3 offers own vs example book",
           pg.evaluate("document.querySelectorAll('#welcome [data-seed]').length") == 2)
        pg.evaluate("""() => {
            const el = document.querySelector('#welcome [data-seed="examples"]');
            if (!el) throw new Error('required element missing: [data-seed=examples]');
            el.click();
        }""")
        pg.wait_for_timeout(2200)
        ok("step 4 is the finish screen", pg.evaluate("!!document.getElementById('wz-done')"))
        pg.evaluate("""() => {
            const el = document.getElementById('wz-done');
            if (!el) throw new Error('required element missing: #wz-done');
            el.click();
        }""")
        pg.wait_for_timeout(3500)
        ok("welcome closed", pg.evaluate("document.getElementById('welcome').style.display") == "none")
        ok("body marked simple", pg.evaluate("document.body.dataset.mode") == "simple")
        ok("example book actually seeded",
           len(json.load(open("holdings.json"))) > 0)
        ok("tour starts once the wizard finishes",
           pg.evaluate("document.getElementById('tourcard').style.display") == "block")
        pg.evaluate("""() => {
            const el = document.getElementById('tskip');
            if (!el) throw new Error('required element missing: #tskip');
            el.click();
        }""")
        pg.wait_for_timeout(1200)

        for pid in ("workbench", "sandbox", "perholding"):
            ok(f"{pid} hidden in simple", pg.evaluate(VIS, pid) is False)
        for pid in ("holdings", "risk", "benchmark", "chain", "alerts", "journal"):
            ok(f"{pid} still shown in simple", pg.evaluate(VIS, pid) is True)

        pg.wait_for_timeout(4000)
        adv_bits = pg.evaluate("""(()=>{const r=document.querySelector('[data-panel="risk"]');
            return [...r.querySelectorAll('.advonly')].filter(e=>e.offsetParent!==null).length;})()""")
        ok(f"risk panel hides its quant blocks ({adv_bits} advanced bits visible)", adv_bits == 0)
        risk_txt = pg.evaluate("document.querySelector('[data-panel=risk]').innerText")
        ok("simple risk still shows value + plain read", "$" in risk_txt and len(risk_txt) > 80)
        ok("no jargon in the simple narrative",
           all(w not in risk_txt for w in ("Beta ", "VaR", "volatility", "Diversification ratio")))
        ok("simple narrative is written in plain English",
           any(w in risk_txt for w in ("separate bets", "bad day", "in step with the market", "riding on")))

        pg.locator('[data-panel="chain"]').scroll_into_view_if_needed()
        pg.wait_for_timeout(500)
        tools = pg.evaluate("""(()=>['chainpath','chainbook','chainlabels','chainexport']
            .filter(id=>{const e=document.getElementById(id);return e && e.offsetParent!==null;}))()""")
        ok(f"advanced map tools hidden in simple ({tools})", tools == [])
        ok("map search still available", pg.evaluate("!!document.getElementById('chainsearch') && document.getElementById('chainsearch').offsetParent!==null"))

        print("\n-- SWITCH TO ADVANCED (header pill) --")
        pg.click("#modepill")
        pg.wait_for_timeout(3500)
        ok("body marked advanced", pg.evaluate("document.body.dataset.mode") == "advanced")
        for pid in ("workbench", "sandbox", "perholding"):
            ok(f"{pid} returns in advanced", pg.evaluate(VIS, pid) is True)
        pg.wait_for_timeout(3000)
        risk_txt2 = pg.evaluate("document.querySelector('[data-panel=risk]').innerText")
        ok("VaR block returns", "1-in-20" in risk_txt2)

        print("\n-- SETTINGS DRAWER --")
        pg.click("#settingsbtn")
        pg.wait_for_timeout(700)
        ok("drawer opens", pg.evaluate("document.getElementById('settings').style.display") == "flex")
        pg.evaluate("document.querySelector('#setaccent .sw[data-hex=\"#4f9ede\"]').click()")
        pg.wait_for_timeout(900)
        accent = pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()")
        ok(f"accent colour applies ({accent})", accent.lower().startswith("#4f9ede"))
        ok("accent persisted", json.load(open("settings.json")).get("accent") == "#4f9ede")
        pg.evaluate("document.querySelector('#setdens button[data-d=\"compact\"]').click()")
        pg.wait_for_timeout(700)
        ok("density applies", pg.evaluate("document.body.dataset.density") == "compact")
        pg.evaluate("document.querySelector('[data-panel-toggle=\"journal\"]').click()")
        pg.wait_for_timeout(900)
        ok("panel can be switched off", pg.evaluate(VIS, "journal") is False)
        ok("hidden panel persisted", "journal" in json.load(open("settings.json")).get("hidden", []))
        pg.evaluate("document.querySelector('[data-panel-toggle=\"journal\"]').click()")
        pg.wait_for_timeout(900)
        ok("and back on", pg.evaluate(VIS, "journal") is True)
        pg.evaluate("document.getElementById('setclose').click()")
        pg.wait_for_timeout(400)
        ok("drawer closes", pg.evaluate("document.getElementById('settings').style.display") == "none")

        print("\n-- KEYBOARD --")
        pg.keyboard.press("?")
        pg.wait_for_timeout(600)
        ok("? opens shortcuts", pg.evaluate("document.getElementById('shortcuts').style.display") == "flex")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)
        ok("Esc closes it", pg.evaluate("document.getElementById('shortcuts').style.display") == "none")
        pg.keyboard.press("s")
        pg.wait_for_timeout(2500)
        ok("s toggles mode", pg.evaluate("document.body.dataset.mode") == "simple")
        pg.keyboard.press("s")
        pg.wait_for_timeout(2500)
        ok("s toggles back", pg.evaluate("document.body.dataset.mode") == "advanced")
        pg.keyboard.press(",")
        pg.wait_for_timeout(600)
        ok(", opens settings", pg.evaluate("document.getElementById('settings').style.display") == "flex")
        pg.keyboard.press("Escape")
        pg.wait_for_timeout(400)

        print("\n-- BRAND --")
        ok("header says WINDROSE", "WINDROSE" in pg.evaluate("document.querySelector('.brand').innerText"))
        ok("icon loads", pg.evaluate("(()=>{const i=document.querySelector('.brand .mark');return i && i.complete && i.naturalWidth>0;})()"))

        print(f"\n-- page errors: {errs[:3] if errs else 'none'}")
        ok("no page errors", not errs)
        b.close()
finally:
    srv.send_signal(signal.SIGINT)
    time.sleep(1)
    srv.terminate()
    # Wait for it to actually die. A server still running when the fixture
    # restores could write the test's settings back over the real ones.
    try:
        srv.wait(timeout=10)
    except subprocess.TimeoutExpired:
        srv.kill()

print(f"\n==== {P} passed, {F} failed ====")
if FAILS:
    print("FAILED:", FAILS)
