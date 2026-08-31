"""layout.py — the wide-screen column engine, the dense density, panel charts.

47 checks across three widths. What it is really guarding is one promise: a
layout you arranged is yours, and the window is not allowed to edit it. Resizing
re-derives the screen from the saved plan; only a drag writes to disk. Every
check below that walks the viewport back and forth exists to hold that line.

It also pins the things that were wrong before the columns went in — a preset
that wrote a key nothing read, and a holdings table that painted out past its
panel border once a column could be a quarter of the window.

Assertions are on what rendered, not on internal state, per the house rule.
"""

import subprocess, sys, os, time, json, signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fixture import preserve
preserve()          # before anything below rewrites the user's settings

# A known starting point: advanced, comfortable, nothing hidden, no first-run
# wizard in the way. The density checks move off comfortable themselves.
json.dump({"mode": "advanced", "accent": "#e87a41", "density": "comfortable",
           "hidden": [], "title": ""}, open("settings.json", "w"))
open(".tutorial_seen", "w").write("done")

srv = subprocess.Popen([sys.executable, "app.py"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        pg = b.new_page(viewport={"width": 2560, "height": 1440}, color_scheme="dark")
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.goto("http://127.0.0.1:7070/", wait_until="domcontentloaded")
        pg.wait_for_timeout(13000)

        COLS = "document.getElementById('layout').dataset.cols"
        PANELS = "[...document.querySelectorAll('#layout .panel')].map(p=>p.dataset.panel)"
        where = lambda pid: pg.evaluate(
            f"document.querySelector('.panel[data-panel=\"{pid}\"]').closest('.zone').dataset.zone")

        print("\n-- COLUMNS BY WIDTH --")
        # The boundaries matter as much as the middles: 1599 and 1600 are the
        # difference between a laptop layout and a monitor one.
        for w, want in [(2560, "4"), (2100, "4"), (2099, "3"), (1920, "3"),
                        (1600, "3"), (1599, "2"), (1440, "2"), (1000, "2"), (760, "1")]:
            pg.set_viewport_size({"width": w, "height": 1000})
            pg.wait_for_timeout(320)
            got = pg.evaluate(COLS)
            ok(f"{w}px -> {want} columns (got {got})", got == want)

        print("\n-- NO PANEL IS LOST OR DUPLICATED AT ANY WIDTH --")
        for w in (2560, 1920, 1440, 760):
            pg.set_viewport_size({"width": w, "height": 1000})
            pg.wait_for_timeout(320)
            ids = pg.evaluate(PANELS)
            ok(f"{w}px: 10 panels, all unique", len(ids) == 10 and len(set(ids)) == 10)

        print("\n-- EVERY COLUMN IS USED --")
        # An empty column on a wide monitor is the thing the whole change exists
        # to remove, so a layout that leaves one is a failure, not a cosmetic.
        for w, n in [(2560, 4), (1920, 3)]:
            pg.set_viewport_size({"width": w, "height": 1000})
            pg.wait_for_timeout(320)
            counts = pg.evaluate("""[...document.querySelectorAll('#layout > .zone')]
                .filter(z=>z.dataset.zone!=='full')
                .map(z=>z.querySelectorAll(':scope > .panel').length)""")
            ok(f"{w}px: {n} non-empty columns {counts}",
               len(counts) == n and all(c > 0 for c in counts))

        print("\n-- A RESIZE NEVER REWRITES THE SAVED LAYOUT --")
        pg.set_viewport_size({"width": 2560, "height": 1440})
        pg.wait_for_timeout(320)
        ok("nothing saved until something is dragged",
           pg.evaluate("localStorage.getItem('windrose-layout3')") is None)
        pg.evaluate("window._layoutSave()")          # what a drop does
        saved = pg.evaluate("localStorage.getItem('windrose-layout3')")
        ok("a drag saves 4 columns", json.loads(saved) and len(json.loads(saved)["cols"]) == 4)
        for w in (1440, 760, 1920, 2560):
            pg.set_viewport_size({"width": w, "height": 1000})
            pg.wait_for_timeout(320)
        ok("still byte-identical after 4 resizes",
           pg.evaluate("localStorage.getItem('windrose-layout3')") == saved)

        print("\n-- A 4-COLUMN LAYOUT OPENS INTACT ON A LAPTOP --")
        pg.set_viewport_size({"width": 1440, "height": 900})
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(9000)
        ids = pg.evaluate(PANELS)
        ok("all 10 panels present at 2 columns", len(ids) == 10 and len(set(ids)) == 10)
        ok("folded to 2 columns", pg.evaluate(COLS) == "2")
        pg.evaluate("localStorage.removeItem('windrose-layout3')")

        print("\n-- A PRESET ACTUALLY MOVES PANELS --")
        # It used to write "windrose-layout2" while the engine read
        # "ledger-layout2", so a chosen preset hid the right panels and then
        # moved none of them. Assert on both halves.
        pg.set_viewport_size({"width": 1920, "height": 1080})
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(9000)
        pg.evaluate("applyPreset('minimal')")
        pg.wait_for_timeout(6000)
        plan = json.loads(pg.evaluate("localStorage.getItem('windrose-layout3')"))
        ok(f"preset wrote the key the engine reads ({plan['cols']})",
           plan["cols"] == [["holdings"], ["benchmark"]])
        vis = pg.evaluate("""[...document.querySelectorAll('#layout .panel')]
            .filter(p=>p.offsetParent!==null).map(p=>p.dataset.panel)""")
        ok(f"only the preset's panels show ({vis})", sorted(vis) == ["benchmark", "holdings"])
        pg.evaluate("localStorage.removeItem('windrose-layout3')")

        print("\n-- WIDE SCREEN DROPS THE MEASURE, SIMPLE MODE KEEPS IT --")
        pg.evaluate("saveSettings({mode:'advanced', hidden:[]})")
        pg.wait_for_timeout(1200)
        pg.reload(wait_until="domcontentloaded")
        pg.wait_for_timeout(9000)
        pg.set_viewport_size({"width": 2560, "height": 1440})
        pg.wait_for_timeout(400)
        w_adv = pg.evaluate("document.querySelector('.wrap').getBoundingClientRect().width")
        ok(f"advanced uses the window ({w_adv:.0f}px of 2560)", w_adv > 2400)
        pg.evaluate("saveSettings({mode:'simple'})")
        pg.wait_for_timeout(700)
        w_sim = pg.evaluate("document.querySelector('.wrap').getBoundingClientRect().width")
        ok(f"simple keeps the 1440 measure ({w_sim:.0f}px)", w_sim <= 1440)
        pg.evaluate("saveSettings({mode:'advanced'})")
        pg.wait_for_timeout(700)

        print("\n-- DENSE IS ONE CLICK, AND IT LANDS --")
        pg.click("#settingsbtn")
        pg.wait_for_timeout(600)
        ok("settings offers three densities",
           pg.evaluate("document.querySelectorAll('#setdens button').length") == 3)
        comf_h2 = pg.evaluate("document.querySelector('.card h2').getBoundingClientRect().height")
        pg.evaluate("document.querySelector('#setdens button[data-d=\"dense\"]').click()")
        pg.wait_for_timeout(900)
        ok("dense applies", pg.evaluate("document.body.dataset.density") == "dense")
        ok("dense persists", json.load(open("settings.json")).get("density") == "dense")
        pg.evaluate("document.getElementById('setclose').click()")
        pg.wait_for_timeout(500)
        ok("panel headers shrank",
           pg.evaluate("document.querySelector('.card h2').getBoundingClientRect().height") < comf_h2)
        # Past 10px the Plex digits stop being readable at arm's length. A few
        # uppercase micro-labels were 9.5px before dense existed and stay that
        # way at every density; nothing dense introduces may go below them.
        smallest = pg.evaluate("""Math.min(...[...document.querySelectorAll('#layout .panel *')]
            .filter(e => e.offsetParent !== null && e.textContent.trim() && !e.children.length)
            .map(e => parseFloat(getComputedStyle(e).fontSize)))""")
        ok(f"nothing below 9.5px (smallest {smallest}px)", smallest >= 9.5)

        print("\n-- HOW MUCH MORE FITS --")
        # Reloaded per density rather than toggled: the sparklines are sized in
        # pixels and a stale one holds the table rows tall, which is a real bug
        # this measurement caught once already.
        heights = {}
        for d in ("comfortable", "compact", "dense"):
            pg.evaluate(f"saveSettings({{density:'{d}'}})")
            pg.wait_for_timeout(900)
            pg.reload(wait_until="domcontentloaded")
            pg.wait_for_timeout(11000)
            heights[d] = pg.evaluate("""(() => ({
                layout: document.getElementById('layout').scrollHeight,
                risk: document.querySelector('[data-panel="risk"]').getBoundingClientRect().height,
                row: document.querySelector('#holdbody tr').getBoundingClientRect().height,
            }))()""")
        c, d = heights["comfortable"], heights["dense"]
        print(f"  layout      comfortable {c['layout']:.0f}px  compact {heights['compact']['layout']:.0f}px  dense {d['layout']:.0f}px")
        print(f"  risk panel  comfortable {c['risk']:.0f}px  dense {d['risk']:.0f}px")
        print(f"  table row   comfortable {c['row']:.0f}px  dense {d['row']:.0f}px")
        ok(f"dense fits {(c['layout']/d['layout']-1)*100:.0f}% more page per screen",
           c["layout"] / d["layout"] >= 1.45)
        ok(f"dense fits {(c['risk']/d['risk']-1)*100:.0f}% more of the risk panel",
           c["risk"] / d["risk"] >= 1.5)
        ok(f"table rows roughly halve ({c['row']:.0f}px -> {d['row']:.0f}px)",
           d["row"] <= c["row"] * 0.6)

        print("\n-- NOTHING PAINTS OUTSIDE ITS PANEL --")
        # A column can now be a quarter of the window. The holdings table has
        # nine nowrap columns and used to run out over the panel border at four
        # columns; it scrolls inside the panel instead.
        pg.set_viewport_size({"width": 2560, "height": 1440})
        for dens in ("comfortable", "dense"):
            pg.evaluate(f"saveSettings({{density:'{dens}'}})")
            pg.wait_for_timeout(900)
            pg.reload(wait_until="domcontentloaded")
            pg.wait_for_timeout(11000)
            over = pg.evaluate("""[...document.querySelectorAll('#layout .panel')]
                .map(p => [p.dataset.panel, p.scrollWidth - p.clientWidth])
                .filter(x => x[1] > 2)""")
            ok(f"{dens} @ 4 columns: no panel overflows its box ({over})", not over)

        print("\n-- CHARTS --")
        painted = pg.evaluate("""[...document.querySelectorAll('canvas.pchart')].map(c => ({
            k: c.dataset.pchart,
            on: c.width > 0 && c.getContext('2d')
                 .getImageData(0, 0, c.width, c.height).data.some(v => v !== 0)
        }))""")
        for cv in painted:
            ok(f"{cv['k']} chart painted", cv["on"])
        ok("four new panel charts", len(painted) == 4)
        ok("holdings sparklines still paint",
           pg.evaluate("document.querySelectorAll('[data-spark]').length") >= 5)

        print("\n-- DRAG A PANEL ACROSS COLUMNS --")
        start = where("alerts")
        pg.evaluate("document.getElementById('layoutbtn').click()")
        pg.wait_for_timeout(400)
        ok("edit mode shows the handles",
           pg.evaluate("getComputedStyle(document.querySelector('.panel .drag')).display") != "none")
        h = pg.query_selector('.panel[data-panel="alerts"] .drag').bounding_box()
        target = pg.evaluate("""(() => {
            const zs = [...document.querySelectorAll('#layout > .zone')]
                .filter(z => z.dataset.zone !== 'full');
            const r = zs[zs.length - 1].getBoundingClientRect();
            return { x: r.x + r.width / 2, y: r.y + 40 };
        })()""")
        pg.mouse.move(h["x"] + h["width"] / 2, h["y"] + h["height"] / 2)
        pg.mouse.down()
        pg.mouse.move(target["x"], target["y"], steps=18)
        pg.wait_for_timeout(250)
        pg.mouse.up()
        pg.wait_for_timeout(700)
        moved = where("alerts")
        ok(f"alerts moved {start} -> {moved}", moved != start and moved == "c3")
        saved = json.loads(pg.evaluate("localStorage.getItem('windrose-layout3')"))
        ok(f"the drag was saved ({saved['cols']})", "alerts" in saved["cols"][3])

        print("\n-- AND IT SURVIVES THE WINDOW --")
        pg.set_viewport_size({"width": 1440, "height": 900})
        pg.wait_for_timeout(500)
        ok("folded to 2 columns", pg.evaluate(COLS) == "2")
        ok("nothing lost", len(pg.evaluate(PANELS)) == 10)
        pg.set_viewport_size({"width": 2560, "height": 1440})
        pg.wait_for_timeout(500)
        ok("back at 4 columns, alerts is where it was left", where("alerts") == "c3")
        ok("plan on disk unchanged by the round trip",
           json.loads(pg.evaluate("localStorage.getItem('windrose-layout3')")) == saved)

        print("\n-- RESET --")
        pg.evaluate("document.getElementById('layoutreset').click()")
        pg.wait_for_timeout(6000)
        ok("reset clears the saved plan",
           pg.evaluate("localStorage.getItem('windrose-layout3')") is None)
        ok("and the default arrangement is back", where("alerts") in ("c0", "c1"))

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
