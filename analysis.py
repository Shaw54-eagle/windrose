"""
analysis.py — v2 of the math behind "Analysis".

Everything is deterministic and computed from price history. No model, no LLM.
Any number on screen can be recomputed by hand from daily bars.

New in v2:
  Per stock : MACD, EWMA volatility, 52-week range position, max drawdown,
              Sharpe ratio, and a transparent 0-100 "conditions score".
  Portfolio : historical VaR + CVaR (expected shortfall) from the actual
              return distribution, per-position risk contribution,
              diversification ratio, portfolio max drawdown.

The conditions score is DESCRIPTIVE — a weighted summary of measurable state
(trend, momentum, relative strength, risk, stretch). It is not a buy/sell
signal and does not predict anything. Weights are documented in SCORE_WEIGHTS.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

TRADING_DAYS = 252
EWMA_LAMBDA = 0.94          # RiskMetrics decay for EWMA volatility

# Conditions-score weights (must sum to 1.0). Documented on the dashboard too.
SCORE_WEIGHTS = {
    "trend":     0.25,      # price vs SMA20/50 + MACD direction
    "momentum":  0.25,      # RSI vs 50 + 20d return
    "rel":       0.20,      # 20d/60d excess return vs SPY
    "risk":      0.15,      # volatility + drawdown penalty (calm = higher)
    "stretch":   0.15,      # Bollinger %b extremes penalty (mid-band = higher)
}


# --------------------------------------------------------------------------- #
#  Primitive indicators
# --------------------------------------------------------------------------- #

def sma(closes: np.ndarray, period: int) -> float:
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period:
        return float("nan")
    return float(closes[-period:].mean())


def sma_series(closes: np.ndarray, period: int) -> np.ndarray:
    """Rolling SMA aligned to closes (nan until warm)."""
    s = pd.Series(closes, dtype=float).rolling(period).mean()
    return s.to_numpy()


def ema_series(closes: np.ndarray, period: int) -> np.ndarray:
    return pd.Series(closes, dtype=float).ewm(span=period, adjust=False).mean().to_numpy()


def rsi(closes: np.ndarray, period: int = 14) -> float:
    """Wilder's RSI, 0-100."""
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period + 1:
        return float("nan")
    delta = np.diff(closes)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)
    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    for i in range(period, len(delta)):
        avg_gain = (avg_gain * (period - 1) + gain[i]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def macd(closes: np.ndarray) -> dict:
    """MACD(12,26,9): line, signal, histogram, and whether histogram is rising."""
    closes = np.asarray(closes, dtype=float)
    if len(closes) < 35:
        return {"line": float("nan"), "signal": float("nan"),
                "hist": float("nan"), "hist_rising": None}
    e12, e26 = ema_series(closes, 12), ema_series(closes, 26)
    line = e12 - e26
    signal = pd.Series(line).ewm(span=9, adjust=False).mean().to_numpy()
    hist = line - signal
    rising = bool(hist[-1] > hist[-2]) if len(hist) > 1 else None
    return {"line": float(line[-1]), "signal": float(signal[-1]),
            "hist": float(hist[-1]), "hist_rising": rising}


def atr(high, low, close, period: int = 14) -> float:
    high, low, close = (np.asarray(x, dtype=float) for x in (high, low, close))
    if len(close) < period + 1:
        return float("nan")
    prev_close = close[:-1]
    tr = np.maximum.reduce([
        high[1:] - low[1:],
        np.abs(high[1:] - prev_close),
        np.abs(low[1:] - prev_close),
    ])
    a = tr[:period].mean()
    for i in range(period, len(tr)):
        a = (a * (period - 1) + tr[i]) / period
    return float(a)


def bollinger(closes: np.ndarray, period: int = 20, num_std: float = 2.0) -> dict:
    closes = np.asarray(closes, dtype=float)
    if len(closes) < period:
        return {"pct_b": float("nan"), "bandwidth": float("nan")}
    w = closes[-period:]
    mid, sd = w.mean(), w.std(ddof=0)
    upper, lower = mid + num_std * sd, mid - num_std * sd
    last = closes[-1]
    pct_b = (last - lower) / (upper - lower) if upper != lower else float("nan")
    bw = (upper - lower) / mid if mid else float("nan")
    return {"pct_b": float(pct_b), "bandwidth": float(bw)}


def pct_return(closes: np.ndarray, lookback: int) -> float:
    closes = np.asarray(closes, dtype=float)
    if len(closes) <= lookback or closes[-(lookback + 1)] == 0:
        return float("nan")
    return float((closes[-1] / closes[-(lookback + 1)] - 1) * 100)


def annualized_vol(closes: np.ndarray, lookback: int = 30) -> float:
    """Plain annualized vol from daily log returns, percent."""
    closes = np.asarray(closes, dtype=float)
    if len(closes) < lookback + 1:
        lookback = len(closes) - 1
    if lookback < 2:
        return float("nan")
    rets = np.diff(np.log(closes[-(lookback + 1):]))
    return float(rets.std(ddof=1) * np.sqrt(TRADING_DAYS) * 100)


def ewma_vol(closes: np.ndarray, lam: float = EWMA_LAMBDA) -> float:
    """EWMA (RiskMetrics) annualized volatility, percent. Reacts faster to
    recent turbulence than an equal-weighted window."""
    closes = np.asarray(closes, dtype=float)
    if len(closes) < 30:
        return float("nan")
    rets = np.diff(np.log(closes))
    var = rets[:20].var(ddof=0)          # seed with first month
    for r in rets[20:]:
        var = lam * var + (1 - lam) * r * r
    return float(np.sqrt(var) * np.sqrt(TRADING_DAYS) * 100)


def max_drawdown(closes: np.ndarray) -> float:
    """Deepest peak-to-trough decline over the window, percent (negative)."""
    closes = np.asarray(closes, dtype=float)
    if len(closes) < 2:
        return float("nan")
    peak = np.maximum.accumulate(closes)
    dd = closes / peak - 1
    return float(dd.min() * 100)


def sharpe(closes: np.ndarray, lookback: int = 120) -> float:
    """Annualized return / annualized vol over the window, rf = 0.
    A crude return-per-unit-of-risk gauge, not a performance claim."""
    closes = np.asarray(closes, dtype=float)
    if len(closes) < 30:
        return float("nan")
    rets = np.diff(np.log(closes[-(lookback + 1):]))
    sd = rets.std(ddof=1)
    if sd == 0:
        return float("nan")
    return float((rets.mean() * TRADING_DAYS) / (sd * np.sqrt(TRADING_DAYS)))


def range_52w(closes: np.ndarray) -> dict:
    """Where price sits in its 52-week (or available) range: 0=low, 1=high."""
    closes = np.asarray(closes, dtype=float)
    w = closes[-TRADING_DAYS:] if len(closes) >= TRADING_DAYS else closes
    hi, lo = float(w.max()), float(w.min())
    pos = (closes[-1] - lo) / (hi - lo) if hi != lo else float("nan")
    return {"high": hi, "low": lo, "pos": float(pos)}


# --------------------------------------------------------------------------- #
#  Conditions score (0-100, transparent weights)
# --------------------------------------------------------------------------- #

def _clip01(x):
    return float(np.clip(x, 0.0, 1.0))


def conditions_score(price, s20, s50, macd_d, rsi_v, mom20,
                     rs20, rs60, vol_pct, dd_pct, pct_b) -> dict:
    """Each sub-score is 0-100 from simple, documented rules; the total is the
    weighted sum. Descriptive summary of current state — NOT a recommendation."""
    subs = {}

    # trend: above/below SMAs + MACD histogram direction
    t = 50.0
    if not np.isnan(s20) and not np.isnan(s50) and price:
        above20 = price > s20
        above50 = price > s50
        aligned = s20 > s50
        t = 20 + 25 * above20 + 25 * above50 + 15 * aligned
        if macd_d.get("hist_rising") is True:
            t += 15
        elif macd_d.get("hist_rising") is False:
            t -= 10
    subs["trend"] = _clip01(t / 100) * 100

    # momentum: RSI centered at 50 + 20d return contribution
    m = 50.0
    if not np.isnan(rsi_v):
        m = (rsi_v - 50) * 1.6 + 50          # RSI 30->18, 50->50, 70->82
    if not np.isnan(mom20):
        m += np.clip(mom20, -10, 10) * 1.5   # ±10% move shifts ±15 pts
    subs["momentum"] = _clip01(m / 100) * 100

    # relative strength vs SPY: 20d (2/3) + 60d (1/3), ±10% excess saturates
    r = 50.0
    if not np.isnan(rs20):
        r = 50 + np.clip(rs20, -10, 10) * 3.3
        if not np.isnan(rs60):
            r = (2 * r + (50 + np.clip(rs60, -15, 15) * 2.2)) / 3
    subs["rel"] = _clip01(r / 100) * 100

    # risk: calm = high score. 15% vol ≈ 90, 40% ≈ 40, 60%+ ≈ 20. Deep drawdown subtracts.
    k = 50.0
    if not np.isnan(vol_pct):
        k = np.interp(vol_pct, [10, 15, 25, 40, 60, 90], [95, 90, 70, 40, 20, 5])
    if not np.isnan(dd_pct):
        k -= np.clip(abs(dd_pct) - 10, 0, 30) * 0.8   # >10% drawdown starts to bite
    subs["risk"] = _clip01(k / 100) * 100

    # stretch: mid-band = high; hugging either band = low (works both directions)
    s = 50.0
    if not np.isnan(pct_b):
        s = 100 - abs(pct_b - 0.5) * 160     # %b 0.5 -> 100, 0 or 1 -> 20
    subs["stretch"] = _clip01(s / 100) * 100

    total = sum(subs[k2] * w for k2, w in SCORE_WEIGHTS.items())
    label = ("strong" if total >= 70 else
             "constructive" if total >= 55 else
             "mixed" if total >= 45 else
             "weak" if total >= 30 else "poor")
    return {"total": round(total, 1), "label": label,
            "components": {k2: round(v, 0) for k2, v in subs.items()},
            "weights": SCORE_WEIGHTS}


# --------------------------------------------------------------------------- #
#  Per-stock snapshot
# --------------------------------------------------------------------------- #

def per_stock(symbol: str, hist: pd.DataFrame, bench_closes: np.ndarray | None = None) -> dict:
    close = hist["Close"].to_numpy(dtype=float)
    high = hist["High"].to_numpy(dtype=float) if "High" in hist else close
    low = hist["Low"].to_numpy(dtype=float) if "Low" in hist else close
    vol = hist["Volume"].to_numpy(dtype=float) if "Volume" in hist else None

    price = float(close[-1])
    s20, s50 = sma(close, 20), sma(close, 50)
    r = rsi(close, 14)
    md = macd(close)
    bb = bollinger(close, 20, 2)
    rng = range_52w(close)

    mom5, mom20, mom60 = pct_return(close, 5), pct_return(close, 20), pct_return(close, 60)
    vol_pct = annualized_vol(close, 30)
    evol = ewma_vol(close)
    dd = max_drawdown(close)
    shp = sharpe(close)
    atr_val = atr(high, low, close, 14)
    atr_pct = (atr_val / price * 100) if (price and not np.isnan(atr_val)) else float("nan")

    vol_ratio = float("nan")
    if vol is not None and len(vol) >= 21:
        avg20 = vol[-21:-1].mean()
        vol_ratio = float(vol[-1] / avg20) if avg20 else float("nan")

    rs20 = rs60 = float("nan")
    if bench_closes is not None and len(bench_closes) == len(close):
        b20, b60 = pct_return(bench_closes, 20), pct_return(bench_closes, 60)
        if not (np.isnan(mom20) or np.isnan(b20)):
            rs20 = mom20 - b20
        if not (np.isnan(mom60) or np.isnan(b60)):
            rs60 = mom60 - b60

    score = conditions_score(price, s20, s50, md, r, mom20, rs20, rs60,
                             (evol if not np.isnan(evol) else vol_pct), dd, bb["pct_b"])

    # ---- labels ----
    if not (np.isnan(s20) or np.isnan(s50)):
        if price > s20 > s50:
            trend = "uptrend"
        elif price < s20 < s50:
            trend = "downtrend"
        elif price > s20:
            trend = "above short-term avg"
        else:
            trend = "below short-term avg"
    else:
        trend = "n/a"

    if np.isnan(r):
        mom_label = "n/a"
    elif r >= 70:
        mom_label = "overbought"
    elif r >= 55:
        mom_label = "strong"
    elif r >= 45:
        mom_label = "neutral"
    elif r > 30:
        mom_label = "weak"
    else:
        mom_label = "oversold"

    use_vol = evol if not np.isnan(evol) else vol_pct
    if np.isnan(use_vol):
        vol_label = "n/a"
    elif use_vol >= 40:
        vol_label = "very high"
    elif use_vol >= 25:
        vol_label = "elevated"
    elif use_vol >= 12:
        vol_label = "normal"
    else:
        vol_label = "low"

    rs_label = "n/a"
    if not np.isnan(rs20):
        rs_label = ("outperforming SPY" if rs20 > 1 else
                    "underperforming SPY" if rs20 < -1 else "tracking SPY")

    summary = _stock_summary(trend, mom_label, r, vol_label, rs_label, rs20, rng["pos"], dd)

    return {
        "symbol": symbol,
        "price": round(price, 2),
        "sma20": _r(s20), "sma50": _r(s50),
        "rsi": _r(r, 1),
        "macd_hist": _r(md["hist"], 3), "macd_rising": md["hist_rising"],
        "mom_5d": _r(mom5, 2), "mom_20d": _r(mom20, 2), "mom_60d": _r(mom60, 2),
        "vol_annual_pct": _r(vol_pct, 1), "ewma_vol_pct": _r(evol, 1),
        "max_drawdown_pct": _r(dd, 1), "sharpe": _r(shp, 2),
        "atr": _r(atr_val, 2), "atr_pct": _r(atr_pct, 2),
        "bb_pct_b": _r(bb["pct_b"], 2),
        "vol_ratio": _r(vol_ratio, 2),
        "rs_20d": _r(rs20, 2), "rs_60d": _r(rs60, 2),
        "range_52w_pos": _r(rng["pos"], 2),
        "high_52w": _r(rng["high"]), "low_52w": _r(rng["low"]),
        "trend": trend, "momentum": mom_label,
        "volatility": vol_label, "relative_strength": rs_label,
        "score": score,
        "summary": summary,
    }


def _stock_summary(trend, mom_label, r, vol_label, rs_label, rs20, pos52, dd) -> str:
    parts = []
    parts.append(trend.capitalize() if trend != "n/a" else "Trend n/a")
    if not np.isnan(r):
        parts.append(f"{mom_label} momentum (RSI {r:.0f})")
    if vol_label != "n/a":
        parts.append(f"{vol_label} volatility")
    if rs_label != "n/a" and not np.isnan(rs20):
        parts.append(f"{rs_label} by {abs(rs20):.0f}% over 20d")
    if not np.isnan(pos52):
        parts.append(f"sits {pos52*100:.0f}% up its 52-week range")
    if not np.isnan(dd) and dd < -15:
        parts.append(f"max drawdown {dd:.0f}%")
    return ", ".join(parts) + "."


# --------------------------------------------------------------------------- #
#  Portfolio-level risk
# --------------------------------------------------------------------------- #

def portfolio(holdings: list[dict], hist_close: pd.DataFrame,
              live_prices: dict | None = None, bench: str = "SPY") -> dict:
    live_prices = live_prices or {}
    # only positions with real shares count toward the book
    active = [h for h in holdings if float(h.get("shares", 0)) > 0]
    syms = [h["symbol"] for h in active if h["symbol"] in hist_close.columns]
    if not syms:
        return {"ok": False, "reason": "no sized positions with price history yet"}

    # ---- valuation & weights ----
    rows, total_val, total_cost = [], 0.0, 0.0
    for h in active:
        s = h["symbol"]
        if s not in hist_close.columns:
            continue
        px = float(live_prices.get(s, hist_close[s].dropna().iloc[-1]))
        shares = float(h.get("shares", 0))
        cost = float(h.get("cost_basis", 0))
        mv = px * shares
        basis = cost * shares
        total_val += mv
        total_cost += basis
        rows.append({"symbol": s, "shares": shares, "price": round(px, 2),
                     "cost_basis": cost, "market_value": round(mv, 2),
                     "pl_dollar": round(mv - basis, 2),
                     "pl_pct": round((px / cost - 1) * 100, 2) if cost else None})
    if total_val <= 0:
        return {"ok": False, "reason": "positions have no market value"}

    for row in rows:
        row["weight_pct"] = round(row["market_value"] / total_val * 100, 1)

    # ---- concentration ----
    weights = np.array([row["market_value"] / total_val for row in rows])
    hhi = float((weights ** 2).sum())
    eff_n = float(1 / hhi) if hhi else float("nan")
    top = sorted(rows, key=lambda x: x["weight_pct"], reverse=True)
    max_w = top[0]["weight_pct"] if top else 0
    top2_w = round(sum(x["weight_pct"] for x in top[:2]), 1)

    # ---- returns matrix ----
    order = [row["symbol"] for row in rows]
    cols = order + ([bench] if bench in hist_close.columns else [])
    px = hist_close[cols].dropna()
    rets = np.log(px / px.shift(1)).dropna()

    corr = rets[order].corr().round(2)
    corr_matrix = {s: corr[s].to_dict() for s in order}
    worst_pair, worst_corr = None, -2.0
    for i in range(len(order)):
        for j in range(i + 1, len(order)):
            c = float(corr.iloc[i, j])
            if c > worst_corr:
                worst_corr, worst_pair = c, (order[i], order[j])

    # ---- portfolio series, vol, beta ----
    w = np.array([row["market_value"] for row in rows], dtype=float)
    w = w / w.sum()
    R = rets[order].to_numpy()
    port_rets = R @ w
    daily_sigma = float(port_rets.std(ddof=1))
    port_vol_annual = daily_sigma * np.sqrt(TRADING_DAYS) * 100

    # EWMA portfolio vol (reacts faster to the recent regime)
    var_e = port_rets[:20].var(ddof=0) if len(port_rets) > 25 else daily_sigma ** 2
    for rr in port_rets[20:]:
        var_e = EWMA_LAMBDA * var_e + (1 - EWMA_LAMBDA) * rr * rr
    ewma_port_vol = float(np.sqrt(var_e) * np.sqrt(TRADING_DAYS) * 100)

    beta = float("nan")
    if bench in hist_close.columns and len(port_rets) > 5:
        b = rets[bench].to_numpy()
        var_b = b.var(ddof=1)
        beta = float(np.cov(port_rets, b, ddof=1)[0, 1] / var_b) if var_b else float("nan")

    # ---- VaR / CVaR: parametric AND historical ----
    z95, z99 = 1.6449, 2.3263
    var95_param = z95 * daily_sigma
    var99_param = z99 * daily_sigma
    q05 = float(np.percentile(port_rets, 5))          # historical 95% VaR (a return)
    q01 = float(np.percentile(port_rets, 1))
    tail = port_rets[port_rets <= q05]
    cvar95 = float(tail.mean()) if len(tail) else q05  # expected shortfall

    # ---- risk contribution per position ----
    cov = np.cov(R, rowvar=False, ddof=1)
    cov = np.atleast_2d(cov)
    port_var = float(w @ cov @ w)
    contrib = {}
    if port_var > 0:
        mc = cov @ w                                  # marginal contributions
        rc = w * mc / port_var                        # sums to 1
        contrib = {order[i]: round(float(rc[i]) * 100, 1) for i in range(len(order))}

    # ---- diversification ratio ----
    indiv_vols = np.sqrt(np.diag(cov))
    div_ratio = float((w @ indiv_vols) / np.sqrt(port_var)) if port_var > 0 else float("nan")

    # ---- portfolio max drawdown (of the weighted book over the window) ----
    curve = np.exp(np.cumsum(port_rets))
    peak = np.maximum.accumulate(curve)
    port_mdd = float((curve / peak - 1).min() * 100)

    # ---- the same three arrays, thinned, for the panel charts -------------
    # Nothing new is computed here. The equity curve and the drawdown beneath
    # it are what max_drawdown_pct is already read off, and the histogram is
    # the distribution the historical VaR percentile is already taken from —
    # so the picture and the number cannot disagree, which is the only reason
    # to draw it from the same arrays rather than fetch prices again.
    series = {}
    if curve.size and curve[0]:
        hist_counts, hist_edges = np.histogram(port_rets * 100, bins=29)
        series = {
            "equity": _thin(curve / curve[0] * 100, 150),
            "drawdown": _thin((curve / peak - 1) * 100, 150),
            "returns": {
                "counts": [int(c) for c in hist_counts],
                "edges": [round(float(e), 3) for e in hist_edges],
                "var95_pct": _r(q05 * 100, 2),
                "cvar95_pct": _r(cvar95 * 100, 2),
            },
        }

    risk_read = _portfolio_summary(eff_n, max_w, worst_pair, worst_corr,
                                   ewma_port_vol, beta,
                                   q05 * 100, q05 * total_val,
                                   cvar95 * 100, cvar95 * total_val,
                                   contrib, div_ratio, port_mdd)

    return {
        "ok": True,
        "total_value": round(total_val, 2),
        "total_cost": round(total_cost, 2),
        "total_pl_dollar": round(total_val - total_cost, 2),
        "total_pl_pct": round((total_val / total_cost - 1) * 100, 2) if total_cost else None,
        "positions": rows,
        "concentration": {
            "max_weight_pct": max_w,
            "top2_weight_pct": top2_w,
            "hhi": round(hhi, 3),
            "effective_holdings": round(eff_n, 2),
            "n_positions": len(rows),
        },
        "correlation": corr_matrix,
        "highest_pair": {"pair": worst_pair, "corr": round(worst_corr, 2)} if worst_pair else None,
        "beta": _r(beta, 2),
        "vol_annual_pct": _r(port_vol_annual, 1),
        "ewma_vol_pct": _r(ewma_port_vol, 1),
        "max_drawdown_pct": _r(port_mdd, 1),
        "series": series,
        "diversification_ratio": _r(div_ratio, 2),
        "risk_contribution": contrib,
        "var": {
            "hist_95_pct": _r(abs(q05) * 100, 2),
            "hist_95_dollar": _r(abs(q05) * total_val, 2),
            "hist_99_pct": _r(abs(q01) * 100, 2),
            "hist_99_dollar": _r(abs(q01) * total_val, 2),
            "cvar_95_pct": _r(abs(cvar95) * 100, 2),
            "cvar_95_dollar": _r(abs(cvar95) * total_val, 2),
            "param_95_pct": _r(var95_param * 100, 2),
            "param_95_dollar": _r(var95_param * total_val, 2),
            "param_99_pct": _r(var99_param * 100, 2),
            "param_99_dollar": _r(var99_param * total_val, 2),
        },
        "risk_read": risk_read,
        "risk_read_plain": _portfolio_summary_plain(
            eff_n, max_w, worst_pair, worst_corr, beta,
            q05 * total_val, contrib, port_mdd),
    }


def _portfolio_summary_plain(eff_n, max_w, pair, corr, beta,
                             var95_d, contrib, mdd) -> str:
    """Same findings as the full read, without the vocabulary.

    Simple mode hides beta, volatility and VaR from the panel, so repeating
    those words in the summary underneath would defeat the point.
    """
    bits = []
    if not np.isnan(eff_n):
        if eff_n < 1.5:
            bits.append(f"Your money is riding on very few things — the biggest "
                        f"position is {max_w:.0f}% of everything you own.")
        elif eff_n < 3:
            bits.append(f"You own a handful of things, but they behave like about "
                        f"{eff_n:.1f} separate bets.")
        else:
            bits.append(f"Reasonably spread out — about {eff_n:.1f} genuinely "
                        f"separate bets.")
    if pair and corr > 0.6:
        bits.append(f"{pair[0]} and {pair[1]} tend to rise and fall together, so "
                    f"owning both is closer to one bet than two.")
    if contrib:
        top_sym = max(contrib, key=contrib.get)
        if contrib[top_sym] >= 60:
            bits.append(f"{top_sym} decides most of what happens to this "
                        f"portfolio — {contrib[top_sym]:.0f}% of the movement comes from it.")
    if not np.isnan(beta):
        if beta > 1.1:
            bits.append("When the market moves, you tend to move more than it does.")
        elif beta < 0.9:
            bits.append("When the market moves, you tend to move less than it does.")
        else:
            bits.append("You tend to move roughly in step with the market.")
    if var95_d and not np.isnan(var95_d):
        bits.append(f"On a bad day — the worst one day in twenty over the past six "
                    f"months — this book lost around ${abs(var95_d):,.0f}.")
    if not np.isnan(mdd) and mdd < -15:
        bits.append(f"Its deepest fall in that window was {mdd:.0f}%, so expect "
                    f"stretches like that again.")
    return " ".join(bits)


def _portfolio_summary(eff_n, max_w, pair, corr, vol, beta,
                       var95_pct, var95_d, cvar_pct, cvar_d,
                       contrib, div_ratio, mdd) -> str:
    bits = []
    if not np.isnan(eff_n):
        if eff_n < 1.5:
            bits.append(f"Highly concentrated — effectively {eff_n:.1f} holdings "
                        f"(largest position is {max_w:.0f}% of the book).")
        elif eff_n < 3:
            bits.append(f"Concentrated — effectively {eff_n:.1f} independent holdings.")
        else:
            bits.append(f"Reasonably spread — effectively {eff_n:.1f} holdings.")
    if pair and corr > 0.6:
        bits.append(f"{pair[0]} and {pair[1]} move together (corr {corr:.2f}) — "
                    f"closer to one bet than two.")
    if contrib:
        top_sym = max(contrib, key=contrib.get)
        if contrib[top_sym] >= 60:
            bits.append(f"{top_sym} alone drives {contrib[top_sym]:.0f}% of portfolio risk.")
    if not np.isnan(div_ratio) and div_ratio < 1.15:
        bits.append(f"Diversification ratio {div_ratio:.2f} — holdings barely offset each other.")
    if not np.isnan(vol):
        bits.append(f"Current-regime volatility ~{vol:.0f}%/yr.")
    if not np.isnan(beta):
        if beta > 1.1:
            tilt = "swings more than the S&P"
        elif beta < 0.9:
            tilt = "swings less than the S&P"
        else:
            tilt = "swings about as much as the S&P"
        bits.append(f"Beta {beta:.2f} — {tilt}.")
    if not np.isnan(var95_pct):
        bits.append(f"On the worst 1-in-20 days of the past six months you lost more than "
                    f"${abs(var95_d):,.0f} ({abs(var95_pct):.1f}%); when that happened the "
                    f"average hit was ${abs(cvar_d):,.0f}.")
    if not np.isnan(mdd) and mdd < -10:
        bits.append(f"The book's deepest slide in the window was {mdd:.0f}%.")
    return " ".join(bits)


# --------------------------------------------------------------------------- #
#  Chart series (for the frontend canvases)
# --------------------------------------------------------------------------- #

def chart_series(hist: pd.DataFrame, points: int = 130) -> dict:
    """Close + SMA20/50 series (tail), ready for a canvas line chart."""
    close = hist["Close"].to_numpy(dtype=float)
    s20 = sma_series(close, 20)
    s50 = sma_series(close, 50)
    idx = [str(d)[:10] for d in hist.index[-points:]]
    def tail(a):
        t = a[-points:]
        return [None if (x is None or np.isnan(x)) else round(float(x), 2) for x in t]
    return {"dates": idx, "close": tail(close), "sma20": tail(s20), "sma50": tail(s50)}


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #

def _thin(arr, n=150, ndigits=3):
    """Evenly spaced sample of a series, last point always kept.

    A canvas 300px wide cannot show 1,300 daily closes, and shipping them
    costs more than the chart is worth. Sampling rather than averaging is
    deliberate: every point drawn is a real observation."""
    a = np.asarray(arr, dtype=float)
    if a.size == 0:
        return []
    if a.size > n:
        idx = np.unique(np.linspace(0, a.size - 1, n).round().astype(int))
        a = a[idx]
    return [None if np.isnan(v) else round(float(v), ndigits) for v in a]


def _r(x, ndigits=2):
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        return round(float(x), ndigits)
    except (TypeError, ValueError):
        return None
