import subprocess, sys, os, time, signal, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fixture import preserve
preserve()          # before anything below deletes or rewrites the user's data

# a genuinely fresh user
for f in (".tutorial_seen", "settings.json", "holdings.json", ".update_check"):
    try: os.remove(f)
    except FileNotFoundError: pass
srv = subprocess.Popen([sys.executable, "app.py"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(10)
P = F = 0
def ok(n, c):
    global P, F
    if c: P += 1; print("  PASS " + n)
    else: F += 1; print("  FAIL " + n)

try:
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1400, "height": 1000}, color_scheme="dark")
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:7070/", wait_until="domcontentloaded")
        pg.wait_for_timeout(12000)

        print("-- step 1: mode --")
        ok("wizard opens", pg.evaluate("document.getElementById('welcome').style.display") != "none")
        ok("both modes offered", pg.evaluate("document.querySelectorAll('#welcome [data-pick]').length") == 2)
        ok("progress dots shown", pg.evaluate("document.querySelectorAll('#welcome .wdot').length") == 4)
        pg.screenshot(path="/tmp/windrose-test-wiz1.png")
        pg.evaluate("document.querySelector('#welcome [data-pick=advanced]').click()")
        pg.wait_for_timeout(1500)

        print("-- step 2: keys --")
        txt = pg.evaluate("document.getElementById('welcome').innerText")
        ok("says keys are optional", "don't need any keys" in txt.lower() or "do not need" in txt.lower())
        ok("offers a skip", pg.evaluate("!!document.getElementById('wz-skip')"))
        ok("has both providers", pg.evaluate("document.querySelectorAll('#welcome [data-test]').length") == 2)
        pg.screenshot(path="/tmp/windrose-test-wiz2.png")

        # a wrong key must be caught before saving
        pg.fill("#wz-fh", "obviously-not-a-real-key")
        pg.evaluate("document.querySelector('[data-test=finnhub]').click()")
        pg.wait_for_function("document.getElementById('wz-fh-r').textContent.length > 3", timeout=20000)
        pg.wait_for_timeout(500)
        res = pg.evaluate("document.getElementById('wz-fh-r').textContent")
        cls = pg.evaluate("document.getElementById('wz-fh-r').className")
        ok(f"bad key rejected before saving ({res.strip()[:40]})", "bad" in cls)

        pg.fill("#wz-fh", "")
        pg.evaluate("document.getElementById('wz-skip').click()")
        pg.wait_for_timeout(1500)

        print("-- step 3: portfolio --")
        ok("offers own vs example", pg.evaluate("document.querySelectorAll('#welcome [data-seed]').length") == 2)
        pg.screenshot(path="/tmp/windrose-test-wiz3.png")
        pg.evaluate("document.querySelector('#welcome [data-seed=own]').click()")
        pg.wait_for_timeout(1800)

        print("-- step 4: finish --")
        txt4 = pg.evaluate("document.getElementById('welcome').innerText")
        ok("warns alerts need it running", "only fire while" in txt4.lower())
        ok("states it isn't advice", "advice" in txt4.lower())
        pg.screenshot(path="/tmp/windrose-test-wiz4.png")
        pg.evaluate("document.getElementById('wz-done').click()")
        pg.wait_for_timeout(4000)
        ok("wizard closes", pg.evaluate("document.getElementById('welcome').style.display") == "none")

        print("-- result --")
        hold = json.loads(open("holdings.json").read())
        ok(f"started empty as chosen ({len(hold)} positions)", hold == [])
        ok("mode persisted", json.loads(open("settings.json").read()).get("mode") == "advanced")
        env = open(".env").read() if os.path.exists(".env") else ""
        ok("no bogus key written (.env " + ("absent" if not env else "clean") + ")",
           "obviously-not-a-real-key" not in env)
        ok("no page errors", not errs)
        if errs: print("    ", errs[:2])

        print("-- second launch shows no wizard --")
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(9000)
        ok("wizard does not reappear", pg.evaluate("document.getElementById('welcome').style.display") == "none")
        b.close()
finally:
    srv.send_signal(signal.SIGINT); time.sleep(1); srv.terminate()
    # Wait for it to actually die. A server still running when the fixture
    # restores could write the wizard's empty book over the real one.
    try: srv.wait(timeout=10)
    except subprocess.TimeoutExpired: srv.kill()
print(f"\n==== {P} passed, {F} failed ====")
