"""
models.py — the valuation & simulation workbench.

Same rule as analysis.py: deterministic, recomputable, no LLM. The difference
here is that several of these models are ASSUMPTION-DRIVEN — the output is
only as good as the sliders feeding it. Every assumption is exposed in the UI
and echoed back in the result so nothing is hidden.

  reverse_dcf   : solves for the FCF growth the market's price implies.
                  (The honest DCF — no invented "fair value".)
  comps         : peer multiples -> median-implied values for the target.
  lbo           : paper LBO — entry, leverage, paydown, exit -> IRR / MOIC.
  mna           : merger accretion/dilution on combined EPS.
  statements    : the actual historical 3 statements, key rows, linked.
  monte_carlo   : bootstrap resampling of the portfolio's own joint daily
                  returns (keeps real fat tails + correlations), N paths.
  stress_test   : replays named historical windows on current weights.
"""

from __future__ import annotations
import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _f(x, default=None):
    try:
        if x is None:
            return default
        v = float(x)
        if np.isnan(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


def _r(x, nd=2):
    v = _f(x)
    return None if v is None else round(v, nd)


# =========================================================================== #
#  REVERSE DCF
# =========================================================================== #

def reverse_dcf(f: dict, discount_pct: float = 9.0, terminal_pct: float = 2.5,
                years: int = 10) -> dict:
    """Solve for the constant FCF growth rate over `years` that makes a plain
    two-stage DCF equal today's market cap. Tells you what you're being asked
    to believe at the current price."""
    fcf0 = _f(f.get("fcf"))
    mcap = _f(f.get("mcap"))
    net_debt = _f(f.get("net_debt"), 0.0) or 0.0
    r = discount_pct / 100.0
    gt = terminal_pct / 100.0

    out = {"inputs": {"fcf_ttm": _r(fcf0 and fcf0 / 1e9, 2), "mcap_b": _r(mcap and mcap / 1e9, 2),
                      "net_debt_b": _r(net_debt / 1e9, 2), "discount_pct": discount_pct,
                      "terminal_pct": terminal_pct, "years": years},
           "ok": False}

    if not fcf0 or not mcap or r <= gt:
        out["note"] = ("FCF is negative or missing — a growth-solve isn't meaningful; "
                       "value depends on when/if FCF turns positive."
                       if (fcf0 is None or fcf0 <= 0)
                       else "Discount rate must exceed terminal growth.")
        return out

    def equity_value(g: float) -> float:
        pv = 0.0
        fcf = fcf0
        for t in range(1, years + 1):
            fcf = fcf * (1 + g)
            pv += fcf / (1 + r) ** t
        tv = fcf * (1 + gt) / (r - gt)
        pv += tv / (1 + r) ** years
        return pv - net_debt

    # bisection for g in [-50%, +60%]
    lo, hi = -0.5, 0.6
    if equity_value(hi) < mcap:
        out["note"] = "Even 60%/yr growth for a decade doesn't reach the current price under these assumptions."
        out["ok"] = True
        out["implied_growth_pct"] = None
        return out
    if equity_value(lo) > mcap:
        implied = lo
    else:
        for _ in range(80):
            mid = (lo + hi) / 2
            if equity_value(mid) < mcap:
                lo = mid
            else:
                hi = mid
        implied = (lo + hi) / 2

    # sensitivity grid: discount rate rows x terminal growth cols
    rs = [discount_pct - 2, discount_pct - 1, discount_pct, discount_pct + 1, discount_pct + 2]
    gts = [max(0.5, terminal_pct - 1), terminal_pct, terminal_pct + 1]
    grid = []
    for rr in rs:
        row = {"r": rr, "cells": []}
        for gg in gts:
            sub = reverse_dcf_growth_only(fcf0, mcap, net_debt, rr / 100, gg / 100, years)
            row["cells"].append({"gt": gg, "g": _r(sub is not None and sub * 100, 1)})
        grid.append(row)

    # context: what has FCF actually grown at?
    hist = f.get("fcf_history") or []
    fcf_cagr = None
    if len(hist) >= 3 and hist[0][1] and hist[-1][1] and hist[-1][1] > 0 and hist[0][1] > 0:
        yrs = len(hist) - 1
        fcf_cagr = ((hist[-1][1] / hist[0][1]) ** (1 / yrs) - 1) * 100

    out.update({
        "ok": True,
        "implied_growth_pct": _r(implied * 100, 1),
        "fcf_yield_pct": _r(fcf0 / mcap * 100, 2),
        "hist_fcf_cagr_pct": _r(fcf_cagr, 1),
        "grid": grid, "grid_gts": gts,
        "read": (f"At the current price, a {years}-year DCF only balances if free cash flow "
                 f"grows ~{implied*100:.1f}%/yr (then {terminal_pct}% forever), discounting at "
                 f"{discount_pct}%. "
                 + (f"For reference, FCF actually grew ~{fcf_cagr:.1f}%/yr over the last {len(hist)-1} reported years. "
                    if fcf_cagr is not None else "")
                 + "You judge whether the implied number is believable — that judgment IS the investment decision."),
    })
    return out


def reverse_dcf_growth_only(fcf0, mcap, net_debt, r, gt, years):
    if r <= gt or not fcf0 or fcf0 <= 0:
        return None
    def ev(g):
        pv, fcf = 0.0, fcf0
        for t in range(1, years + 1):
            fcf = fcf * (1 + g)
            pv += fcf / (1 + r) ** t
        return pv + (fcf * (1 + gt) / (r - gt)) / (1 + r) ** years - net_debt
    lo, hi = -0.5, 0.6
    if ev(hi) < mcap:
        return None
    if ev(lo) > mcap:
        return lo
    for _ in range(60):
        mid = (lo + hi) / 2
        if ev(mid) < mcap:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# =========================================================================== #
#  COMPARABLE COMPANY ANALYSIS
# =========================================================================== #

def comps(target: dict, peers: list[dict]) -> dict:
    """Peer multiples table + median-implied values for the target."""
    def row(f):
        return {
            "symbol": f.get("symbol"),
            "mcap_b": _r(_f(f.get("mcap"), 0) / 1e9, 1),
            "pe_t": _r(f.get("pe_t"), 1), "pe_f": _r(f.get("pe_f"), 1),
            "ev_ebitda": _r(f.get("ev_ebitda"), 1),
            "ev_rev": _r((_f(f.get("ev")) / _f(f.get("revenue")))
                         if _f(f.get("ev")) and _f(f.get("revenue")) else None, 2),
            "pb": _r(f.get("pb"), 2),
            "fcf_yield": _r((_f(f.get("fcf")) / _f(f.get("mcap")) * 100)
                            if _f(f.get("fcf")) and _f(f.get("mcap")) else None, 2),
            "op_margin_pct": _r(_f(f.get("op_margin"), None) and f["op_margin"] * 100, 1),
            "rev_growth_pct": _r(_f(f.get("rev_growth"), None) and f["rev_growth"] * 100, 1),
        }

    peer_rows = [row(p) for p in peers if _f(p.get("mcap"))]
    trow = row(target)

    def med(key):
        # exclude "nm" outliers the way a comps sheet would
        caps = {"pe_t": 100, "pe_f": 100, "ev_ebitda": 60, "ev_rev": 30, "pb": 60, "fcf_yield": 50}
        vals = [pr[key] for pr in peer_rows
                if pr[key] is not None and 0 < pr[key] <= caps.get(key, 1e9)]
        return round(float(np.median(vals)), 2) if vals else None

    medians = {k: med(k) for k in ["pe_t", "pe_f", "ev_ebitda", "ev_rev", "pb", "fcf_yield"]}

    # implied share values at peer medians
    shares = _f(target.get("shares"))
    net_debt = _f(target.get("net_debt"), 0.0) or 0.0
    implied = {}
    if shares:
        if medians["pe_f"] and _f(target.get("eps_fwd")):
            implied["P/E (fwd)"] = round(medians["pe_f"] * target["eps_fwd"], 2)
        if medians["pe_t"] and _f(target.get("eps_ttm")):
            implied["P/E (ttm)"] = round(medians["pe_t"] * target["eps_ttm"], 2)
        if medians["ev_ebitda"] and _f(target.get("ebitda")):
            implied["EV/EBITDA"] = round((medians["ev_ebitda"] * target["ebitda"] - net_debt) / shares, 2)
        if medians["ev_rev"] and _f(target.get("revenue")):
            implied["EV/Revenue"] = round((medians["ev_rev"] * target["revenue"] - net_debt) / shares, 2)

    price = _f(target.get("price"))
    vs = {k: round((v / price - 1) * 100, 1) for k, v in implied.items()} if price else {}

    flag = ""
    if vs and max(abs(v) for v in vs.values()) > 40:
        flag = (" Note: implied values here span a wide range — this peer set mixes business "
                "models with structurally different multiples, so the medians say as much "
                "about the peer list as about the company.")

    return {"ok": bool(peer_rows), "target": trow, "peers": peer_rows,
            "medians": medians, "implied_price": implied, "vs_price_pct": vs,
            "read": ("Implied values assume the market would pay the peer-median multiple "
                     "for this company's numbers. Persistent gaps usually have reasons — "
                     "margin, growth, backlog quality — so treat gaps as questions, not signals."
                     + flag)}


# =========================================================================== #
#  PAPER LBO
# =========================================================================== #

def lbo(f: dict, premium_pct=25.0, debt_pct=60.0, rate_pct=9.0,
        ebitda_growth_pct=4.0, exit_multiple=None, years=5, tax_pct=21.0) -> dict:
    ebitda0 = _f(f.get("ebitda"))
    mcap = _f(f.get("mcap"))
    net_debt = _f(f.get("net_debt"), 0.0) or 0.0
    fcf = _f(f.get("fcf"))
    if not ebitda0 or not mcap or ebitda0 <= 0:
        return {"ok": False, "note": "Needs positive EBITDA and market cap."}

    entry_equity_paid = mcap * (1 + premium_pct / 100)
    entry_ev = entry_equity_paid + net_debt
    entry_mult = entry_ev / ebitda0
    exit_mult = _f(exit_multiple) or round(entry_mult, 1)

    debt0 = entry_ev * debt_pct / 100
    sponsor_equity = entry_ev - debt0
    conv = 0.5
    if fcf and ebitda0:
        conv = float(np.clip(fcf / ebitda0, 0.20, 0.80))   # FCF conversion from actuals

    g = ebitda_growth_pct / 100
    rate = rate_pct / 100
    tax = tax_pct / 100

    rows, debt, ebitda = [], debt0, ebitda0
    for y in range(1, int(years) + 1):
        ebitda = ebitda * (1 + g)
        interest = debt * rate
        fcf_pre_debt = ebitda * conv
        paydown = max(0.0, fcf_pre_debt - interest * (1 - tax))
        debt = max(0.0, debt - paydown)
        rows.append({"year": y, "ebitda_b": _r(ebitda / 1e9, 2),
                     "interest_b": _r(interest / 1e9, 2),
                     "paydown_b": _r(paydown / 1e9, 2),
                     "debt_b": _r(debt / 1e9, 2)})

    exit_ev = ebitda * exit_mult
    exit_equity = exit_ev - debt
    moic = exit_equity / sponsor_equity if sponsor_equity > 0 else None
    irr = (moic ** (1 / years) - 1) * 100 if moic and moic > 0 else None

    return {
        "ok": True,
        "inputs": {"premium_pct": premium_pct, "debt_pct": debt_pct, "rate_pct": rate_pct,
                   "ebitda_growth_pct": ebitda_growth_pct, "exit_multiple": exit_mult,
                   "years": years, "tax_pct": tax_pct,
                   "fcf_conversion": round(conv, 2)},
        "entry": {"ev_b": _r(entry_ev / 1e9, 2), "entry_multiple": _r(entry_mult, 1),
                  "debt_b": _r(debt0 / 1e9, 2), "sponsor_equity_b": _r(sponsor_equity / 1e9, 2)},
        "years_table": rows,
        "exit": {"ev_b": _r(exit_ev / 1e9, 2), "debt_b": _r(debt / 1e9, 2),
                 "equity_b": _r(exit_equity / 1e9, 2)},
        "moic": _r(moic, 2), "irr_pct": _r(irr, 1),
        "read": (f"Buy at a {premium_pct:.0f}% premium ({entry_mult:.1f}× EBITDA), finance "
                 f"{debt_pct:.0f}% with debt at {rate_pct:.0f}%, grow EBITDA {ebitda_growth_pct:.0f}%/yr, "
                 f"convert {conv:.0%} of it to cash (that ratio comes from the company's own "
                 f"actual FCF/EBITDA), exit at {exit_mult:.1f}×. Sponsors typically want ~20%+ IRR — "
                 f"if this shows less, the price already embeds too much optimism for a buyout case."),
    }


# =========================================================================== #
#  M&A ACCRETION / DILUTION
# =========================================================================== #

def mna(acq: dict, tgt: dict, premium_pct=25.0, pct_stock=50.0,
        debt_rate_pct=6.0, synergies_m=0.0, tax_pct=21.0) -> dict:
    a_price, a_shares, a_eps = _f(acq.get("price")), _f(acq.get("shares")), _f(acq.get("eps_ttm"))
    t_mcap, t_eps, t_shares = _f(tgt.get("mcap")), _f(tgt.get("eps_ttm")), _f(tgt.get("shares"))
    if not all([a_price, a_shares, a_eps, t_mcap]):
        return {"ok": False, "note": "Missing acquirer price/shares/EPS or target market cap."}

    t_ni = (t_eps * t_shares) if (t_eps and t_shares) else None
    if t_ni is None:
        return {"ok": False, "note": "Target net income unavailable (no EPS/share count)."}

    deal_value = t_mcap * (1 + premium_pct / 100)
    stock_part = deal_value * pct_stock / 100
    cash_part = deal_value - stock_part            # assume cash is borrowed
    new_shares = stock_part / a_price
    tax = tax_pct / 100

    a_ni = a_eps * a_shares
    interest_drag = cash_part * (debt_rate_pct / 100) * (1 - tax)
    syn = synergies_m * 1e6 * (1 - tax)

    combined_ni = a_ni + t_ni + syn - interest_drag
    combined_shares = a_shares + new_shares
    new_eps = combined_ni / combined_shares
    acc_pct = (new_eps / a_eps - 1) * 100

    # pre-tax synergies needed to break even
    be = None
    gap = (a_eps * combined_shares) - (a_ni + t_ni - interest_drag)
    be = gap / (1 - tax) / 1e6

    return {
        "ok": True,
        "inputs": {"premium_pct": premium_pct, "pct_stock": pct_stock,
                   "debt_rate_pct": debt_rate_pct, "synergies_m": synergies_m, "tax_pct": tax_pct},
        "deal_value_b": _r(deal_value / 1e9, 2),
        "new_shares_m": _r(new_shares / 1e6, 1),
        "eps_before": _r(a_eps, 2), "eps_after": _r(new_eps, 2),
        "accretion_pct": _r(acc_pct, 1),
        "breakeven_synergies_m": _r(be, 0),
        "read": (f"{'Accretive' if acc_pct >= 0 else 'Dilutive'} {abs(acc_pct):.1f}% to acquirer EPS "
                 f"under these terms. "
                 + (f"Breakeven needs ~${be:,.0f}M pre-tax synergies. " if be > 0 else
                    f"Accretive even with zero synergies (${abs(be):,.0f}M of cushion). ")
                 + "EPS math is bookkeeping, not value — deals can be accretive and still destroy value "
                 "(and vice versa). Treat this as the arithmetic frame, not the verdict."),
    }


# =========================================================================== #
#  3-STATEMENT VIEW (historical, linked)
# =========================================================================== #

def statements_view(stmts: dict) -> dict:
    """Key rows from the actual reported statements, in $B, oldest -> newest,
    plus the linkage line: Net income -> CFO -> FCF."""
    inc, bal, cfs = stmts.get("income"), stmts.get("balance"), stmts.get("cashflow")
    if inc is None or inc.empty:
        return {"ok": False, "note": "No reported statements available for this ticker."}

    def pick(df, names):
        if df is None or df.empty:
            return None
        for n in names:
            if n in df.index:
                s = df.loc[n]
                if isinstance(s, pd.DataFrame):
                    s = s.iloc[0]
                return s
        return None

    years = [str(c)[:4] for c in inc.columns][::-1]

    def series(df, names, scale=1e9):
        s = pick(df, names)
        if s is None:
            return None
        vals = [(_f(v) / scale if _f(v) is not None else None) for v in s.tolist()][::-1]
        return [None if v is None else round(v, 2) for v in vals]

    income_rows = [
        ("Revenue", series(inc, ["Total Revenue", "Operating Revenue"])),
        ("Gross profit", series(inc, ["Gross Profit"])),
        ("Operating income", series(inc, ["Operating Income", "EBIT"])),
        ("EBITDA", series(inc, ["EBITDA", "Normalized EBITDA"])),
        ("Net income", series(inc, ["Net Income", "Net Income Common Stockholders"])),
    ]
    balance_rows = [
        ("Cash & equivalents", series(bal, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"])),
        ("Total debt", series(bal, ["Total Debt"])),
        ("Net debt", series(bal, ["Net Debt"])),
        ("Working capital", series(bal, ["Working Capital"])),
        ("Shareholders' equity", series(bal, ["Common Stock Equity", "Stockholders Equity"])),
    ]
    cash_rows = [
        ("Operating cash flow", series(cfs, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])),
        ("Capital expenditure", series(cfs, ["Capital Expenditure"])),
        ("Free cash flow", series(cfs, ["Free Cash Flow"])),
        ("Dividends paid", series(cfs, ["Cash Dividends Paid"])),
        ("Buybacks", series(cfs, ["Repurchase Of Capital Stock", "Common Stock Payments"])),
    ]

    def clean(rows):
        return [{"label": lab, "values": v} for lab, v in rows if v is not None]

    ni = dict(income_rows).get("Net income")
    cfo = dict(cash_rows).get("Operating cash flow")
    fcf = dict(cash_rows).get("Free cash flow")
    link = None
    if ni and cfo and fcf and ni[-1] and cfo[-1] and fcf[-1]:
        link = (f"Latest year linkage: ${ni[-1]:.1f}B net income became ${cfo[-1]:.1f}B operating "
                f"cash ({cfo[-1]/ni[-1]:.1f}× — accruals vs cash), and ${fcf[-1]:.1f}B was left "
                f"after capex. Cash conversion is where accounting meets reality.")

    return {"ok": True, "years": years,
            "income": clean(income_rows), "balance": clean(balance_rows),
            "cashflow": clean(cash_rows), "link": link}


# =========================================================================== #
#  MONTE CARLO (bootstrap)
# =========================================================================== #

def monte_carlo(rets: pd.DataFrame, weights: np.ndarray, total_value: float,
                n_paths: int = 2000, horizon: int = TRADING_DAYS, seed: int = 42) -> dict:
    """Bootstrap-resample the portfolio's OWN joint daily returns (rows sampled
    with replacement -> correlations and fat tails preserved, no normality
    assumed). Seeded, so it's reproducible."""
    R = rets.to_numpy()
    if R.shape[0] < 60:
        return {"ok": False, "note": "Not enough return history."}
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, R.shape[0], size=(n_paths, horizon))
    port = R @ weights                       # daily portfolio log-returns
    paths = np.cumsum(port[idx], axis=1)     # log growth paths
    growth = np.exp(paths)                   # wealth multiple

    pct = [5, 25, 50, 75, 95]
    step = max(1, horizon // 60)
    xs = list(range(0, horizon, step)) + [horizon - 1]
    bands = {str(p): [round(float(np.percentile(growth[:, x], p)), 4) for x in xs] for p in pct}

    terminal = growth[:, -1]
    var5 = float(np.percentile(terminal, 5))
    es5 = float(terminal[terminal <= var5].mean())

    return {
        "ok": True, "n_paths": n_paths, "horizon_days": horizon, "seed": seed,
        "xs": xs, "bands": bands,
        "terminal": {
            "median": round(float(np.median(terminal)), 3),
            "p5": round(var5, 3), "p95": round(float(np.percentile(terminal, 95)), 3),
            "prob_loss_pct": round(float((terminal < 1).mean() * 100), 1),
            "prob_down20_pct": round(float((terminal < 0.8).mean() * 100), 1),
            "es5": round(es5, 3),
        },
        "dollars": {
            "median": round(float(np.median(terminal)) * total_value, 2),
            "p5": round(var5 * total_value, 2),
            "p95": round(float(np.percentile(terminal, 95)) * total_value, 2),
            "es5": round(es5 * total_value, 2),
        },
        "read": (f"{n_paths:,} one-year paths resampled from your book's own daily returns "
                 f"(correlations and fat tails kept, no bell curve assumed). Median outcome "
                 f"is a wealth multiple of {np.median(terminal):.2f}×; 5% of paths end below "
                 f"{var5:.2f}×, and when they do, the average is {es5:.2f}×. "
                 "This says what the PAST distribution implies if it repeats — it does not know the future."),
    }


# =========================================================================== #
#  STRESS REPLAY
# =========================================================================== #

STRESS_WINDOWS = [
    ("COVID crash",      "2020-02-19", "2020-03-23"),
    ("2022 rate shock",  "2022-01-03", "2022-10-12"),
    ("SVB week",         "2023-03-06", "2023-03-13"),
    ("Aug-24 vol spike",  "2024-07-31", "2024-08-05"),
]


def stress_test(close: pd.DataFrame, weights: dict, total_value: float,
                bench: str = "SPY") -> dict:
    """Replay named historical windows on TODAY's weights. Holdings that didn't
    exist yet in a window are dropped and the remaining weights renormalized —
    flagged when it happens."""
    results = []
    syms = [s for s in weights if s in close.columns]
    for name, a, b in STRESS_WINDOWS:
        try:
            win = close.loc[a:b]
        except Exception:
            continue
        if win.empty or len(win) < 3:
            continue
        rets, used = {}, []
        for s in syms:
            ser = win[s].dropna()
            if len(ser) >= 2 and ser.iloc[0] > 0:
                rets[s] = ser.iloc[-1] / ser.iloc[0] - 1
                used.append(s)
        if not used:
            continue
        wsum = sum(weights[s] for s in used)
        port = sum(weights[s] / wsum * rets[s] for s in used)
        spy = None
        if bench in win.columns:
            bs = win[bench].dropna()
            if len(bs) >= 2:
                spy = bs.iloc[-1] / bs.iloc[0] - 1
        results.append({
            "name": name, "from": a, "to": b,
            "portfolio_pct": round(port * 100, 1),
            "dollar_impact": round(port * total_value, 2),
            "spy_pct": round(spy * 100, 1) if spy is not None else None,
            "per_holding": {s: round(rets[s] * 100, 1) for s in used},
            "note": (None if len(used) == len(syms)
                     else f"only {', '.join(used)} existed then — weights renormalized"),
        })
    return {"ok": bool(results), "windows": results,
            "read": ("Each row applies today's weights to what those holdings actually did in a "
                     "past storm. It's a rear-view mirror — the next storm will differ — but it's "
                     "an honest floor for 'how bad can a bad month look'.")}
