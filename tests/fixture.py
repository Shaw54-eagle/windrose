"""
fixture.py — keep a test run from touching the user's real data.

Every suite drives the real app against the real files in the repo root. They
add and delete holdings, write journal entries, create alerts, rewrite settings,
and the wizard suite exercises the screen that saves API keys. Run against a
live install that is exactly as destructive as it sounds: a sweep once deleted
a real KO position out of a real book, and only a manual backup got it back.

preserve() copies every private state file to a temp directory and puts it back
when the process ends — on a clean finish, on an exception, and on Ctrl-C. A
file that did not exist beforehand is removed again rather than left behind, so
a clean install stays clean and the next run still looks like a first run.

    from fixture import preserve
    preserve()

Call it before the fresh-user setup and before starting the server, so what gets
snapshotted is the user's data rather than whatever the app writes on boot.
"""

from __future__ import annotations
import atexit, contextlib, os, shutil, signal, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The private-data set — the same files .gitignore keeps out of the repo,
# because "not ours to commit" and "not ours to destroy" are the same list.
STATE_FILES = (
    "holdings.json",     # positions. This is the one that got eaten.
    "journal.json",
    "alerts.json",
    "settings.json",
    ".env",              # API keys. wizt.py drives the screen that writes this.
    ".tutorial_seen",    # the absence of these is what makes the app believe it
    ".update_check",     # is a fresh install, so the suites delete them on purpose
    ".lan_pin",
)

_restored = False


@contextlib.contextmanager
def _deaf_to_sigint():
    """Ignore Ctrl-C for the duration. A second one landing halfway through the
    restore would leave a half-written book, which is the exact failure this
    module exists to prevent."""
    try:
        prev = signal.signal(signal.SIGINT, signal.SIG_IGN)
    except ValueError:          # not the main thread — nothing to guard
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGINT, prev)


def _exit_on(sig):
    """atexit does not run for SIGTERM. Turn it into an ordinary exit so it does."""
    def bail(signum, _frame):
        raise SystemExit(f"terminated by signal {signum}")
    with contextlib.suppress(ValueError, OSError, AttributeError):
        signal.signal(sig, bail)


def preserve(files=STATE_FILES, root=ROOT):
    """Snapshot the private state files; restore them when this process ends.

    Returns the restore function, so a caller that wants the files back at a
    specific moment can say so. Calling it twice is harmless.
    """
    root = Path(root)
    tmp = Path(tempfile.mkdtemp(prefix="windrose-state-"))
    snapshot: dict[str, Path | None] = {}
    for name in files:
        src = root / name
        if src.exists():
            shutil.copy2(src, tmp / name)
            snapshot[name] = tmp / name
        else:
            snapshot[name] = None        # remember it was absent

    held = sorted(n for n, b in snapshot.items() if b is not None)
    print(f"  [fixture] holding {len(held)} state file(s) safe: {', '.join(held) or 'none'}")

    def restore():
        global _restored
        if _restored:
            return
        _restored = True
        with _deaf_to_sigint():
            for name, backup in snapshot.items():
                dst = root / name
                if backup is None:
                    with contextlib.suppress(FileNotFoundError, IsADirectoryError):
                        os.remove(dst)
                else:
                    shutil.copy2(backup, dst)
            shutil.rmtree(tmp, ignore_errors=True)
        print(f"  [fixture] restored {len(held)} state file(s) — your data is back")

    atexit.register(restore)
    _exit_on(signal.SIGTERM)
    return restore
