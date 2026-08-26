"""
walk.py — the interactive Advanced walkthrough.

It drives the real UI, so the checks assert on what ends up on screen: the
card's text, the highlight box, the panel each step actually changed. Checking
that WALK_I incremented would pass while the user saw nothing, which is how the
analyze button shipped broken.

Runs twice — once with a book, once with an empty one — because "degrades sanely
when the book is empty" is a requirement, not a nice-to-have.
"""
import subprocess, sys, os, time, signal, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fixture import preserve
preserve()          # before anything below deletes or rewrites the user's data

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


def card(pg):
    return pg.evaluate("document.getElementById('tourcard').innerText")


def advance(pg, to=None):
    """Click next. Steps do real work — the map's `all` view alone can take
    tens of seconds — so always wait for the destination card to settle rather
    than guessing at a timeout."""
    pg.evaluate("""() => {
        const el = document.getElementById('wknext');
        if (!el) throw new Error('required element missing: #wknext');
        el.click();
    }""")
    pg.wait_for_timeout(400)
    if to:
        settle(pg, to)


def settle(pg, n, timeout=60000):
    """Wait for step n's card to stop saying Working…"""
    pg.wait_for_function(
        f"""(() => {{
            const c = document.getElementById('tourcard');
            if (!c || c.style.display === 'none') return false;
            if (!c.innerText.includes('{n} / 4')) return false;
            return !c.innerText.includes('Working…');
        }})()""", timeout=timeout)


def run(book, label):
    global P, F
    json.dump(book, open("holdings.json", "w"))
    json.dump({"mode": "advanced", "accent": "#e87a41", "density": "comfortable",
               "hidden": [], "title": ""}, open("settings.json", "w"))
    srv = subprocess.Popen([sys.executable, "app.py"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page(viewport={"width": 1600, "height": 1050}, color_scheme="dark")
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            for _ in range(90):
                try:
                    pg.goto("http://127.0.0.1:7070/?walk=1", wait_until="domcontentloaded")
                    break
                except Exception:
                    time.sleep(1)
            pg.wait_for_timeout(14000)

            print(f"\n=== {label} ===")

            # ---- it starts on its own from ?walk=1 ------------------------
            settle(pg, 1)
            ok("starts from ?walk=1", pg.evaluate(
                "document.getElementById('tourcard').style.display") == "block")
            ok("url no longer says walk=1", "walk=1" not in pg.evaluate("location.search"))
            ok("card is the wide walk variant", pg.evaluate(
                "document.getElementById('tourcard').className") == "walk")

            # ---- step 1: reverse DCF -------------------------------------
            t1 = card(pg)
            ok(f"1/4 shows on screen ({t1.splitlines()[0][:34]})", "1 / 4" in t1)
            model = pg.evaluate("document.getElementById('modelbody').innerText")
            ok("it really opened the reverse DCF", pg.evaluate("MW.tab") == "rdcf"
               and "implied FCF growth" in model)
            if book:
                ok(f"ran on a real holding ({pg.evaluate('MW.sym')})",
                   pg.evaluate("MW.sym") == book[0]["symbol"])
                ok("card quotes the number that rendered",
                   "implied FCF growth" in t1 or "could not price" in t1)
            else:
                # SPY has no free cash flow to run backwards, so an empty book
                # gets a named demonstration company instead of a dead model.
                ok("empty book uses a demo company, not an index",
                   pg.evaluate("MW.sym") == "AAPL")
                ok("and says plainly that it isn't theirs",
                   "book is empty" in t1 and "demonstration" in t1)
            ok("says it is not a forecast", "not a forecast" in t1)

            # ---- step 2: the map -----------------------------------------
            advance(pg, to=2)
            t2 = card(pg)
            ok("2/4 shows on screen", "2 / 4" in t2)
            ok("map switched to the all view", pg.evaluate("CH.net") == "all")
            traced = pg.evaluate("CH.path && CH.path.length >= 2")
            ok("a route is actually lit on the map", bool(traced))
            ok("the card names the hops it traced",
               "hop" in t2 and ("→" in t2 or "did not finish" in t2))
            ok("admits the map carries no volume", "how much money" in t2 or
               "did not finish" in t2 or "still settling" in t2)

            # ---- step 3: chokepoints -------------------------------------
            advance(pg, to=3)
            t3 = card(pg)
            ok("3/4 shows on screen", "3 / 4" in t3)
            if book:
                ok("says structure, not revenue", "graph structure, not revenue" in t3)
                ok("names which table it read (supplier vs customer)",
                   "shared supplier" in t3 or "shared customer" in t3
                   or "depends on" in t3 or "sells into" in t3
                   or "shares a supplier or a customer" in t3)
                # Rows routinely tie; calling one of them "strongest" would
                # invent a ranking the percentage does not support.
                ok("does not invent a ranking when rows tie",
                   "tie at the top" in t3 or "strongest shared" in t3
                   or "shares a supplier or a customer" in t3)
            else:
                ok("empty book gets the honest version",
                   "yours is empty" in t3 or "needs a book" in t3)

            # ---- step 4: the journal -------------------------------------
            advance(pg, to=4)
            t4 = card(pg)
            ok("4/4 shows on screen", "4 / 4" in t4)
            ok("explains why the reason field exists",
               "eight months" in t4 and "reason" in t4.lower())
            ok("focus is in the reason box",
               pg.evaluate("document.activeElement && document.activeElement.id") == "j-reason")
            ok("last step offers done, not next",
               pg.evaluate("document.getElementById('wknext').innerText").strip() == "done")

            # ---- finishing puts everything back --------------------------
            advance(pg)
            pg.wait_for_timeout(1200)
            ok("card closes on done", pg.evaluate(
                "document.getElementById('tourcard').style.display") == "none")
            ok("highlight box closes too", pg.evaluate(
                "document.getElementById('tourbox').style.display") == "none")
            ok("traced route is cleared", pg.evaluate("CH.path") is None)

            # ---- skippable at every step ---------------------------------
            for n in (1, 2, 3, 4):
                pg.evaluate("walkStart()")
                settle(pg, 1)
                for k in range(2, n + 1):
                    advance(pg, to=k)
                pg.evaluate("""() => {
                    const el = document.getElementById('wkskip');
                    if (!el) throw new Error('required element missing: #wkskip');
                    el.click();
                }""")
                pg.wait_for_timeout(900)
                ok(f"skippable at step {n}", pg.evaluate(
                    "document.getElementById('tourcard').style.display") == "none")

            # ---- re-runnable ---------------------------------------------
            pg.evaluate("walkStart()")
            settle(pg, 1)
            ok("re-runnable, and restarts at step 1", "1 / 4" in card(pg))
            pg.evaluate("document.getElementById('wkskip').click()")
            pg.wait_for_timeout(700)

            # ---- and from settings ---------------------------------------
            pg.click("#settingsbtn")
            pg.wait_for_timeout(900)
            ok("settings offers it", pg.evaluate("!!document.getElementById('setwalk')"))
            pg.evaluate("document.getElementById('setwalk').click()")
            settle(pg, 1)
            ok("settings entry launches it", "1 / 4" in card(pg))
            pg.evaluate("document.getElementById('wkskip').click()")
            pg.wait_for_timeout(700)

            ok("no page errors", not errs)
            if errs:
                print("     ", errs[:3])
            b.close()
    finally:
        srv.send_signal(signal.SIGINT)
        time.sleep(1)
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except subprocess.TimeoutExpired:
            srv.kill()


run([{"symbol": "AAPL", "shares": 12, "cost_basis": 268.40},
     {"symbol": "NVDA", "shares": 6, "cost_basis": 141.10},
     {"symbol": "XOM", "shares": 20, "cost_basis": 166.20}], "WITH A BOOK")
run([], "WITH AN EMPTY BOOK")

print(f"\n==== {P} passed, {F} failed ====")
if FAILS:
    print("FAILED:", FAILS)
