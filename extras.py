"""
extras.py — the second wave of features. Same house rules: deterministic,
honest about data gaps, assumptions visible.

  dividends       : yield, rate, next ex-date, TTM paid, recent history
  total_return    : price P/L + dividends actually received (needs acquired date)
  benchmark       : "same dollars into SPY on the same dates" shadow book
  whatif          : hypothetical share counts -> full portfolio risk recompute
  journal         : trade/decision log with hit-rate stats and chart markers
  earnings_strip  : days-to-earnings countdown across holdings
  export_csv      : one-file dump of holdings + metrics
  chain           : the curated supply-chain graph + live quotes for its nodes
"""

from __future__ import annotations
import json, uuid, datetime as dt
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
JOURNAL_FILE = BASE / "journal.json"
CHAIN_FILE = BASE / "supply_chain.json"


def _f(x, default=None):
    try:
        v = float(x)
        if np.isnan(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


# =========================================================================== #
#  DIVIDENDS & TOTAL RETURN
# =========================================================================== #

def dividends(symbol: str, ticker_obj, info: dict, acquired: str | None,
              shares: float, cost_basis: float, price: float | None) -> dict:
    """Dividend profile + (when an acquired date exists) total-return P/L that
    counts the cash the position actually paid you."""
    out = {"symbol": symbol, "ok": True}
    try:
        div = ticker_obj.dividends
        if div is None or len(div) == 0:
            out.update({"pays": False})
            return out
        div.index = pd.to_datetime(div.index).tz_localize(None)
        ttm = float(div[div.index >= (pd.Timestamp.now() - pd.Timedelta(days=370))].sum())
        rate = _f(info.get("dividendRate")) or (ttm if ttm > 0 else None)
        yld = _f(info.get("dividendYield"))
        if yld and yld < 1:      # yfinance sometimes returns 0.029, sometimes 2.9
            yld *= 100
        ex_next = None
        ex = info.get("exDividendDate")
        if ex:
            try:
                ex_dt = dt.datetime.fromtimestamp(ex) if isinstance(ex, (int, float)) else pd.to_datetime(ex)
                if ex_dt.date() >= dt.date.today():
                    ex_next = str(ex_dt.date())
            except Exception:
                pass
        hist = [(str(d.date()), round(float(v), 4)) for d, v in div.tail(8).items()]

        out.update({
            "pays": ttm > 0 or bool(rate),
            "yield_pct": round(yld, 2) if yld else None,
            "rate_annual": round(rate, 2) if rate else None,
            "ttm_per_share": round(ttm, 2),
            "ex_next": ex_next,
            "history": hist,
        })

        # total return since acquisition — only honest with a real date
        if acquired and shares > 0 and cost_basis and price:
            try:
                acq = pd.to_datetime(acquired)
                received_ps = float(div[div.index >= acq].sum())
                received = received_ps * shares
                price_pl = (price - cost_basis) * shares
                total_pl = price_pl + received
                out["total_return"] = {
                    "acquired": acquired,
                    "dividends_received": round(received, 2),
                    "price_pl": round(price_pl, 2),
                    "total_pl": round(total_pl, 2),
                    "total_pl_pct": round(total_pl / (cost_basis * shares) * 100, 2),
                }
            except Exception:
                pass
    except Exception as e:
        out = {"symbol": symbol, "ok": False, "note": f"{type(e).__name__}"}
    return out


def portfolio_income(div_rows: list[dict], holdings: list[dict]) -> dict:
    """Annual dividend income at current rates, across sized positions."""
    total = 0.0
    for h in holdings:
        if float(h.get("shares", 0)) <= 0:
            continue
        d = next((r for r in div_rows if r["symbol"] == h["symbol"]), None)
        if d and d.get("rate_annual"):
            total += d["rate_annual"] * float(h["shares"])
    return {"annual_income": round(total, 2)}


# =========================================================================== #
#  BENCHMARK SHADOW — same dollars into SPY, same dates
# =========================================================================== #

def _bench_series(legs, close: pd.DataFrame, b: pd.Series, points: int = 160) -> dict:
    """The two totals as daily curves: what the book was worth, and what the
    same dollars in SPY were worth, over the price window.

    Each position joins both lines on the day it was acquired and contributes
    nothing before it, so the two lines step up by identical dollars at
    identical moments. That is the property worth having: every gap between
    them is performance, never a deposit."""
    if not legs or b.empty:
        return {}
    idx = b.index
    n = len(idx)
    spy = b.to_numpy(dtype=float)
    book = np.zeros(n)
    shadow = np.zeros(n)
    for sym, shares, spent, spy_entry, e in legs:
        if sym not in close.columns or spy_entry <= 0:
            continue
        px = close[sym].reindex(idx).ffill().bfill().to_numpy(dtype=float)
        book[e:] += np.nan_to_num(px[e:] * shares)
        shadow[e:] += spent / spy_entry * spy[e:]

    step = max(1, n // points)
    keep = list(range(0, n, step))
    if keep[-1] != n - 1:
        keep.append(n - 1)
    return {
        "dates": [str(idx[i].date()) for i in keep],
        "book": [round(float(book[i]), 2) for i in keep],
        "shadow": [round(float(shadow[i]), 2) for i in keep],
    }


def benchmark(holdings: list[dict], close: pd.DataFrame, live: dict,
              bench: str = "SPY") -> dict:
    """For each sized position: the dollars you spent, converted into SPY at
    that day's close, marked to now. Positions without an acquired date fall
    back to the start of the price window — labeled, not hidden."""
    if bench not in close.columns:
        return {"ok": False, "note": "no benchmark history"}
    b = close[bench].dropna()
    if b.empty:
        return {"ok": False, "note": "no benchmark history"}

    rows, approx = [], False
    legs = []                    # (symbol, shares, spent, spy_entry, entry_index)
    tot_cost = tot_now = tot_shadow = 0.0
    for h in holdings:
        shares = float(h.get("shares", 0))
        cost = float(h.get("cost_basis", 0))
        if shares <= 0 or cost <= 0 or h["symbol"] not in close.columns:
            continue
        sym = h["symbol"]
        spent = shares * cost
        px_now = float(live.get(sym, close[sym].dropna().iloc[-1]))
        now_val = shares * px_now

        acq = h.get("acquired")
        if acq:
            try:
                ts = pd.to_datetime(acq)
                bi = b.index.searchsorted(ts)
                bi = min(max(bi, 0), len(b) - 1)
                spy_entry, entry_i, dated = float(b.iloc[bi]), int(bi), True
            except Exception:
                spy_entry, entry_i, dated = float(b.iloc[0]), 0, False
        else:
            spy_entry, entry_i, dated = float(b.iloc[0]), 0, False
        if not dated:
            approx = True

        spy_now = float(b.iloc[-1])
        shadow = spent / spy_entry * spy_now
        rows.append({
            "symbol": sym, "spent": round(spent, 2),
            "now": round(now_val, 2), "shadow": round(shadow, 2),
            "alpha": round(now_val - shadow, 2),
            "dated": dated,
        })
        tot_cost += spent; tot_now += now_val; tot_shadow += shadow
        legs.append((sym, shares, spent, spy_entry, entry_i))

    if not rows:
        return {"ok": False, "note": "no sized positions with cost basis"}

    verdict = tot_now - tot_shadow
    return {
        "ok": True, "rows": rows, "approx": approx,
        "series": _bench_series(legs, close, b),
        "totals": {
            "spent": round(tot_cost, 2), "book": round(tot_now, 2),
            "shadow": round(tot_shadow, 2), "alpha": round(verdict, 2),
            "book_pct": round((tot_now / tot_cost - 1) * 100, 2),
            "shadow_pct": round((tot_shadow / tot_cost - 1) * 100, 2),
        },
        "read": ((f"The same dollars, dropped into SPY on the same dates, would be worth "
                  f"${tot_shadow:,.2f} today vs your ${tot_now:,.2f} — you're "
                  f"{'ahead' if verdict >= 0 else 'behind'} the do-nothing alternative by "
                  f"${abs(verdict):,.2f}.")
                 + (" Positions without an acquired date are measured from the start of the "
                    "price window — add dates (✎ on a holding) for the exact comparison."
                    if approx else "")),
    }


# =========================================================================== #
#  WHAT-IF SANDBOX
# =========================================================================== #

def whatif(current_holdings: list[dict], hypo_shares: dict, close: pd.DataFrame,
           live: dict, portfolio_fn) -> dict:
    """Re-run the full portfolio risk engine with hypothetical share counts.
    Nothing is saved; nothing touches the real book."""
    hypo = []
    seen = set()
    for h in current_holdings:
        s = h["symbol"]
        seen.add(s)
        hypo.append({"symbol": s, "shares": float(hypo_shares.get(s, h.get("shares", 0))),
                     "cost_basis": float(h.get("cost_basis", 0)) or float(live.get(s, 0))})
    for s, sh in hypo_shares.items():
        if s not in seen and s in close.columns:
            hypo.append({"symbol": s, "shares": float(sh),
                         "cost_basis": float(live.get(s, close[s].dropna().iloc[-1]))})
    cur = portfolio_fn(current_holdings, close, live_prices=live)
    new = portfolio_fn(hypo, close, live_prices=live)
    return {"ok": True, "current": cur, "hypothetical": new}


# =========================================================================== #
#  DECISION JOURNAL
# =========================================================================== #

def journal_load() -> list[dict]:
    if JOURNAL_FILE.exists():
        try:
            return json.loads(JOURNAL_FILE.read_text())
        except Exception:
            return []
    return []


def journal_save(entries: list[dict]):
    JOURNAL_FILE.write_text(json.dumps(entries, indent=2))


def journal_add(symbol: str, side: str, reason: str, price: float | None,
                shares: float | None, date: str | None) -> dict:
    entries = journal_load()
    e = {
        "id": uuid.uuid4().hex[:10],
        "date": date or str(dt.date.today()),
        "symbol": symbol.upper(),
        "side": side if side in ("buy", "sell", "note") else "note",
        "price": round(price, 2) if price else None,
        "shares": shares,
        "reason": (reason or "").strip()[:600],
    }
    entries.append(e)
    entries.sort(key=lambda x: x["date"])
    journal_save(entries)
    return e


def journal_delete(entry_id: str) -> bool:
    entries = journal_load()
    n = len(entries)
    entries = [e for e in entries if e["id"] != entry_id]
    journal_save(entries)
    return len(entries) < n


def journal_stats(close: pd.DataFrame, live: dict) -> dict:
    """Hit rate on logged buys/sells, marked to today. A sell 'wins' if the
    price is lower now than when you sold. Small samples lie — the endpoint
    says so rather than hiding it."""
    entries = journal_load()
    graded, wins = 0, 0
    per = {}
    for e in entries:
        s, px = e["symbol"], e.get("price")
        if e["side"] not in ("buy", "sell") or not px:
            continue
        now = _f(live.get(s))
        if now is None and s in close.columns:
            ser = close[s].dropna()
            now = float(ser.iloc[-1]) if len(ser) else None
        if now is None:
            continue
        ret = (now / px - 1) * 100
        win = ret >= 0 if e["side"] == "buy" else ret <= 0
        graded += 1
        wins += 1 if win else 0
        per.setdefault(s, {"graded": 0, "wins": 0})
        per[s]["graded"] += 1
        per[s]["wins"] += 1 if win else 0
        e["_ret_pct"] = round(ret, 1)
        e["_win"] = win
    return {
        "entries": entries,
        "graded": graded, "wins": wins,
        "hit_rate_pct": round(wins / graded * 100, 1) if graded else None,
        "per_symbol": {s: round(v["wins"] / v["graded"] * 100, 0) for s, v in per.items()},
        "note": ("Fewer than 10 graded calls — a hit rate this early is noise, not skill."
                 if 0 < graded < 10 else None),
    }


# =========================================================================== #
#  EARNINGS COUNTDOWN
# =========================================================================== #

def earnings_strip(symbols: list[str], outlook_fn) -> list[dict]:
    rows = []
    today = dt.date.today()
    for s in symbols:
        o = outlook_fn(s)
        d = o.get("next_earnings")
        if not d:
            continue
        try:
            ed = dt.date.fromisoformat(str(d)[:10])
            days = (ed - today).days
            if days < -3:
                continue
            rows.append({"symbol": s, "date": str(ed), "days": days})
        except Exception:
            continue
    rows.sort(key=lambda r: r["days"])
    return rows


# =========================================================================== #
#  CSV EXPORT
# =========================================================================== #

def export_csv(holdings: list[dict], analysis: dict, live: dict) -> str:
    lines = ["symbol,shares,cost_basis,acquired,price,market_value,pl_dollar,pl_pct,"
             "rsi,mom_20d_pct,ewma_vol_pct,max_dd_pct,sharpe,score"]
    stocks = {s["symbol"]: s for s in analysis.get("stocks", [])}
    for h in holdings:
        s = h["symbol"]
        st = stocks.get(s, {})
        px = _f(live.get(s)) or st.get("price")
        shares = float(h.get("shares", 0))
        cost = float(h.get("cost_basis", 0))
        mv = px * shares if px else None
        pl = (px - cost) * shares if (px and cost) else None
        plp = (px / cost - 1) * 100 if (px and cost) else None
        sc = (st.get("score") or {}).get("total")
        row = [s, shares, cost, h.get("acquired") or "", px,
               round(mv, 2) if mv is not None else "",
               round(pl, 2) if pl is not None else "",
               round(plp, 2) if plp is not None else "",
               st.get("rsi"), st.get("mom_20d"), st.get("ewma_vol_pct"),
               st.get("max_drawdown_pct"), st.get("sharpe"), sc]
        lines.append(",".join("" if v is None else str(v) for v in row))
    p = analysis.get("portfolio", {})
    if p.get("ok"):
        lines.append("")
        lines.append("portfolio_metric,value")
        c = p.get("concentration", {})
        v = p.get("var", {})
        for k, val in [("total_value", p.get("total_value")), ("total_pl_pct", p.get("total_pl_pct")),
                       ("effective_holdings", c.get("effective_holdings")), ("beta", p.get("beta")),
                       ("ewma_vol_pct", p.get("ewma_vol_pct")), ("max_drawdown_pct", p.get("max_drawdown_pct")),
                       ("var95_hist_dollar", v.get("hist_95_dollar")), ("cvar95_dollar", v.get("cvar_95_dollar")),
                       ("diversification_ratio", p.get("diversification_ratio"))]:
            lines.append(f"{k},{val}")
    return "\n".join(lines)


# =========================================================================== #
#  SUPPLY CHAIN
# =========================================================================== #

_TAG_RE = None


def _scrub(value):
    """Strip anything HTML-ish out of curated map text.

    supply_chain.json is community-editable and pull requests against it are
    invited, so its strings are untrusted input. The browser renders labels and
    relationship text into innerHTML; a crafted label was able to execute
    arbitrary JavaScript with access to the local API. Escaping happens at
    render too — this is the second lock.
    """
    global _TAG_RE
    if not isinstance(value, str):
        return value
    if _TAG_RE is None:
        import re as _re
        _TAG_RE = _re.compile(r"<[^>]*>")
    return _TAG_RE.sub("", value).replace("<", "").replace(">", "")


_URL_KEYS = ("url", "href", "link", "source_url")
_URL_OK = None
_BAD_SCHEME = None


def _scrub_url(value: str) -> str:
    """Only http(s) survives. Everything else becomes empty.

    Stripping angle brackets does nothing to `javascript:alert(1)` once it lands
    in an href, so URL fields need a scheme check rather than tag removal. Also
    kills `data:`, `vbscript:`, `file:` and protocol-relative `//evil.com`.
    """
    global _URL_OK
    if _URL_OK is None:
        import re as _re
        _URL_OK = _re.compile(r"^https?://[^\s]+$", _re.I)
    v = _scrub(value).strip()
    return v if _URL_OK.match(v) else ""


def _has_bad_scheme(value: str) -> bool:
    """Does this string lead with a scheme that executes when clicked?

    Browsers tolerate whitespace, tabs, newlines and NUL between the scheme and
    the colon, so `java\\tscript:` and ` javascript :` both fire. Strip the
    characters they ignore before deciding.
    """
    global _BAD_SCHEME
    if _BAD_SCHEME is None:
        import re as _re
        _BAD_SCHEME = _re.compile(
            r"^(javascript|data|vbscript|file|blob|about)\s*:", _re.I)
    stripped = "".join(c for c in value if c not in "\t\r\n\x00 ").lstrip()
    return bool(_BAD_SCHEME.match(stripped))


def _scrub_deep(value, key=None):
    """Scrub every string anywhere in the structure, whatever it is called.

    The previous version listed the fields to clean, which fails open the moment
    schema v2 adds one — exactly the mistake that put a script tag in a company
    label. Walking everything means a new field is protected before anyone
    remembers to protect it.
    """
    if isinstance(value, str):
        if key in _URL_KEYS:
            return _scrub_url(value)
        # A URL-bearing field named something we did not anticipate — homepage,
        # docs, ref — is still a URL when it reaches an href. Keying the check
        # off the field name fails open exactly like the old field allowlist
        # did, so judge the value instead.
        return "" if _has_bad_scheme(value) else _scrub(value)
    if isinstance(value, list):
        return [_scrub_deep(v, key) for v in value]
    if isinstance(value, dict):
        return {_scrub(k) if isinstance(k, str) else k: _scrub_deep(v, k)
                for k, v in value.items()}
    return value


def _scrub_chain(data: dict) -> dict:
    """Scrub the whole networks tree, not just nodes and edges.

    Naming the two keys to walk fails open the same way naming the fields did:
    a schema that grows a sibling key — per-network metadata, a provenance
    block — would ship unscrubbed. Walking each network entire means the next
    addition is covered before anyone thinks about it.
    """
    if not isinstance(data, dict):
        return data
    nets = data.get("networks")
    if isinstance(nets, dict):
        data["networks"] = {
            _scrub(k) if isinstance(k, str) else k:
                (_scrub_deep(v) if isinstance(v, dict) else _scrub_deep(v))
            for k, v in nets.items()
        }
    return data


def chain_load() -> dict:
    try:
        return _scrub_chain(json.loads(CHAIN_FILE.read_text()))
    except Exception as e:
        return {"networks": {}, "_error": str(e)}


def chain_tickers(network: dict) -> list[str]:
    out = []
    for n in network.get("nodes", []):
        t = n.get("ticker", n["id"])
        if t:
            out.append(t)
    return out
