# Tests

Browser-driven checks that exercise the real app, not mocks. They start a
server, drive Chromium against it, and assert on what a user would actually
see — several bugs in this repo shipped because an earlier test asserted on
internal state instead.

    pip install playwright && playwright install chromium

    python3 tests/sweep3.py    # 31 checks: every panel, workbench tab, network
    python3 tests/v4test.py    # 47 checks: modes, the setup wizard, settings, accents
    python3 tests/wizt.py      # 16 checks: the setup wizard, both branches
    python3 tests/final47.py   # 13 checks: solo, notifications, updater, feedback
    python3 tests/walk.py      # 62 checks: the advanced walkthrough, book and no book

`final47.py` drives a server you already have running; the other three start
their own on port 7070.

## They are safe to run against a live install

The suites still mutate real files while they run — they add and delete
holdings, write journal entries, create alerts, rewrite settings, and the wizard
suite drives the screen that saves API keys. What changed is that they put
everything back.

`fixture.py` snapshots the private state files to a temp directory before a run
and restores them when the process ends:

    holdings.json  journal.json  alerts.json  settings.json
    .env  .tutorial_seen  .update_check  .lan_pin

That is the same list `.gitignore` keeps out of the repo, on the principle that
"not ours to commit" and "not ours to destroy" are the same set. A file that was
absent beforehand is deleted again rather than left behind, so a clean install
stays clean and the next run still looks like a first run.

Restore happens on a clean finish, on an exception, on Ctrl-C, and on SIGTERM.
Ctrl-C is ignored for the few milliseconds the restore itself takes, because a
second one landing halfway through would leave a half-written book — which is
the exact failure this exists to prevent.

This is not theoretical. A sweep run deleted a real KO position out of a real
book, and only a manual backup got it back. That is why the fixture exists.

**Where it still lies to you:** `kill -9` and a power cut cannot be intercepted,
so neither can be restored from. In that one case the snapshot is left behind in
your temp directory as `windrose-state-*` — copy the files back by hand. Every
other exit path cleans the snapshot up after restoring.

Lessons that are baked into these, worth keeping:

- Assert on rendered output, never on a variable. `MW.sym` being correct while
  the panel showed nothing is exactly how the analyze button shipped broken.
- Click canvas nodes with `locator.click(position=...)`, not absolute mouse
  coordinates — the canvas is usually below the fold.
- Pin graph nodes (`CH.nodes.forEach(n => n.pinned = true)`) before clicking, or
  physics drifts them out from under the click.
- Re-verify a failure individually before reporting it. A batch quote request
  drops symbols for transient reasons and the ticker checker cried wolf.
- A suite that leaves the book in a different state than it found it is broken,
  even if every check passed. `sweep3.py` added KO and deleted it, which emptied
  a real book and also broke the checks after it that needed a holding to exist.
  Add fixtures at the start, take them away at the end, and call `preserve()`
  before the first line that touches disk.
- Wait for the server subprocess to actually exit before the fixture restores.
  `terminate()` does not block, and a server still running can write the test's
  holdings back over the real ones after they have been put back.
