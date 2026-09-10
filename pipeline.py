"""
pipeline.py — data-source health, shared by market.py.

Every fetch in market.py used to catch its own exceptions and print a line
that nobody watching the UI would ever see. This module is that print's
replacement: a small in-memory registry of "when did this source last
succeed, and what broke the last time it didn't" — plus a narrow retry
helper for the fetches that run inline during a request. It is not a job
scheduler; there are a fixed, known set of sources and none of them depend
on each other, so a dict is enough.

The Alpaca-auth circuit breaker in market.py (_ALPACA_DISABLED / _AUTH_FAILS)
is unrelated and untouched — it decides whether Alpaca gets called at all.
This module just records what happened when something was called.

What "ok" means here: the source answered usefully. Where an empty answer is
indistinguishable from a dead source — yfinance handing back an empty frame
when it is rate-limiting, Finnhub returning HTTP 429 with a normal-looking
body — market.py records that as a failure, because those are the outages this
panel exists to show and neither of them raises. Where an empty answer is a
real answer, like a news call that simply has no stories, it stays ok.

That leaves a residue worth knowing: a fetch that returns a thin-but-valid
payload (an outlook with no analyst coverage, say) reads ok while its panel
looks bare. The settings copy says so rather than implying the green dot is a
promise about the panel.
"""

from __future__ import annotations
import re, threading, time
import requests

# urllib3 puts the whole request URL — query string included — into the message
# of a connection or timeout error, and every Finnhub call authenticates with
# ?token=<key>. That message used to go to a console nobody reads. It now goes
# into /api/status and onto the screen, so the key has to come out on the way
# in. app.py's key test already does the equivalent, keeping only the exception
# type; CLAUDE.md's "keys are loopback-only" rule is the reason both exist.
_SECRET_PARAM = re.compile(
    r"((?:token|key|secret|api_?key|password|passwd|auth)=)[^&\s'\"()]+",
    re.IGNORECASE)


def _redact(text: str) -> str:
    return _SECRET_PARAM.sub(r"\1<redacted>", text)

# Only a source that refreshes on its own can be "stale", because only for
# those does silence mean something is wrong. Everything else is fetched when
# a panel asks for it: "last ok two hours ago" means nobody opened that panel
# for two hours, which is not a fault and must not be painted as one. An
# earlier version of this table gave every source a threshold and produced a
# column of amber warnings about sources that were working fine.
#
# The Alpaca websocket is deliberately absent. It goes quiet every night and
# all weekend because no trades print, and a healthy connected stream reporting
# "stale" for three quarters of the week is exactly the false signal this panel
# is supposed to remove. Its health is ws_healthy(), not its last tick.
CONTINUOUS = {
    "alpaca-quotes": 30,
    "yfinance-quotes": 30,
}

_STATUS: dict = {}
_LOCK = threading.Lock()


def record_ok(source: str) -> None:
    # The last error is kept after a recovery rather than wiped. "Working now,
    # but it failed four minutes ago" is a different situation from "has never
    # failed", and the difference matters when a source is flapping.
    with _LOCK:
        cur = _STATUS.get(source, {})
        _STATUS[source] = {
            "ok": True, "last_success_ts": time.time(),
            "last_error": cur.get("last_error"),
            "last_error_ts": cur.get("last_error_ts"),
            "fail_streak": 0,
        }


def record_fail(source: str, exc: Exception) -> None:
    with _LOCK:
        cur = _STATUS.get(source, {})
        _STATUS[source] = {
            "ok": False, "last_success_ts": cur.get("last_success_ts"),
            "last_error": _redact(f"{type(exc).__name__}: {exc}"),
            "last_error_ts": time.time(),
            "fail_streak": cur.get("fail_streak", 0) + 1,
        }


def snapshot() -> dict:
    """Per-source status plus a computed `stale` flag, for /api/status."""
    now = time.time()
    with _LOCK:
        rows = {k: dict(v) for k, v in _STATUS.items()}
    for source, row in rows.items():
        threshold = CONTINUOUS.get(source)
        last = row.get("last_success_ts")
        row["stale"] = bool(threshold and (last is None or now - last > threshold))
    return rows


def with_retry(fn, attempts: int = 2, backoff: float = 0.5):
    """Call fn() (a zero-arg callable), retrying network-shaped failures.

    Recording is the caller's job — each fetch function records once, at its
    own level, so a retried call doesn't count as two failures.

    A non-network exception (a bug, a bad response shape) is re-raised
    immediately: it would fail the same way on a second attempt, and the
    delay is paid by whoever is waiting on the page.

    Backoff is short and flat, not exponential. Several callers run inline
    during a request, and a user staring at a blank panel is worse than a
    missing one.
    """
    last_exc = None
    for attempt in range(attempts):
        try:
            return fn()
        except (requests.RequestException, TimeoutError, ConnectionError) as e:
            last_exc = e
            if attempt + 1 < attempts:
                time.sleep(backoff)
    raise last_exc
