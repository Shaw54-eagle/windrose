"""
chokepoints.py — what does your book actually rest on?

The risk panel measures how your holdings move together. This measures
something different and harder to see: what they *depend on*. Five holdings in
five sectors can still funnel into one fab, one refiner, one payments network.
Correlation only shows that after it hurts you; structure shows it beforehand.

The method is deliberately plain. Walk upstream from each holding through the
supply-chain graph, note every company reachable within N hops, and report the
ones that more than one holding reaches — weighted by how much of your money
sits behind them. Then do the same downstream, which answers the other
question: are my companies all selling to the same few customers?

Honest limits, stated here because they belong next to the code:
  · The map is hand-curated and incomplete. Absence of a link is not evidence
    of independence.
  · A supply relationship is not a revenue share. TSMC appearing behind 70% of
    your book does not mean 70% of your value depends on TSMC — only that the
    companies you own sit downstream of it.
  · Hops are graph distance, not importance. A one-hop sole-source supplier
    matters more than a three-hop commodity vendor, and this cannot tell them
    apart.
"""
from __future__ import annotations

import collections

MAX_HOPS = 3


def _merged_graph(chain: dict):
    """One directed graph across every network. Edges run supplier -> customer."""
    nodes, up, down = {}, collections.defaultdict(set), collections.defaultdict(set)
    for net_id, net in (chain.get("networks") or {}).items():
        for n in net.get("nodes", []):
            existing = nodes.setdefault(n["id"], dict(n, nets=[]))
            if net_id not in existing["nets"]:
                existing["nets"].append(net_id)
        for e in net.get("edges", []):
            up[e["to"]].add(e["from"])
            down[e["from"]].add(e["to"])
    return nodes, up, down


def _reachable(start: str, adj: dict, max_hops: int) -> dict:
    """Everything reachable from `start`, with the shortest hop count to each."""
    seen, frontier = {}, {start}
    for hop in range(1, max_hops + 1):
        nxt = set()
        for s in frontier:
            for nb in adj.get(s, ()):
                if nb != start and nb not in seen:
                    seen[nb] = hop
                    nxt.add(nb)
        frontier = nxt
        if not frontier:
            break
    return seen


def _rank(direction_adj, symbols, weights, nodes, max_hops):
    """Companies reachable from more than one holding, ranked by money behind them."""
    reach = collections.defaultdict(dict)
    for sym in symbols:
        for other, hops in _reachable(sym, direction_adj, max_hops).items():
            reach[other][sym] = hops

    out = []
    for cid, hits in reach.items():
        if len(hits) < 2:                     # one holding is a dependency, not a chokepoint
            continue
        node = nodes.get(cid, {})
        weight = round(sum(weights.get(s, 0.0) for s in hits), 1)
        out.append({
            "id": cid,
            "label": node.get("label") or cid,
            "ticker": node.get("ticker", cid),
            "industries": node.get("nets", [])[:3],
            "held": cid in symbols,
            "count": len(hits),
            "weight_pct": weight,
            "min_hops": min(hits.values()),
            "reaches": sorted(
                ({"symbol": s, "hops": h} for s, h in hits.items()),
                key=lambda r: (r["hops"], r["symbol"]),
            ),
        })
    out.sort(key=lambda r: (-r["weight_pct"], -r["count"], r["min_hops"]))
    return out


def analyse(chain: dict, holdings: list[dict], prices: dict, max_hops: int = MAX_HOPS) -> dict:
    """Full report. `prices` maps symbol -> last price; missing prices weigh 0."""
    nodes, up, down = _merged_graph(chain)

    symbols, values = [], {}
    for h in holdings:
        sym = h.get("symbol")
        if not sym:
            continue
        shares = float(h.get("shares") or 0)
        px = float((prices.get(sym) or {}).get("price") or 0)
        values[sym] = shares * px
        symbols.append(sym)

    mapped = [s for s in symbols if s in nodes]
    unmapped = [s for s in symbols if s not in nodes]
    sized = [s for s in mapped if values.get(s, 0) > 0]

    total = sum(values.get(s, 0) for s in sized) or 0.0
    if total > 0:
        weights = {s: values[s] / total * 100.0 for s in sized}
        basis = "value"
    else:
        # No prices yet (or every position is watch-only). An honest equal
        # weighting beats showing 0% everywhere and implying no exposure.
        share = 100.0 / len(mapped) if mapped else 0.0
        weights = {s: share for s in mapped}
        basis = "equal"
    # Watch-only positions still reveal structure; they just carry no weight.
    for s in mapped:
        weights.setdefault(s, 0.0)

    return {
        "ok": bool(mapped),
        "hops": max_hops,
        "mapped": mapped,
        "unmapped": unmapped,
        "coverage_pct": round(len(mapped) / len(symbols) * 100) if symbols else 0,
        "basis": basis,
        "upstream": _rank(up, mapped, weights, nodes, max_hops)[:12],
        "downstream": _rank(down, mapped, weights, nodes, max_hops)[:12],
        "note": ("Graph structure from a hand-curated map, not revenue data. "
                 "A shared supplier is a shared dependency, not a shared income "
                 "statement — and a missing link may just be a gap in the map."),
    }
