"""
app.py — the local server.

Run:  python3 app.py   ->   http://localhost:7070

It serves one page (the dashboard) and a handful of JSON endpoints the page
polls. A background thread keeps live prices fresh; everything else is fetched
on request and cached in market.py. No login, no database, no trading — it
reads data and shows it. You make the decisions.
"""

from __future__ import annotations
import os, json, time, datetime as dt
import pandas as pd
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory, redirect, Response

APP_NAME = "Windrose"
APP_TAGLINE = "know where you actually stand"
APP_VERSION = "5.3"

# 7070 is the default, but it is not always free — a Linux box running other
# services may already own it, and the app used to die with a raw Flask error.
PORT = 7070
try:
    PORT = int((os.getenv("WINDROSE_PORT") or "7070").strip())
    if not (1 <= PORT <= 65535):
        PORT = 7070
except (TypeError, ValueError):
    PORT = 7070
LEDGER_VERSION = APP_VERSION      # legacy alias
BASE = Path(__file__).resolve().parent
import re as _re
# Letters, digits, and the punctuation real symbols use: BRK-B, BRK.B, ES=F, ^VIX
TICKER_RE = _re.compile(r"^[\^]?[A-Z0-9][A-Z0-9.\-=]{0,11}$")

HOLDINGS_FILE = BASE / "holdings.json"


# --- load .env (tiny parser, no extra dependency) ---
def load_env():
    env = BASE / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
import analysis as A          # noqa: E402  (after env load)
import market as M            # noqa: E402
import models as MD           # noqa: E402
import strategies as ST       # noqa: E402
import extras as X            # noqa: E402
import alerts as AL           # noqa: E402

app = Flask(__name__, static_folder=str(BASE / "static"), static_url_path="/static")
BENCH = "SPY"
_analysis_cache = {"ts": 0, "data": None}


# --------------------------------------------------------------------------- #
#  holdings persistence
# --------------------------------------------------------------------------- #

def load_holdings() -> list[dict]:
    if HOLDINGS_FILE.exists():
        try:
            return json.loads(HOLDINGS_FILE.read_text())
        except Exception:
            return []
    return []


# A starter portfolio so a brand-new install opens on a working dashboard
# instead of empty panels. These are ordinary large caps picked to span five
# sectors — they are examples, not recommendations, and the ✕ on each row
# removes them. Every one of them also appears in the supply-chain map, so the
# "trace my book" tools have something to chew on out of the box.
EXAMPLE_BOOK = [
    {"symbol": "AAPL", "shares": 12, "cost_basis": 268.40},   # technology
    {"symbol": "JPM",  "shares": 8,  "cost_basis": 331.75},   # financials
    {"symbol": "XOM",  "shares": 20, "cost_basis": 166.20},   # energy
    {"symbol": "KO",   "shares": 35, "cost_basis": 79.90},    # consumer staples
    {"symbol": "UNH",  "shares": 5,  "cost_basis": 425.50},   # healthcare
]


def save_holdings(holdings: list[dict]):
    HOLDINGS_FILE.write_text(json.dumps(holdings, indent=2))


def holding_symbols() -> list[str]:
    return [h["symbol"] for h in load_holdings()]


# --------------------------------------------------------------------------- #
#  market hours (approx: Mon-Fri 9:30-16:00 ET, ignores holidays)
# --------------------------------------------------------------------------- #

def market_status() -> dict:
    try:
        from zoneinfo import ZoneInfo
        now = dt.datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        now = dt.datetime.utcnow()
    open_now = (now.weekday() < 5
                and (now.hour, now.minute) >= (9, 30)
                and (now.hour, now.minute) < (16, 0))
    return {"open": open_now, "et": now.strftime("%a %I:%M:%S %p ET")}


# --------------------------------------------------------------------------- #
#  pages
# --------------------------------------------------------------------------- #

TUTORIAL_MARKER = BASE / ".tutorial_seen"


@app.route("/")
def index():
    # First run is handled in-page: the dashboard runs a guided tour until
    # the marker exists (see /api/status first_run + /api/tutorial/seen).
    return send_from_directory(str(BASE / "templates"), "index.html")


@app.route("/tutorial")
def tutorial():
    return send_from_directory(str(BASE / "templates"), "tutorial.html")


@app.route("/api/tutorial/seen", methods=["POST"])
def api_tutorial_seen():
    try:
        TUTORIAL_MARKER.write_text(dt.datetime.now().isoformat())
    except Exception:
        pass
    return jsonify({"ok": True})


@app.route("/api/tutorial/returns")
def api_tutorial_returns():
    """The book's daily % returns for the tutorial's VaR demo."""
    pw = _portfolio_weights()
    if not pw:
        return jsonify({"ok": False, "note": "no sized positions yet"})
    import numpy as np
    px = pw["close"][pw["syms"]].dropna()
    rets = np.log(px / px.shift(1)).dropna()
    w = np.array([pw["weights"][s] for s in pw["syms"]])
    port = rets.to_numpy() @ w
    return jsonify({"ok": True,
                    "returns_pct": [round(float(r) * 100, 3) for r in port],
                    "total_value": round(pw["total"], 2)})


# --------------------------------------------------------------------------- #
#  holdings API
# --------------------------------------------------------------------------- #

@app.route("/api/holdings", methods=["GET"])
def api_holdings():
    return jsonify(load_holdings())


@app.route("/api/holdings", methods=["POST"])
def api_add_holding():
    body = request.get_json(force=True, silent=True) or {}
    sym = (body.get("symbol") or "").strip().upper()
    if not sym:
        return jsonify({"error": "symbol required"}), 400
    # A ticker is a short, boring string. Without this, the endpoint happily
    # stored things like "<script>alert(1)</script>" and "../../etc/passwd",
    # which then get rendered in the holdings table and passed to data APIs.
    if not TICKER_RE.match(sym):
        return jsonify({"error": "not a valid ticker symbol"}), 400
    try:
        shares = float(body.get("shares", 0) or 0)
        cost = float(body.get("cost_basis", 0) or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "shares and cost must be numbers"}), 400
    # Negative shares broke the risk maths silently (a negative weight), and a
    # value like 1e18 produced a portfolio worth more than the world.
    if shares < 0 or cost < 0:
        return jsonify({"error": "shares and cost cannot be negative"}), 400
    if shares > 1e12 or cost > 1e12 or shares != shares or cost != cost:
        return jsonify({"error": "that number is out of range"}), 400
    acquired = (body.get("acquired") or "").strip() or None
    if acquired:
        try:
            dt.date.fromisoformat(acquired)
        except ValueError:
            return jsonify({"error": "acquired must be YYYY-MM-DD"}), 400
    holdings = load_holdings()
    holdings = [h for h in holdings if h["symbol"] != sym]   # replace if exists
    h = {"symbol": sym, "shares": shares, "cost_basis": cost}
    if acquired:
        h["acquired"] = acquired
    holdings.append(h)
    save_holdings(holdings)
    _analysis_cache["ts"] = 0          # force recompute next call
    return jsonify(holdings)


@app.route("/api/holdings/<symbol>", methods=["DELETE"])
def api_delete_holding(symbol):
    sym = symbol.strip().upper()
    holdings = [h for h in load_holdings() if h["symbol"] != sym]
    save_holdings(holdings)
    _analysis_cache["ts"] = 0
    return jsonify(holdings)


# --------------------------------------------------------------------------- #
#  live / futures / news / status
# --------------------------------------------------------------------------- #

@app.route("/api/live")
def api_live():
    return jsonify(M.get_live())


@app.route("/api/futures")
def api_futures():
    return jsonify(M.get_futures())


@app.route("/api/news")
def api_news():
    return jsonify(M.get_news(holding_symbols()))


@app.route("/api/outlook/<symbol>")
def api_outlook(symbol):
    return jsonify(M.get_outlook(symbol.strip().upper()))


@app.route("/api/status")
def api_status():
    live = M.get_live()
    return jsonify({
        "market": market_status(),
        "live_src": live.get("src"),
        "have_alpaca": M.have_alpaca(),
        "have_finnhub": M.have_finnhub(),
        "n_holdings": len(load_holdings()),
        "server_time": dt.datetime.now().strftime("%I:%M:%S %p"),
        "first_run": not TUTORIAL_MARKER.exists(),
        "version": APP_VERSION,
        "app_name": APP_NAME,
        "settings": load_settings(),
    })


@app.route("/api/spark")
def api_spark():
    """Chart series (close + SMA20/50) per holding, for the canvas charts."""
    symbols = holding_symbols()
    if not symbols:
        return jsonify({})
    hist = M.get_history(symbols, bench=BENCH)
    out = {}
    for s in symbols:
        f = hist["frames"].get(s)
        if f is not None and len(f) > 5:
            out[s] = A.chart_series(f)
    return jsonify(out)


# --------------------------------------------------------------------------- #
#  analysis (the heavy one — cached ~45s)
# --------------------------------------------------------------------------- #

import threading as _th
_analysis_lock = _th.Lock()


def get_analysis() -> dict:
    with _analysis_lock:
        if _analysis_cache["data"] is not None and time.time() - _analysis_cache["ts"] < 45:
            return _analysis_cache["data"]
        return _compute_analysis()


def _compute_analysis() -> dict:
    holdings = load_holdings()
    symbols = [h["symbol"] for h in holdings]
    if not symbols:
        data = {"stocks": [], "portfolio": {"ok": False, "reason": "no holdings yet"},
                "generated_at": dt.datetime.now().strftime("%I:%M:%S %p")}
        _analysis_cache.update(ts=time.time(), data=data)
        return data

    hist = M.get_history(symbols, bench=BENCH)
    close, frames = hist["close"], hist["frames"]
    live = M.get_live().get("quotes", {})
    live_prices = {s: q["price"] for s, q in live.items() if q.get("price")}

    bench_closes = close[BENCH].to_numpy() if (BENCH in getattr(close, "columns", [])) else None

    stocks = []
    for s in symbols:
        if s in frames and len(frames[s]) > 20:
            bench = (close[BENCH].reindex(frames[s].index).to_numpy()
                     if bench_closes is not None else None)
            row = A.per_stock(s, frames[s], bench)
            if s in live_prices:
                row["live_price"] = live_prices[s]
            stocks.append(row)
        else:
            stocks.append({"symbol": s, "summary": "Not enough price history yet."})

    port = A.portfolio(holdings, close, live_prices=live_prices, bench=BENCH) \
        if not close.empty else {"ok": False, "reason": "no price history"}

    data = {"stocks": stocks, "portfolio": port,
            "generated_at": dt.datetime.now().strftime("%I:%M:%S %p")}
    _analysis_cache.update(ts=time.time(), data=data)
    return data


@app.route("/api/analysis")
def api_analysis():
    return jsonify(get_analysis())



@app.route("/api/company/<symbol>")
def api_company(symbol):
    """Small dossier for the chain popup — cached fundamentals, no heavy math."""
    try:
        f = M.get_fundamentals(symbol.strip().upper()) or {}
        mc = f.get("market_cap")
        return jsonify({"ok": True, "name": f.get("name"),
                        "sector": f.get("sector"), "industry": f.get("industry"),
                        "market_cap": mc, "spark": M.get_card_spark(symbol.strip().upper())})
    except Exception as e:
        return jsonify({"ok": False, "note": str(e)[:80]})


@app.route("/api/strip")
def api_strip():
    """Quotes for the top strip — any mix of futures (=F), indices (^), stocks."""
    raw = (request.args.get("symbols") or "").strip()
    syms = [s.strip().upper() for s in raw.split(",") if s.strip()][:12]
    return jsonify(M.get_strip(syms) if syms else M.get_futures())


@app.route("/api/news/<symbol>")
def api_symbol_news(symbol):
    return jsonify(M.get_symbol_news(symbol.strip().upper()))


# --------------------------------------------------------------------------- #
#  models workbench
# --------------------------------------------------------------------------- #

def _q(name, default, lo=None, hi=None):
    try:
        v = float(request.args.get(name, default))
    except (TypeError, ValueError):
        v = default
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


@app.route("/api/models/fund/<symbol>")
def api_fund(symbol):
    return jsonify(M.get_fundamentals(symbol.strip().upper()))


@app.route("/api/models/rdcf/<symbol>")
def api_rdcf(symbol):
    f = M.get_fundamentals(symbol.strip().upper())
    if not f.get("ok"):
        return jsonify({"ok": False, "note": "fundamentals unavailable"})
    return jsonify(MD.reverse_dcf(f,
        discount_pct=_q("r", 9.0, 5, 20), terminal_pct=_q("gt", 2.5, 0, 4.5)))


@app.route("/api/models/comps/<symbol>")
def api_comps(symbol):
    sym = symbol.strip().upper()
    f = M.get_fundamentals(sym)
    if not f.get("ok"):
        return jsonify({"ok": False, "note": "fundamentals unavailable"})
    peers = M.get_peers(sym)
    if not peers:
        return jsonify({"ok": False, "note": "peer list unavailable (needs Finnhub key)"})
    pfs = [M.get_fundamentals(p) for p in peers[:7]]
    return jsonify(MD.comps(f, [p for p in pfs if p.get("ok")]))


@app.route("/api/models/statements/<symbol>")
def api_statements(symbol):
    return jsonify(MD.statements_view(M.get_statements(symbol.strip().upper())))


@app.route("/api/models/lbo/<symbol>")
def api_lbo(symbol):
    f = M.get_fundamentals(symbol.strip().upper())
    if not f.get("ok"):
        return jsonify({"ok": False, "note": "fundamentals unavailable"})
    exit_m = request.args.get("exit")
    return jsonify(MD.lbo(f,
        premium_pct=_q("premium", 25, 0, 80), debt_pct=_q("debt", 60, 20, 90),
        rate_pct=_q("rate", 9, 3, 15), ebitda_growth_pct=_q("growth", 4, -5, 20),
        exit_multiple=float(exit_m) if exit_m else None,
        years=int(_q("years", 5, 3, 7)), tax_pct=_q("tax", 21, 0, 40)))


@app.route("/api/models/mna")
def api_mna():
    acq = (request.args.get("acq") or "").strip().upper()
    tgt = (request.args.get("tgt") or "").strip().upper()
    if not acq or not tgt:
        return jsonify({"ok": False, "note": "need acq and tgt symbols"})
    fa, ft = M.get_fundamentals(acq), M.get_fundamentals(tgt)
    if not (fa.get("ok") and ft.get("ok")):
        return jsonify({"ok": False, "note": "fundamentals unavailable for one side"})
    return jsonify(MD.mna(fa, ft,
        premium_pct=_q("premium", 25, 0, 80), pct_stock=_q("stock", 50, 0, 100),
        debt_rate_pct=_q("rate", 6, 2, 12), synergies_m=_q("syn", 0, 0, 20000),
        tax_pct=_q("tax", 21, 0, 40)))


def _portfolio_weights():
    holdings = [h for h in load_holdings() if float(h.get("shares", 0)) > 0]
    syms = [h["symbol"] for h in holdings]
    if not syms:
        return None
    close = M.get_history(syms)["close"]
    live = {s: q["price"] for s, q in M.get_live().get("quotes", {}).items() if q.get("price")}
    mv = {}
    for h in holdings:
        s = h["symbol"]
        if s not in close.columns:
            continue
        px = float(live.get(s, close[s].dropna().iloc[-1]))
        mv[s] = px * float(h["shares"])
    tot = sum(mv.values())
    if tot <= 0:
        return None
    return {"syms": list(mv.keys()), "weights": {s: v / tot for s, v in mv.items()},
            "total": tot, "close": close}


@app.route("/api/models/montecarlo")
def api_montecarlo():
    pw = _portfolio_weights()
    if not pw:
        return jsonify({"ok": False, "note": "no sized positions yet"})
    import numpy as np
    px = pw["close"][pw["syms"]].dropna()
    rets = np.log(px / px.shift(1)).dropna()
    w = np.array([pw["weights"][s] for s in pw["syms"]])
    return jsonify(MD.monte_carlo(rets, w, pw["total"],
                                  horizon=int(_q("horizon", 252, 21, 756))))


@app.route("/api/models/stress")
def api_stress():
    pw = _portfolio_weights()
    if not pw:
        return jsonify({"ok": False, "note": "no sized positions yet"})
    close7 = M.get_history(pw["syms"], period="7y")["close"]
    return jsonify(MD.stress_test(close7, pw["weights"], pw["total"]))


@app.route("/api/models/backtest/<symbol>")
def api_backtest(symbol):
    sym = symbol.strip().upper()
    frames = M.get_history([sym], period="5y")["frames"]
    if sym not in frames:
        return jsonify({"ok": False, "note": "no history for " + sym})
    return jsonify(ST.backtest(sym, frames[sym]["Close"]))



# --------------------------------------------------------------------------- #
#  streaming to the browser (SSE) — pushes on every tick, heartbeats between
# --------------------------------------------------------------------------- #

@app.route("/api/stream")
def api_stream():
    def gen():
        last_v = -1
        last_alert_ts = time.time()
        last_beat = 0.0
        while True:
            live = M.get_live()
            payload = None
            if live.get("v", 0) != last_v:
                last_v = live.get("v", 0)
                payload = {"type": "quotes", "src": live["src"], "quotes": live["quotes"]}
            fired = AL.fired_since(last_alert_ts)
            if fired:
                last_alert_ts = max(e["ts"] for e in fired)
                yield "data: " + json.dumps({"type": "alerts", "events": fired}) + "\n\n"
            if payload:
                yield "data: " + json.dumps(payload) + "\n\n"
                last_beat = time.time()
            elif time.time() - last_beat > 12:
                yield ": ping\n\n"
                last_beat = time.time()
            time.sleep(0.35)
    return Response(gen(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------------- #
#  alerts
# --------------------------------------------------------------------------- #

@app.route("/api/alerts", methods=["GET"])
def api_alerts():
    return jsonify({"rules": AL.load(), "metrics": AL.METRICS,
                    "recent": list(AL.FIRED)[-15:]})


@app.route("/api/alerts", methods=["POST"])
def api_alerts_add():
    b = request.get_json(force=True, silent=True) or {}
    try:
        rule = AL.add(b.get("symbol", ""), b.get("metric", ""),
                      float(b.get("value", 0)), b.get("note", ""))
        return jsonify(rule)
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/alerts/<rid>", methods=["DELETE"])
def api_alerts_del(rid):
    return jsonify({"deleted": AL.delete(rid)})


@app.route("/api/alerts/<rid>/toggle", methods=["POST"])
def api_alerts_toggle(rid):
    return jsonify({"enabled": AL.toggle(rid)})


_port_peak_cache = {"ts": 0, "dd": None}


def _port_drawdown_from_peak():
    """Book value today vs its 1-year peak (with current share counts)."""
    if time.time() - _port_peak_cache["ts"] < 60:
        return _port_peak_cache["dd"]
    dd = None
    try:
        pw = _portfolio_weights()
        if pw:
            import numpy as np
            holdings = {h["symbol"]: float(h["shares"]) for h in load_holdings()
                        if float(h.get("shares", 0)) > 0}
            px = pw["close"][[s for s in holdings if s in pw["close"].columns]].dropna()
            curve = (px * pd.Series(holdings)).sum(axis=1)
            peak = float(curve.max())
            now = pw["total"]
            if peak > 0:
                dd = round((now / peak - 1) * 100, 2)
    except Exception:
        pass
    _port_peak_cache.update(ts=time.time(), dd=dd)
    return dd


def _alerts_loop():
    while True:
        try:
            live = M.get_live().get("quotes", {})
            stocks = (_analysis_cache.get("data") or {}).get("stocks", [])
            AL.evaluate(live, stocks, {"max_drawdown_from_peak_pct": _port_drawdown_from_peak()})
        except Exception as e:
            print(f"[alerts] {type(e).__name__}: {e}")
        time.sleep(3)


# --------------------------------------------------------------------------- #
#  dividends, income, benchmark, what-if, journal, earnings, csv, chain
# --------------------------------------------------------------------------- #

_div_cache = {"ts": 0, "rows": []}


def _all_dividends():
    if time.time() - _div_cache["ts"] < 900:
        return _div_cache["rows"]
    live = {s: q["price"] for s, q in M.get_live().get("quotes", {}).items() if q.get("price")}
    rows = []
    for h in load_holdings():
        t, info = M.get_dividend_raw(h["symbol"])
        if t is None:
            continue
        rows.append(X.dividends(h["symbol"], t, info, h.get("acquired"),
                                float(h.get("shares", 0)), float(h.get("cost_basis", 0)),
                                live.get(h["symbol"])))
    _div_cache.update(ts=time.time(), rows=rows)
    return rows


@app.route("/api/dividends")
def api_dividends():
    rows = _all_dividends()
    income = X.portfolio_income(rows, load_holdings())
    return jsonify({"rows": rows, "income": income})


@app.route("/api/benchmark")
def api_benchmark():
    pw = _portfolio_weights()
    if not pw:
        return jsonify({"ok": False, "note": "no sized positions yet"})
    live = {s: q["price"] for s, q in M.get_live().get("quotes", {}).items() if q.get("price")}
    return jsonify(X.benchmark(load_holdings(), pw["close"], live))


@app.route("/api/whatif")
def api_whatif():
    raw = request.args.get("shares", "")
    hypo = {}
    for part in raw.split(","):
        if ":" in part:
            s, v = part.split(":", 1)
            try:
                hypo[s.strip().upper()] = float(v)
            except ValueError:
                pass
    pw = _portfolio_weights()
    holdings = load_holdings()
    extra = [s for s in hypo if s not in {h["symbol"] for h in holdings}]
    close = M.get_history(sorted({h["symbol"] for h in holdings} | set(extra)))["close"]         if extra else (pw["close"] if pw else M.get_history([h["symbol"] for h in holdings])["close"])
    live = {s: q["price"] for s, q in M.get_live().get("quotes", {}).items() if q.get("price")}
    return jsonify(X.whatif(holdings, hypo, close, live, A.portfolio))


@app.route("/api/journal", methods=["GET"])
def api_journal():
    pw = _portfolio_weights()
    close = pw["close"] if pw else M.get_history(holding_symbols())["close"]
    live = {s: q["price"] for s, q in M.get_live().get("quotes", {}).items() if q.get("price")}
    return jsonify(X.journal_stats(close, live))


@app.route("/api/journal", methods=["POST"])
def api_journal_add():
    b = request.get_json(force=True, silent=True) or {}
    sym = (b.get("symbol") or "").strip().upper()
    if not sym:
        return jsonify({"error": "symbol required"}), 400
    e = X.journal_add(sym, b.get("side", "note"), b.get("reason", ""),
                      float(b["price"]) if b.get("price") else None,
                      float(b["shares"]) if b.get("shares") else None,
                      b.get("date"))
    return jsonify(e)


@app.route("/api/journal/<eid>", methods=["DELETE"])
def api_journal_del(eid):
    return jsonify({"deleted": X.journal_delete(eid)})


@app.route("/api/earnings")
def api_earnings():
    return jsonify(X.earnings_strip(holding_symbols(), M.get_outlook))


@app.route("/api/export.csv")
def api_export():
    analysis = _analysis_cache.get("data") or {}
    live = {s: q["price"] for s, q in M.get_live().get("quotes", {}).items() if q.get("price")}
    csv = X.export_csv(load_holdings(), analysis, live)
    return Response(csv, mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=windrose_export.csv"})


@app.route("/api/factors")
def api_factors():
    """Beta/correlation vs SPY, ITA (defense), XLI (industrials) + sector mix."""
    pw = _portfolio_weights()
    if not pw:
        return jsonify({"ok": False, "note": "no sized positions yet"})
    import numpy as np
    benches = ["SPY", "ITA", "XLI"]
    close = M.get_history(pw["syms"], bench="SPY")["close"]
    extra = M.get_history(benches)["close"]
    allpx = close.join(extra[[b for b in benches if b not in close.columns]], how="inner").dropna()
    rets = np.log(allpx / allpx.shift(1)).dropna()
    w = np.array([pw["weights"][s] for s in pw["syms"]])
    port = rets[pw["syms"]].to_numpy() @ w
    out = {"ok": True, "benches": {}}
    for b in benches:
        if b not in rets.columns:
            continue
        bb = rets[b].to_numpy()
        var_b = bb.var(ddof=1)
        beta = float(np.cov(port, bb, ddof=1)[0, 1] / var_b) if var_b else None
        corr = float(np.corrcoef(port, bb)[0, 1])
        out["benches"][b] = {"beta": round(beta, 2) if beta else None, "corr": round(corr, 2)}
    sectors = {}
    for s in pw["syms"]:
        f = M.get_fundamentals(s)
        sec = (f.get("op_margin") is not None or True) and (f.get("sector") or "Unknown")
        sectors[sec] = sectors.get(sec, 0) + pw["weights"][s] * 100
    out["sectors"] = [{"sector": k, "weight_pct": round(v, 1)}
                      for k, v in sorted(sectors.items(), key=lambda kv: -kv[1])]
    return jsonify(out)


def _chain_merged(data: dict) -> dict:
    """Every network fused into one graph — nodes deduped by id, edges by pair."""
    nodes, edges, seen_n, seen_e = [], [], {}, {}
    for net_id, net in data.get("networks", {}).items():
        for n in net["nodes"]:
            if n["id"] not in seen_n:
                seen_n[n["id"]] = dict(n, nets=[net_id])
                nodes.append(seen_n[n["id"]])
            elif net_id not in seen_n[n["id"]]["nets"]:
                seen_n[n["id"]]["nets"].append(net_id)
        for e in net["edges"]:
            k = (e["from"], e["to"])
            if k in seen_e:
                if e["rel"] not in seen_e[k]["rel"]:
                    seen_e[k]["rel"] += " · " + e["rel"]
            else:
                seen_e[k] = dict(e)
                edges.append(seen_e[k])
    return {"nodes": nodes, "edges": edges}


@app.route("/api/chain")
def api_chain():
    data = X.chain_load()
    net_id = request.args.get("net", "defense")
    avail = ["all"] + list(data.get("networks", {}).keys())
    net = _chain_merged(data) if net_id == "all" else data.get("networks", {}).get(net_id)
    if not net:
        return jsonify({"ok": False, "note": "unknown network", "available": avail})
    # ?quotes=0 returns the graph immediately; the browser then asks for prices
    # separately. The merged view needs ~300 quotes and that can take a minute
    # cold — no reason to stare at a blank panel while it happens.
    want_quotes = request.args.get("quotes", "1") != "0"
    quotes = M.get_chain_quotes(X.chain_tickers(net)) if want_quotes else {}
    return jsonify({"ok": True, "id": net_id, "network": net, "quotes": quotes,
                    "available": avail,
                    "holdings": holding_symbols(),
                    "note": data.get("_note", "")})


# --------------------------------------------------------------------------- #
#  settings — experience mode and personalisation, stored next to your data
# --------------------------------------------------------------------------- #

SETTINGS_FILE = BASE / "settings.json"

DEFAULT_SETTINGS = {
    "mode": None,            # None = never chosen, so show the welcome screen
    "accent": "#e87a41",
    "density": "comfortable",
    "hidden": [],            # panels the user switched off
    "title": "",             # optional name for this dashboard
    # Whether the launcher *checks* for a newer version. It no longer applies
    # one — see update.sh. False still means "leave me alone", which is what
    # anyone who set it to false was asking for.
    "auto_update": True,
    "desktop_notifications": True,   # OS popups when no browser tab is open
    "cbsafe": False,         # blue/orange instead of green/red for gains and losses
    "preset": "",            # last-applied layout preset, for the settings UI
}


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            s.update(json.loads(SETTINGS_FILE.read_text()))
    except Exception:
        pass
    return s


def save_settings(s: dict) -> None:
    try:
        SETTINGS_FILE.write_text(json.dumps(s, indent=2))
    except Exception as e:
        print(f"[settings] could not save: {e}")


def _loopback_only():
    """Keys may only be set from this machine, never over the network."""
    ip = request.remote_addr or ""
    return ip.startswith("127.") or ip == "::1"


@app.route("/api/setup/testkeys", methods=["POST"])
def api_test_keys():
    """Try a key before saving it, so nobody pastes and hopes."""
    if not _loopback_only():
        return jsonify({"ok": False, "error": "keys can only be set on this computer"}), 403
    body = request.get_json(silent=True) or {}
    which = body.get("which")
    result = {"ok": False, "detail": ""}

    if which == "finnhub":
        key = (body.get("finnhub_key") or "").strip()
        if not key:
            return jsonify({"ok": False, "detail": "no key given"})
        try:
            import requests as _rq
            r = _rq.get("https://finnhub.io/api/v1/quote",
                        params={"symbol": "AAPL", "token": key}, timeout=8)
            if r.status_code == 200 and isinstance(r.json().get("c"), (int, float)) and r.json().get("c"):
                result = {"ok": True, "detail": f"working — AAPL at {r.json()['c']}"}
            elif r.status_code in (401, 403):
                result = {"ok": False, "detail": "that key was rejected"}
            else:
                result = {"ok": False, "detail": f"unexpected response ({r.status_code})"}
        except Exception as e:
            result = {"ok": False, "detail": f"could not reach Finnhub ({type(e).__name__})"}

    elif which == "alpaca":
        k = (body.get("alpaca_key") or "").strip()
        s = (body.get("alpaca_secret") or "").strip()
        if not k or not s:
            return jsonify({"ok": False, "detail": "both key and secret are needed"})
        try:
            import requests as _rq
            r = _rq.get("https://data.alpaca.markets/v2/stocks/snapshots",
                        params={"symbols": "AAPL", "feed": "iex"},
                        headers={"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s}, timeout=8)
            if r.status_code == 200:
                result = {"ok": True, "detail": "working — live quotes enabled"}
            elif r.status_code in (401, 403):
                result = {"ok": False, "detail": "those credentials were rejected"}
            else:
                result = {"ok": False, "detail": f"unexpected response ({r.status_code})"}
        except Exception as e:
            result = {"ok": False, "detail": f"could not reach Alpaca ({type(e).__name__})"}
    else:
        result = {"ok": False, "detail": "unknown provider"}

    return jsonify(result)


@app.route("/api/setup/savekeys", methods=["POST"])
def api_save_keys():
    """Write keys into .env. Values never leave this machine."""
    if not _loopback_only():
        return jsonify({"ok": False, "error": "keys can only be set on this computer"}), 403
    body = request.get_json(silent=True) or {}
    wanted = {
        "FINNHUB_KEY": (body.get("finnhub_key") or "").strip(),
        "ALPACA_KEY": (body.get("alpaca_key") or "").strip(),
        "ALPACA_SECRET": (body.get("alpaca_secret") or "").strip(),
    }
    env = BASE / ".env"
    lines = env.read_text().splitlines() if env.exists() else []
    kept = [l for l in lines
            if not any(l.strip().lstrip("#").strip().startswith(k + "=") for k in wanted)]
    for k, v in wanted.items():
        if v:
            kept.append(f"{k}={v}")
            os.environ[k] = v          # live now, no restart needed
    header = "# Windrose configuration — written by the setup wizard. Keep private."
    if not any(l.startswith("# Windrose configuration") for l in kept):
        kept.insert(0, header)
    env.write_text("\n".join(kept).rstrip() + "\n")
    return jsonify({"ok": True, "finnhub": M.have_finnhub(), "alpaca": M.have_alpaca()})


@app.route("/api/setup/seed", methods=["POST"])
def api_seed():
    """Start empty, or with the example book, at the user's choice."""
    body = request.get_json(silent=True) or {}
    if body.get("examples"):
        save_holdings(EXAMPLE_BOOK)
    else:
        save_holdings([])
    _analysis_cache["ts"] = 0
    return jsonify(load_holdings())


@app.route("/api/chokepoints")
def api_chokepoints():
    """What the whole book rests on — shared suppliers and shared customers.

    The risk panel measures how holdings move together. This measures what
    they depend on, which correlation only reveals after the fact.
    """
    import chokepoints as CP
    try:
        hops = max(1, min(4, int(request.args.get("hops", 3))))
    except (TypeError, ValueError):
        hops = 3
    quotes = M.get_live().get("quotes", {})
    return jsonify(CP.analyse(X.chain_load(), load_holdings(), quotes, max_hops=hops))


@app.route("/api/diagnostics")
def api_diagnostics():
    """Facts that help reproduce a bug — and nothing else.

    Deliberately excluded: tickers, share counts, cost bases, journal text,
    alert rules, API keys, file paths, hostname. Whether a key is *configured*
    is a yes/no; the key itself never leaves the machine.
    """
    import platform, sys as _sys
    import updater
    s = load_settings()
    holdings = load_holdings()
    return jsonify({
        # Which fork is running is itself a fact needed to reproduce a bug, and
        # it is what points the Report button at the right issue tracker.
        "repo": updater.REPO,
        "version": APP_VERSION,
        "python": platform.python_version(),
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "mode": s.get("mode") or "unset",
        "install": "git" if (BASE / ".git").exists() else "zip",
        "data_source": "alpaca" if M.have_alpaca() else "yfinance-delayed",
        "news_configured": bool(M.have_finnhub()),
        "position_count": len(holdings),
    })


@app.route("/api/update/check")
def api_update_check():
    """Is a newer version published? Never installs — see the launcher."""
    import updater
    return jsonify(updater.check(APP_VERSION, force=request.args.get("force") == "1"))


@app.route("/api/settings", methods=["GET", "POST"])
def api_settings():
    s = load_settings()
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        for k in DEFAULT_SETTINGS:
            if k in body:
                s[k] = body[k]
        if s.get("mode") not in (None, "simple", "advanced"):
            s["mode"] = "advanced"
        if not isinstance(s.get("hidden"), list):
            s["hidden"] = []
        save_settings(s)
    return jsonify(s)


# --------------------------------------------------------------------------- #
#  phone access — LAN mode, passcode-gated
# --------------------------------------------------------------------------- #

LAN_MODE = False
LAN_PIN = None
PIN_FILE = BASE / ".lan_pin"


def _local_ip() -> str:
    """This machine's address on the home network (no traffic is actually sent)."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _bindable(ip: str) -> bool:
    """Can we actually listen on this address right now?"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((ip, 0))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _load_or_make_pin() -> str:
    pin = (os.getenv("WINDROSE_PIN") or os.getenv("LEDGER_PIN") or "").strip()
    if pin:
        return pin
    if PIN_FILE.exists():
        saved = PIN_FILE.read_text().strip()
        if saved:
            return saved
    import secrets
    pin = f"{secrets.randbelow(900000) + 100000}"
    try:
        PIN_FILE.write_text(pin)
    except Exception:
        pass
    return pin


_PIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Windrose</title><style>
 body{margin:0;height:100vh;display:flex;align-items:center;justify-content:center;
   background:#0b0d11;color:#e4e6eb;font-family:-apple-system,BlinkMacSystemFont,sans-serif}
 .box{width:min(320px,86vw);text-align:center}
 .mark{color:#e87a41;font-size:30px;letter-spacing:-.02em;margin-bottom:6px}
 p{color:#8b9199;font-size:14px;line-height:1.5;margin:0 0 22px}
 input{width:100%;box-sizing:border-box;background:#151820;border:1px solid #262b36;color:#e4e6eb;
   font-family:ui-monospace,monospace;font-size:22px;text-align:center;letter-spacing:.35em;
   padding:14px;border-radius:12px;-webkit-appearance:none}
 input:focus{outline:none;border-color:#e87a41}
 button{width:100%;margin-top:12px;background:#e87a41;color:#0b0d11;border:0;font-size:16px;
   font-weight:600;padding:14px;border-radius:12px}
 .err{color:#e5534b;font-size:13px;margin-top:14px;min-height:16px}
</style></head><body><div class="box">
 <div class="mark">&#9612; WINDROSE</div>
 <p>Enter the passcode shown in the terminal on your computer.</p>
 <form method="get"><input name="pin" inputmode="numeric" pattern="[0-9]*" autofocus
   placeholder="000000" autocomplete="off"><button type="submit">Unlock</button></form>
 <div class="err">__ERR__</div></div></body></html>"""


@app.before_request
def _lan_guard():
    """Loopback is always trusted. Anything off-box needs the passcode once."""
    if not LAN_MODE or not LAN_PIN:
        return None
    ip = request.remote_addr or ""
    if ip.startswith("127.") or ip == "::1":
        return None
    if request.cookies.get("ledger_pin") == LAN_PIN:
        return None
    supplied = (request.args.get("pin") or "").strip()
    if supplied == LAN_PIN:
        resp = redirect(request.path or "/")
        resp.set_cookie("ledger_pin", LAN_PIN, max_age=60 * 60 * 24 * 365,
                        samesite="Lax", httponly=True)
        return resp
    err = "That code didn't match — try again." if supplied else ""
    page = _PIN_PAGE.replace("__ERR__", err)
    if not LAN_PIN.isdigit():          # a chosen passphrase wants a normal keyboard
        page = page.replace(' inputmode="numeric" pattern="[0-9]*"', ' autocapitalize="off"')
        page = page.replace('placeholder="000000"', 'placeholder="passcode"')
        page = page.replace("letter-spacing:.35em;", "letter-spacing:.04em;")
    return Response(page, status=401, mimetype="text/html")


@app.route("/manifest.webmanifest")
def api_manifest():
    """Makes Add to Home Screen open Windrose full-screen with its own icon."""
    return jsonify({
        "name": "Windrose", "short_name": "Windrose",
        "start_url": "/", "scope": "/",
        "display": "standalone", "orientation": "any",
        "background_color": "#0b0d11", "theme_color": "#0b0d11",
        "icons": [
            {"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": "/static/icons/maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
    })


# --------------------------------------------------------------------------- #
#  boot
# --------------------------------------------------------------------------- #

def start_background():
    """Everything except the HTTP server — shared by web and app modes."""
    if not HOLDINGS_FILE.exists():
        # On a true first run the setup wizard asks whether the user wants the
        # example book, so seeding here would pre-empt their answer. Seed only
        # when setup has already happened and the file has gone missing.
        already_set_up = bool((load_settings() or {}).get("mode"))
        save_holdings(EXAMPLE_BOOK if already_set_up else [])
    M.start_live_poller(holding_symbols, interval=2.0)
    M.start_stream(holding_symbols)
    import threading as _t
    try:
        AL.DESKTOP_NOTIFY = bool(load_settings().get("desktop_notifications", True))
    except Exception:
        pass
    _t.Thread(target=_alerts_loop, daemon=True, name="alerts").start()


def main():
    global LAN_MODE, LAN_PIN
    import sys
    LAN_MODE = ("--lan" in sys.argv) \
        or os.getenv("WINDROSE_LAN", os.getenv("LEDGER_LAN", "")).strip() in ("1", "true", "yes")

    start_background()
    print(f"\n  {APP_NAME} v{APP_VERSION} — {APP_TAGLINE}")
    print(f"  ->  http://127.0.0.1:{PORT}")
    print("  Alpaca live:", "yes" if M.have_alpaca() else "no (using delayed yfinance)",
          "| Finnhub news:", "yes" if M.have_finnhub() else "no")

    host = "127.0.0.1"
    if LAN_MODE:
        LAN_PIN = _load_or_make_pin()
        host = "0.0.0.0"
        url = f"http://{_local_ip()}:{PORT}"
        host = "0.0.0.0"

        print("\n  " + "-" * 58)
        print("  PHONE / TABLET ACCESS IS ON")
        print(f"  Open on the other device:   {url}")
        print(f"  Passcode:                   {LAN_PIN}")
        print("  Reachable from:             any device on this Wi-Fi with the passcode")
        try:
            import qrcode
            q = qrcode.QRCode(border=1)
            q.add_data(f"{url}/?pin={LAN_PIN}")
            q.make()
            print()
            q.print_ascii(invert=True)
        except ImportError:
            print("  (pip install qrcode  for a scannable code here)")
        print("  Both devices must be on the same network. Leave this off on")
        print("  public Wi-Fi — the passcode is the only thing standing in the way.")
        print("  " + "-" * 58)

    # Flask logs a line for every request. Windrose polls itself several times
    # a second, so the console fills with noise and a genuine error scrolls
    # past unread — which is exactly what happened to the first Windows
    # tester. Errors still print; the request log and the "development
    # server" banner do not. WINDROSE_VERBOSE=1 puts it all back.
    if os.getenv("WINDROSE_VERBOSE", "").strip() not in ("1", "true", "yes"):
        import logging
        logging.getLogger("werkzeug").setLevel(logging.ERROR)
        try:
            import flask.cli
            flask.cli.show_server_banner = lambda *a, **k: None
        except Exception:
            pass

    print("\n  Ctrl+C to stop.\n")
    # Check before handing over to Flask — it swallows the error and prints its
    # own, which tells the user nothing about how to fix it.
    import socket as _sk
    _probe = _sk.socket(_sk.AF_INET, _sk.SOCK_STREAM)
    try:
        _probe.bind((host if host != "0.0.0.0" else "", PORT))
        _probe.close()
    except OSError:
        _probe.close()
        alt = PORT + 1
        print(f"\n  Port {PORT} is already being used by another program.")
        print(f"  Start Windrose somewhere else instead:\n")
        print(f"      WINDROSE_PORT={alt} bash \"Start Windrose.command\"\n")
        print(f"  then open  http://127.0.0.1:{alt}")
        print(f"  On Linux, 'ss -ltnp | grep {PORT}' shows what is holding it.\n")
        raise SystemExit(1)

    app.run(host=host, port=PORT, threaded=True, debug=False)


if __name__ == "__main__":
    main()
