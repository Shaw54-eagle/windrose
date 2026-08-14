"""
strategies.py — the Strategy Lab.

Backtests a few CLASSIC systematic strategies on one symbol's daily closes and
compares them to buy-and-hold. Purpose: understanding how these mechanics
behave on names you own — NOT signal generation.

Honesty rules baked in:
  • Signals act on the NEXT day (shift 1) — no look-ahead.
  • 5 bps cost charged per position change — no free trading.
  • Stats reported against buy-and-hold, including time-in-market,
    because being in cash half the time is a real difference.
  • A backtest is a description of one past. It overfits by existence.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

TRADING_DAYS = 252
COST = 0.0005          # 5 bps per position change


def _rsi_series(closes: pd.Series, period: int = 2) -> pd.Series:
    delta = closes.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    ag = gain.ewm(alpha=1 / period, adjust=False).mean()
    al = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = ag / al.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _positions(closes: pd.Series, strategy: str) -> pd.Series:
    """1 = long, 0 = cash. Computed on today's data, applied tomorrow."""
    if strategy == "buy_hold":
        pos = pd.Series(1.0, index=closes.index)
    elif strategy == "sma_cross":
        s50 = closes.rolling(50).mean()
        s200 = closes.rolling(200).mean()
        pos = (s50 > s200).astype(float)
    elif strategy == "tsmom":
        # 12-month momentum, skipping the most recent month
        r = closes.shift(21) / closes.shift(252) - 1
        pos = (r > 0).astype(float)
    elif strategy == "rsi2":
        rsi = _rsi_series(closes, 2)
        pos = pd.Series(np.nan, index=closes.index)
        pos[rsi < 10] = 1.0
        pos[rsi > 70] = 0.0
        pos = pos.ffill().fillna(0.0)
    else:
        raise ValueError(strategy)
    return pos.shift(1).fillna(0.0)          # act next day


def _stats(eq: pd.Series, daily: pd.Series, pos: pd.Series) -> dict:
    n = len(daily)
    if n < 30 or eq.iloc[-1] <= 0:
        return {}
    yrs = n / TRADING_DAYS
    total = eq.iloc[-1] - 1
    cagr = eq.iloc[-1] ** (1 / yrs) - 1
    vol = daily.std(ddof=1) * np.sqrt(TRADING_DAYS)
    sharpe = (daily.mean() * TRADING_DAYS) / vol if vol > 0 else np.nan
    peak = eq.cummax()
    mdd = float((eq / peak - 1).min())
    flips = int((pos.diff().abs() > 0).sum())
    return {
        "total_pct": round(total * 100, 1),
        "cagr_pct": round(cagr * 100, 2),
        "vol_pct": round(vol * 100, 1),
        "sharpe": round(float(sharpe), 2) if not np.isnan(sharpe) else None,
        "max_dd_pct": round(mdd * 100, 1),
        "exposure_pct": round(float(pos.mean()) * 100, 0),
        "trades": flips,
    }


STRATEGIES = {
    "buy_hold": "Buy & hold",
    "sma_cross": "SMA 50/200 cross",
    "tsmom": "12-1 momentum",
    "rsi2": "RSI(2) mean-reversion",
}


def backtest(symbol: str, closes: pd.Series, points: int = 160) -> dict:
    closes = closes.dropna()
    if len(closes) < 300:
        return {"ok": False, "note": "Needs ~300+ trading days of history."}
    daily_ret = closes.pct_change().fillna(0.0)

    out_rows, curves = [], {}
    for key, label in STRATEGIES.items():
        pos = _positions(closes, key)
        strat_ret = pos * daily_ret - (pos.diff().abs().fillna(0.0)) * COST
        eq = (1 + strat_ret).cumprod()
        st = _stats(eq, strat_ret, pos)
        if not st:
            continue
        st.update({"key": key, "label": label})
        out_rows.append(st)
        step = max(1, len(eq) // points)
        curves[key] = [round(float(v), 4) for v in eq.iloc[::step].tolist()]

    dates = closes.index[::max(1, len(closes) // points)]
    return {
        "ok": True, "symbol": symbol,
        "window": f"{str(closes.index[0])[:10]} → {str(closes.index[-1])[:10]}",
        "cost_bps": COST * 1e4,
        "rows": out_rows,
        "curves": curves,
        "dates": [str(d)[:10] for d in dates],
        "read": ("Signals execute next-day and pay 5 bps per flip. These are the classic "
                 "mechanics, shown so you can see how they behave on names you own — a good "
                 "backtest here is a description of one past, not a promise. If a strategy "
                 "only wins by sitting in cash through one crash, that's luck wearing a suit."),
    }
