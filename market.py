"""
market.py — all outside-world data lives here.

Sources, and why each:
  • Live prices   -> Alpaca snapshots (IEX feed), polled on a background thread.
                     Falls back to yfinance if Alpaca keys are missing.
  • History       -> yfinance daily bars (feeds analysis.py). Cached ~10 min.
  • Futures/index -> yfinance (ES/NQ/YM/CL/GC/VIX). Delayed; clearly flagged.
  • News          -> Finnhub (general + per-holding). Cached ~3 min.
  • Outlook       -> yfinance analyst targets/ratings/earnings. Cached ~30 min.

Nothing here can crash the app: every fetch is wrapped, and a dead source just
returns empty so the rest of the dashboard keeps working.
"""

from __future__ import annotations
import os, time, threading, datetime as dt
import requests
import pandas as pd

try:
    import yfinance as yf
except Exception:
    yf = None

ALPACA_DATA = "https://data.alpaca.markets/v2"

# .env.example ships with placeholder values, and some launchers copy it
# verbatim. A placeholder must read as "no key" — otherwise the app believes
# it has credentials and hammers the API with 401s forever.
_PLACEHOLDERS = {
    "", "your_alpaca_key_here", "your_alpaca_secret_here", "your_finnhub_key_here",
    "your_key_here", "changeme", "xxx", "none", "null", "todo",
}


def _clean(name: str) -> str:
    v = (os.getenv(name, "") or "").strip().strip('"').strip("'")
    if v.lower() in _PLACEHOLDERS or v.lower().startswith("your_"):
        return ""
    return v


def _alpaca_key():    return _clean("ALPACA_KEY")
def _alpaca_secret(): return _clean("ALPACA_SECRET")
def _finnhub_key():   return _clean("FINNHUB_KEY")

FUTURES = [
    ("ES=F", "S&P 500", "ES"),
    ("NQ=F", "Nasdaq 100", "NQ"),
    ("YM=F", "Dow", "YM"),
    ("CL=F", "Crude Oil", "CL"),
    ("GC=F", "Gold", "GC"),
    ("^VIX", "Volatility", "VIX"),
]

# ---- shared state ----
_LIVE: dict = {}            # symbol -> {price, change_abs, change_pct, prev_close, src, ts}
_LIVE_LOCK = threading.Lock()
_LIVE_SRC = "none"
_cache: dict = {}          # key -> (expires_at, value)


def _cache_get(key):
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _cache_put(key, value, ttl):
    _cache[key] = (time.time() + ttl, value)


_ALPACA_DISABLED = False     # flipped after repeated auth rejections
_AUTH_FAILS = 0


def have_alpaca() -> bool:
    if _ALPACA_DISABLED:
        return False
    return bool(_alpaca_key() and _alpaca_secret())


def have_finnhub() -> bool:
    return bool(_finnhub_key())


# --------------------------------------------------------------------------- #
#  LIVE PRICES — background poller
# --------------------------------------------------------------------------- #

def _alpaca_snapshots(symbols: list[str]) -> dict:
    """One call returns latest trade + daily bar + prev daily bar per symbol."""
    if not symbols or not have_alpaca():
        return {}
    headers = {"APCA-API-KEY-ID": _alpaca_key(), "APCA-API-SECRET-KEY": _alpaca_secret()}
    r = requests.get(f"{ALPACA_DATA}/stocks/snapshots",
                     params={"symbols": ",".join(symbols), "feed": "iex"},
                     headers=headers, timeout=8)
    r.raise_for_status()
    data = r.json()
    out = {}
    for sym, snap in data.items():
        trade = (snap or {}).get("latestTrade") or {}
        daily = (snap or {}).get("dailyBar") or {}
        prev = (snap or {}).get("prevDailyBar") or {}
        price = trade.get("p") or daily.get("c")
        prev_close = prev.get("c") or daily.get("o")
        if price is None:
            continue
        change_abs = (price - prev_close) if prev_close else None
        change_pct = (change_abs / prev_close * 100) if prev_close else None
        out[sym] = {
            "price": round(float(price), 2),
            "prev_close": round(float(prev_close), 2) if prev_close else None,
            "change_abs": round(change_abs, 2) if change_abs is not None else None,
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "src": "alpaca-iex", "ts": time.time(),
        }
    return out


def _yf_quotes(symbols: list[str]) -> dict:
    """Delayed quotes for a list of symbols.

    One batched download instead of a request per symbol — the supply-chain
    map asks for ~300 at once and serial calls took well over a minute.
    Falls back to the per-symbol path if the batch comes back empty.
    """
    if not symbols or yf is None:
        return {}
    out = {}
    if len(symbols) > 4:
        try:
            raw = yf.download(symbols, period="5d", interval="1d", progress=False,
                              auto_adjust=False, group_by="ticker", threads=True)
            lvl0 = set(raw.columns.get_level_values(0)) if hasattr(raw.columns, "levels") else set()
            for sym in symbols:
                try:
                    if sym not in lvl0:
                        continue
                    ser = raw[sym]["Close"].dropna()
                    if len(ser) < 1:
                        continue
                    price = float(ser.iloc[-1])
                    prev = float(ser.iloc[-2]) if len(ser) >= 2 else None
                    ca = (price - prev) if prev else None
                    cp = (ca / prev * 100) if prev else None
                    out[sym] = {
                        "price": round(price, 2),
                        "prev_close": round(prev, 2) if prev else None,
                        "change_abs": round(ca, 2) if ca is not None else None,
                        "change_pct": round(cp, 2) if cp is not None else None,
                        "src": "yfinance-delayed", "ts": time.time(),
                    }
                except Exception:
                    continue
        except Exception as e:
            print(f"[chain quotes batch] {type(e).__name__}: {e}")
        if out:
            return out

    for sym in symbols:
        try:
            fi = yf.Ticker(sym).fast_info
            price = fi.get("last_price") or fi.get("lastPrice")
            prev = fi.get("previous_close") or fi.get("previousClose")
            if price is None:
                continue
            ca = (price - prev) if prev else None
            cp = (ca / prev * 100) if prev else None
            out[sym] = {
                "price": round(float(price), 2),
                "prev_close": round(float(prev), 2) if prev else None,
                "change_abs": round(ca, 2) if ca is not None else None,
                "change_pct": round(cp, 2) if cp is not None else None,
                "src": "yfinance-delayed", "ts": time.time(),
            }
        except Exception:
            continue
    return out


def start_live_poller(get_symbols, interval: float = 2.0):
    """Spawn one daemon thread that refreshes _LIVE every `interval` seconds.
    `get_symbols` is a callable returning the current symbol list (so newly
    added holdings get picked up automatically)."""
    def loop():
        global _LIVE_SRC
        while True:
            try:
                symbols = sorted(set(get_symbols()))
                if symbols:
                    snap = _alpaca_snapshots(symbols) if have_alpaca() else {}
                    if snap:
                        _LIVE_SRC = "alpaca-ws" if ws_healthy() else "alpaca-iex"
                    else:
                        snap = _yf_quotes(symbols)
                        _LIVE_SRC = "yfinance-delayed" if snap else "none"
                    if snap:
                        with _LIVE_LOCK:
                            for s, q in snap.items():
                                cur = _LIVE.get(s)
                                # don't stomp a fresher websocket tick with a poll
                                if cur and cur.get("src") == "alpaca-ws" and ws_healthy():
                                    cur["prev_close"] = q.get("prev_close") or cur.get("prev_close")
                                else:
                                    _LIVE[s] = q
                        _bump()
            except Exception as e:
                # Credentials that exist but don't work (wrong, revoked, or a
                # data plan that doesn't cover this feed) would otherwise log a
                # 401 every couple of seconds for the life of the process.
                # Say it once, fall back to delayed quotes, stop asking.
                global _ALPACA_DISABLED, _AUTH_FAILS
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (401, 403):
                    _AUTH_FAILS += 1
                    if _AUTH_FAILS >= 3 and not _ALPACA_DISABLED:
                        _ALPACA_DISABLED = True
                        print("\n  [alpaca] Your API keys were rejected (HTTP "
                              f"{status}). Falling back to delayed Yahoo quotes.")
                        print("  [alpaca] Fix or remove ALPACA_KEY / ALPACA_SECRET in .env, "
                              "then restart. Everything else keeps working.\n")
                    elif _AUTH_FAILS < 3:
                        print(f"[live poller] auth rejected ({status}) — retrying")
                else:
                    print(f"[live poller] {type(e).__name__}: {e}")
            # streaming healthy -> poll is just the safety net + prev_close refresh
            time.sleep(15.0 if ws_healthy() else interval)

    t = threading.Thread(target=loop, daemon=True, name="live-poller")
    t.start()
    return t


def get_live() -> dict:
    with _LIVE_LOCK:
        src = "alpaca-ws" if ws_healthy() else _LIVE_SRC
        return {"src": src, "quotes": dict(_LIVE), "ts": time.time(), "v": LIVE_VERSION}


# --------------------------------------------------------------------------- #
#  HISTORY  (feeds analysis.py)
# --------------------------------------------------------------------------- #

def get_history(symbols: list[str], bench: str = "SPY", period: str = "1y") -> dict:
    """Returns {'close': DataFrame(cols=symbols+bench), 'frames': {sym: OHLCV df}}.
    Cached 10 minutes — analysis only needs daily bars, no point hammering."""
    want = sorted(set(list(symbols) + [bench]))
    key = "hist:" + ",".join(want) + ":" + period
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if yf is None or not want:
        return {"close": pd.DataFrame(), "frames": {}}
    try:
        raw = yf.download(want, period=period, interval="1d",
                          progress=False, auto_adjust=True, group_by="column")
        if raw.empty:
            return {"close": pd.DataFrame(), "frames": {}}
        # Normalise to MultiIndex (field, symbol) even for a single symbol
        if not isinstance(raw.columns, pd.MultiIndex):
            raw.columns = pd.MultiIndex.from_product([raw.columns, [want[0]]])
        close = raw["Close"].copy()
        frames = {}
        for s in want:
            try:
                frames[s] = pd.DataFrame({
                    "Close": raw["Close"][s], "High": raw["High"][s],
                    "Low": raw["Low"][s], "Volume": raw["Volume"][s],
                }).dropna()
            except Exception:
                pass
        result = {"close": close, "frames": frames}
        _cache_put(key, result, ttl=600)
        return result
    except Exception as e:
        print(f"[history] {type(e).__name__}: {e}")
        return {"close": pd.DataFrame(), "frames": {}}


# --------------------------------------------------------------------------- #
#  FUTURES / INDEX STRIP
# --------------------------------------------------------------------------- #

def get_futures() -> list[dict]:
    key = "futures"
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if yf is None:
        return []
    out = []
    try:
        syms = [s for s, _, _ in FUTURES]
        raw = yf.download(syms, period="5d", interval="1d",
                          progress=False, auto_adjust=False, group_by="ticker")
        for sym, name, short in FUTURES:
            try:
                df = raw[sym].dropna() if sym in raw.columns.get_level_values(0) else None
                if df is None or len(df) < 2:
                    continue
                last = float(df["Close"].iloc[-1])
                prev = float(df["Close"].iloc[-2])
                cp = (last - prev) / prev * 100 if prev else None
                out.append({
                    "symbol": sym, "name": name, "short": short,
                    "price": round(last, 2),
                    "change_pct": round(cp, 2) if cp is not None else None,
                    "is_index": sym.startswith("^"),
                    "delayed": True,
                })
            except Exception:
                continue
    except Exception as e:
        print(f"[futures] {type(e).__name__}: {e}")
    _cache_put(key, out, ttl=20)
    return out


# --------------------------------------------------------------------------- #
#  NEWS  (Finnhub)
# --------------------------------------------------------------------------- #

def get_news(symbols: list[str], limit: int = 25) -> list[dict]:
    key = "news:" + ",".join(sorted(set(symbols)))
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if not have_finnhub():
        return [{"_notice": "Add a free FINNHUB_KEY to .env to load market news."}]
    items, seen = [], set()
    try:
        # General market news
        r = requests.get("https://finnhub.io/api/v1/news",
                         params={"category": "general", "token": _finnhub_key()}, timeout=8)
        for n in (r.json() if r.ok else [])[:15]:
            h = n.get("headline", "")
            if h and h not in seen:
                seen.add(h)
                items.append(_news_row(n, "Market"))
        # Per-holding news (last 7 days)
        today = dt.date.today()
        frm = (today - dt.timedelta(days=7)).isoformat()
        for sym in symbols[:6]:
            r = requests.get("https://finnhub.io/api/v1/company-news",
                             params={"symbol": sym, "from": frm, "to": today.isoformat(),
                                     "token": _finnhub_key()}, timeout=8)
            for n in (r.json() if r.ok else [])[:6]:
                h = n.get("headline", "")
                if h and h not in seen:
                    seen.add(h)
                    items.append(_news_row(n, sym))
    except Exception as e:
        print(f"[news] {type(e).__name__}: {e}")
    items.sort(key=lambda x: x.get("ts", 0), reverse=True)
    items = items[:limit]
    _cache_put(key, items, ttl=180)
    return items


def _news_row(n: dict, tag: str) -> dict:
    ts = n.get("datetime", 0)
    return {
        "headline": n.get("headline", ""),
        "source": n.get("source", ""),
        "url": n.get("url", ""),
        "tag": tag,
        "ts": ts,
        "when": dt.datetime.fromtimestamp(ts).strftime("%b %d, %I:%M %p") if ts else "",
    }


# --------------------------------------------------------------------------- #
#  FORWARD OUTLOOK  (analyst consensus — opinion, not prediction)
# --------------------------------------------------------------------------- #

def get_outlook(symbol: str) -> dict:
    key = "outlook:" + symbol
    cached = _cache_get(key)
    if cached is not None:
        return cached
    out = {"symbol": symbol, "ok": False}
    if yf is None:
        return out
    try:
        t = yf.Ticker(symbol)
        info = {}
        try:
            info = t.get_info()
        except Exception:
            info = getattr(t, "info", {}) or {}
        current = info.get("currentPrice") or info.get("regularMarketPrice")
        mean = info.get("targetMeanPrice")
        high = info.get("targetHighPrice")
        low = info.get("targetLowPrice")
        n = info.get("numberOfAnalystOpinions")
        rating = info.get("recommendationKey")
        implied = ((mean - current) / current * 100) if (mean and current) else None

        # next earnings date (best-effort)
        next_earn = None
        try:
            cal = t.calendar
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if ed:
                    next_earn = str(ed[0] if isinstance(ed, (list, tuple)) else ed)
            elif hasattr(cal, "loc") and "Earnings Date" in getattr(cal, "index", []):
                next_earn = str(cal.loc["Earnings Date"][0])
        except Exception:
            pass

        out = {
            "symbol": symbol, "ok": bool(mean or rating),
            "current": round(float(current), 2) if current else None,
            "target_mean": round(float(mean), 2) if mean else None,
            "target_high": round(float(high), 2) if high else None,
            "target_low": round(float(low), 2) if low else None,
            "implied_pct": round(implied, 1) if implied is not None else None,
            "rating": (rating or "").replace("_", " ") or None,
            "n_analysts": int(n) if n else None,
            "next_earnings": next_earn,
        }
        _cache_put(key, out, ttl=1800)
    except Exception as e:
        print(f"[outlook {symbol}] {type(e).__name__}: {e}")
    return out


# --------------------------------------------------------------------------- #
#  FUNDAMENTALS  (feeds models.py — cached 1h)
# --------------------------------------------------------------------------- #

def get_fundamentals(symbol: str) -> dict:
    key = "fund:" + symbol
    cached = _cache_get(key)
    if cached is not None:
        return cached
    out = {"symbol": symbol, "ok": False}
    if yf is None:
        return out
    try:
        t = yf.Ticker(symbol)
        info = {}
        try:
            info = t.get_info()
        except Exception:
            info = getattr(t, "info", {}) or {}

        cash = info.get("totalCash") or 0
        debt = info.get("totalDebt") or 0
        fcf = info.get("freeCashflow")
        cfo = info.get("operatingCashflow")

        # FCF history from the reported cash-flow statement
        fcf_hist = []
        try:
            cf = t.cashflow
            if cf is not None and not cf.empty and "Free Cash Flow" in cf.index:
                s = cf.loc["Free Cash Flow"].dropna()
                fcf_hist = [(str(c)[:4], float(v)) for c, v in
                            sorted(s.items(), key=lambda kv: str(kv[0]))]
                if fcf is None and fcf_hist:
                    fcf = fcf_hist[-1][1]
        except Exception:
            pass

        out = {
            "symbol": symbol, "ok": True,
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "mcap": info.get("marketCap"),
            "shares": info.get("sharesOutstanding"),
            "ev": info.get("enterpriseValue"),
            "net_debt": (debt - cash) if (debt or cash) else None,
            "total_debt": debt, "cash": cash,
            "beta": info.get("beta"),
            "eps_ttm": info.get("trailingEps"), "eps_fwd": info.get("forwardEps"),
            "pe_t": info.get("trailingPE"), "pe_f": info.get("forwardPE"),
            "ev_ebitda": info.get("enterpriseToEbitda"),
            "pb": info.get("priceToBook"),
            "ebitda": info.get("ebitda"),
            "fcf": fcf, "cfo": cfo,
            "revenue": info.get("totalRevenue"),
            "rev_growth": info.get("revenueGrowth"),
            "op_margin": info.get("operatingMargins"),
            "profit_margin": info.get("profitMargins"),
            "name": info.get("shortName") or symbol,
            "sector": info.get("sector"),
            "fcf_history": fcf_hist,
        }
        _cache_put(key, out, ttl=3600)
    except Exception as e:
        print(f"[fundamentals {symbol}] {type(e).__name__}: {e}")
    return out


def get_statements(symbol: str) -> dict:
    """Raw reported statements (annual) for the 3-statement view. Cached 1h."""
    key = "stmts:" + symbol
    cached = _cache_get(key)
    if cached is not None:
        return cached
    out = {"income": None, "balance": None, "cashflow": None}
    if yf is None:
        return out
    try:
        t = yf.Ticker(symbol)
        out = {"income": t.financials, "balance": t.balance_sheet, "cashflow": t.cashflow}
        _cache_put(key, out, ttl=3600)
    except Exception as e:
        print(f"[statements {symbol}] {type(e).__name__}: {e}")
    return out


def get_peers(symbol: str, limit: int = 8) -> list[str]:
    """Finnhub peer list, cleaned (no self, no foreign listings). Cached 1d."""
    key = "peers:" + symbol
    cached = _cache_get(key)
    if cached is not None:
        return cached
    peers = []
    if have_finnhub():
        try:
            r = requests.get("https://finnhub.io/api/v1/stock/peers",
                             params={"symbol": symbol, "token": _finnhub_key()}, timeout=8)
            if r.ok:
                peers = [p for p in r.json()
                         if p and p != symbol and "." not in p][:limit]
        except Exception as e:
            print(f"[peers {symbol}] {type(e).__name__}: {e}")
    _cache_put(key, peers, ttl=86400)
    return peers


# --------------------------------------------------------------------------- #
#  TRUE STREAMING — Alpaca websocket (IEX). The REST poller stays as fallback
#  and as the source of prev_close / day-change context.
# --------------------------------------------------------------------------- #

_WS_HEALTHY = False
_WS_APP = None
_WS_SUBSCRIBED: set = set()
LIVE_VERSION = 0          # bumped on every quote update; SSE watches this


def _bump():
    global LIVE_VERSION
    LIVE_VERSION += 1


def ws_healthy() -> bool:
    return _WS_HEALTHY


def start_stream(get_symbols, on_update=None):
    """Alpaca IEX trade stream. Updates _LIVE tick-by-tick. Self-heals: on any
    error it marks unhealthy and retries every 15s; the REST poller covers the
    gap so the dashboard never goes blind."""
    if not have_alpaca():
        return None
    try:
        import websocket
    except Exception:
        print("[stream] websocket-client not installed — REST polling only")
        return None

    import json as _json

    def run():
        global _WS_HEALTHY, _WS_APP, _WS_SUBSCRIBED
        url = "wss://stream.data.alpaca.markets/v2/iex"
        while True:
            try:
                def on_open(ws):
                    ws.send(_json.dumps({"action": "auth",
                                         "key": _alpaca_key(), "secret": _alpaca_secret()}))

                def on_message(ws, msg):
                    global _WS_HEALTHY, _WS_SUBSCRIBED
                    try:
                        data = _json.loads(msg)
                    except Exception:
                        return
                    for m in (data if isinstance(data, list) else [data]):
                        t = m.get("T")
                        if t == "success" and m.get("msg") == "authenticated":
                            _WS_HEALTHY = True
                            syms = sorted(set(get_symbols()))
                            if syms:
                                ws.send(_json.dumps({"action": "subscribe", "trades": syms}))
                                _WS_SUBSCRIBED = set(syms)
                        elif t == "t":
                            sym, px = m.get("S"), m.get("p")
                            if not sym or px is None:
                                continue
                            with _LIVE_LOCK:
                                cur = _LIVE.get(sym, {})
                                prev = cur.get("prev_close")
                                ca = (px - prev) if prev else None
                                _LIVE[sym] = {
                                    "price": round(float(px), 2),
                                    "prev_close": prev,
                                    "change_abs": round(ca, 2) if ca is not None else None,
                                    "change_pct": round(ca / prev * 100, 2) if (ca is not None and prev) else None,
                                    "src": "alpaca-ws", "ts": time.time(),
                                }
                            _bump()
                            if on_update:
                                try:
                                    on_update(sym)
                                except Exception:
                                    pass
                        elif t == "error":
                            print(f"[stream] error: {m}")

                def on_close(ws, *a):
                    global _WS_HEALTHY
                    _WS_HEALTHY = False

                def on_error(ws, err):
                    global _WS_HEALTHY
                    _WS_HEALTHY = False

                app = websocket.WebSocketApp(url, on_open=on_open, on_message=on_message,
                                             on_close=on_close, on_error=on_error)
                _WS_APP = app

                # background: keep subscriptions matched to current holdings
                def sub_watch():
                    global _WS_SUBSCRIBED
                    while app.keep_running:
                        time.sleep(5)
                        if not _WS_HEALTHY:
                            continue
                        want = set(get_symbols())
                        add = sorted(want - _WS_SUBSCRIBED)
                        drop = sorted(_WS_SUBSCRIBED - want)
                        try:
                            if add:
                                app.send(_json.dumps({"action": "subscribe", "trades": add}))
                            if drop:
                                app.send(_json.dumps({"action": "unsubscribe", "trades": drop}))
                            _WS_SUBSCRIBED = want
                        except Exception:
                            pass
                threading.Thread(target=sub_watch, daemon=True).start()

                app.run_forever(ping_interval=20, ping_timeout=8)
            except Exception as e:
                print(f"[stream] {type(e).__name__}: {e}")
            _WS_HEALTHY = False
            time.sleep(15)      # retry

    t = threading.Thread(target=run, daemon=True, name="alpaca-stream")
    t.start()
    return t


# --------------------------------------------------------------------------- #
#  DIVIDENDS (raw objects for extras.dividends)
# --------------------------------------------------------------------------- #

def get_dividend_raw(symbol: str):
    """Ticker object + info, cached, for extras.dividends to slice."""
    key = "divraw:" + symbol
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if yf is None:
        return None, {}
    try:
        t = yf.Ticker(symbol)
        try:
            info = t.get_info()
        except Exception:
            info = getattr(t, "info", {}) or {}
        _cache_put(key, (t, info), ttl=3600)
        return t, info
    except Exception as e:
        print(f"[dividends {symbol}] {type(e).__name__}: {e}")
        return None, {}


# --------------------------------------------------------------------------- #
#  CHAIN QUOTES — delayed is fine for a map view
# --------------------------------------------------------------------------- #

def get_chain_quotes(symbols: list[str]) -> dict:
    key = "chainq:" + ",".join(sorted(symbols))
    cached = _cache_get(key)
    if cached is not None:
        return cached
    # reuse live where we have it; fill the rest from yfinance
    live = get_live().get("quotes", {})
    need = [s for s in symbols if s not in live]
    q = {s: live[s] for s in symbols if s in live}
    q.update(_yf_quotes(need))
    _cache_put(key, q, ttl=60)
    return q


# --------------------------------------------------------------------------- #
#  CUSTOM STRIP QUOTES — any mix of futures / indices / stocks (cached 20s)
# --------------------------------------------------------------------------- #

_STRIP_NAMES = {s: n for s, n, _ in FUTURES}

def get_strip(symbols: list[str]) -> list[dict]:
    key = "strip:" + ",".join(symbols)
    cached = _cache_get(key)
    if cached is not None:
        return cached
    out = []
    if yf is None or not symbols:
        return out
    try:
        raw = yf.download(symbols, period="5d", interval="1d",
                          progress=False, auto_adjust=False, group_by="ticker")
        single = len(symbols) == 1
        for sym in symbols:
            try:
                df = raw if single else (raw[sym] if sym in raw.columns.get_level_values(0) else None)
                if df is None:
                    continue
                ser = df["Close"].dropna()
                if len(ser) < 2:
                    continue
                last, prev = float(ser.iloc[-1]), float(ser.iloc[-2])
                short = sym.replace("=F", "").replace("^", "")
                out.append({
                    "symbol": sym, "short": short,
                    "name": _STRIP_NAMES.get(sym, short),
                    "price": round(last, 2),
                    "change_pct": round((last / prev - 1) * 100, 2) if prev else None,
                    "is_index": sym.startswith("^"),
                    "delayed": True,
                })
            except Exception:
                continue
        _cache_put(key, out, ttl=20)
    except Exception as e:
        print(f"[strip] {type(e).__name__}: {e}")
    return out


# --------------------------------------------------------------------------- #
#  PER-SYMBOL NEWS — for the holdings-row dropdowns (cached 3 min)
# --------------------------------------------------------------------------- #

def get_symbol_news(symbol: str, limit: int = 8) -> list[dict]:
    key = "symnews:" + symbol
    cached = _cache_get(key)
    if cached is not None:
        return cached
    if not have_finnhub():
        return [{"_notice": "Add a free FINNHUB_KEY to .env to load news."}]
    items = []
    try:
        if symbol == "MARKET":
            r = requests.get("https://finnhub.io/api/v1/news",
                             params={"category": "general", "token": _finnhub_key()}, timeout=8)
            for n in (r.json() if r.ok else [])[:limit]:
                items.append(_news_row(n, "Market"))
        else:
            today = dt.date.today()
            frm = (today - dt.timedelta(days=10)).isoformat()
            r = requests.get("https://finnhub.io/api/v1/company-news",
                             params={"symbol": symbol, "from": frm, "to": today.isoformat(),
                                     "token": _finnhub_key()}, timeout=8)
            seen = set()
            for n in (r.json() if r.ok else []):
                h = n.get("headline", "")
                if h and h not in seen:
                    seen.add(h)
                    items.append(_news_row(n, symbol))
                if len(items) >= limit:
                    break
    except Exception as e:
        print(f"[symnews {symbol}] {type(e).__name__}: {e}")
    _cache_put(key, items, ttl=180)
    return items


# --------------------------------------------------------------------------- #
#  30-DAY CARD SPARK — tiny close series for the chain popup (cached 30 min)
# --------------------------------------------------------------------------- #

def get_card_spark(symbol: str) -> list[float]:
    key = "spark30:" + symbol
    cached = _cache_get(key)
    if cached is not None:
        return cached
    out = []
    if yf is None:
        return out
    try:
        ser = yf.download(symbol, period="1mo", interval="1d",
                          progress=False, auto_adjust=False)["Close"]
        if hasattr(ser, "squeeze"):
            ser = ser.squeeze()
        ser = ser.dropna()
        out = [round(float(x), 2) for x in ser.tolist()][-30:]
        _cache_put(key, out, ttl=1800)
    except Exception as e:
        print(f"[spark30 {symbol}] {type(e).__name__}: {e}")
    return out
