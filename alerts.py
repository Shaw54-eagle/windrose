"""
alerts.py — watch without staring.

Rules are edge-triggered: a rule fires when its condition flips from false to
true, then arms again only after the condition goes false. No spam, no
"still above your level" every three seconds.

Metrics:
  price_above / price_below      (needs: value)
  day_move_abs                   (|day change %| >= value)
  rsi_above / rsi_below          (from the cached analysis)
  cross_below_sma20 / cross_below_sma50 / cross_above_sma20 / cross_above_sma50
  port_drawdown                  (portfolio down >= value % from its 1y peak)

Everything persists to alerts.json. Fired events land in a ring buffer the
frontend drains for macOS/browser notifications.
"""

from __future__ import annotations
import json, time, uuid, threading
from collections import deque
from pathlib import Path

BASE = Path(__file__).resolve().parent
ALERTS_FILE = BASE / "alerts.json"

METRICS = [
    "price_above", "price_below", "day_move_abs",
    "rsi_above", "rsi_below",
    "cross_above_sma20", "cross_below_sma20",
    "cross_above_sma50", "cross_below_sma50",
    "port_drawdown",
]

_LOCK = threading.Lock()
FIRED = deque(maxlen=80)          # recent fired events (frontend polls/streams these)
_STATE: dict = {}                 # rule_id -> last condition bool (for edge trigger)


def load() -> list[dict]:
    if ALERTS_FILE.exists():
        try:
            return json.loads(ALERTS_FILE.read_text())
        except Exception:
            return []
    return []


def save(rules: list[dict]):
    ALERTS_FILE.write_text(json.dumps(rules, indent=2))


def add(symbol: str, metric: str, value: float, note: str = "") -> dict:
    if metric not in METRICS:
        raise ValueError("unknown metric")
    rule = {
        "id": uuid.uuid4().hex[:10],
        "symbol": (symbol or "PORT").upper(),
        "metric": metric,
        "value": float(value),
        "note": (note or "").strip()[:140],
        "enabled": True,
        "created": time.strftime("%Y-%m-%d"),
        "last_fired": None,
    }
    with _LOCK:
        rules = load()
        rules.append(rule)
        save(rules)
    return rule


def delete(rule_id: str) -> bool:
    with _LOCK:
        rules = load()
        n = len(rules)
        rules = [r for r in rules if r["id"] != rule_id]
        save(rules)
        _STATE.pop(rule_id, None)
    return len(rules) < n


def toggle(rule_id: str) -> bool:
    with _LOCK:
        rules = load()
        for r in rules:
            if r["id"] == rule_id:
                r["enabled"] = not r["enabled"]
                save(rules)
                return r["enabled"]
    return False


# --------------------------------------------------------------------------- #
#  evaluation
# --------------------------------------------------------------------------- #

def _condition(rule: dict, quotes: dict, stocks: dict, port: dict) -> bool | None:
    """True/False if evaluable right now, None if data missing."""
    m, v = rule["metric"], rule["value"]
    sym = rule["symbol"]

    if m == "port_drawdown":
        dd = (port or {}).get("max_drawdown_from_peak_pct")
        return None if dd is None else (dd <= -abs(v))

    q = quotes.get(sym) or {}
    st = stocks.get(sym) or {}
    price = q.get("price") or st.get("live_price") or st.get("price")

    if m in ("price_above", "price_below"):
        if price is None:
            return None
        return price >= v if m == "price_above" else price <= v
    if m == "day_move_abs":
        cp = q.get("change_pct")
        return None if cp is None else abs(cp) >= abs(v)
    if m in ("rsi_above", "rsi_below"):
        r = st.get("rsi")
        if r is None:
            return None
        return r >= v if m == "rsi_above" else r <= v
    if m.startswith("cross_"):
        sma = st.get("sma20") if m.endswith("sma20") else st.get("sma50")
        if price is None or sma is None:
            return None
        return price >= sma if "above" in m else price <= sma
    return None


def evaluate(quotes: dict, stocks_list: list[dict], port_extra: dict):
    """One evaluation pass. Called every few seconds from the app's loop."""
    rules = load()
    if not rules:
        return
    stocks = {s["symbol"]: s for s in (stocks_list or [])}
    dirty = False
    for r in rules:
        if not r.get("enabled"):
            _STATE[r["id"]] = False
            continue
        cond = _condition(r, quotes, stocks, port_extra)
        if cond is None:
            continue
        prev = _STATE.get(r["id"], False)
        if cond and not prev:
            evt = {
                "id": uuid.uuid4().hex[:8],
                "rule_id": r["id"],
                "symbol": r["symbol"],
                "metric": r["metric"],
                "value": r["value"],
                "note": r.get("note", ""),
                "ts": time.time(),
                "when": time.strftime("%I:%M:%S %p"),
                "text": _text(r, quotes, stocks),
            }
            FIRED.append(evt)
            r["last_fired"] = time.strftime("%Y-%m-%d %H:%M")
            dirty = True
        _STATE[r["id"]] = cond
    if dirty:
        with _LOCK:
            save(rules)


def _text(r: dict, quotes: dict, stocks: dict) -> str:
    sym, m, v = r["symbol"], r["metric"], r["value"]
    q = quotes.get(sym) or {}
    st = stocks.get(sym) or {}
    px = q.get("price") or st.get("price")
    label = {
        "price_above": f"{sym} crossed above {v:g} (now {px})",
        "price_below": f"{sym} fell below {v:g} (now {px})",
        "day_move_abs": f"{sym} moved {q.get('change_pct')}% today (threshold {v:g}%)",
        "rsi_above": f"{sym} RSI hit {st.get('rsi')} (≥ {v:g})",
        "rsi_below": f"{sym} RSI hit {st.get('rsi')} (≤ {v:g})",
        "cross_above_sma20": f"{sym} crossed above its 20-day average",
        "cross_below_sma20": f"{sym} crossed below its 20-day average",
        "cross_above_sma50": f"{sym} crossed above its 50-day average",
        "cross_below_sma50": f"{sym} crossed below its 50-day average",
        "port_drawdown": f"Portfolio drawdown breached −{abs(v):g}% from its 1-year peak",
    }.get(m, f"{sym} {m} {v}")
    return label + (f" — {r['note']}" if r.get("note") else "")


def fired_since(ts: float) -> list[dict]:
    return [e for e in FIRED if e["ts"] > ts]
