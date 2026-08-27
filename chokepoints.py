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
  · Hops are graph distance, not importance on their own. Distance is now
    discounted (see HOP_DECAY) and recorded criticality is used where it
    exists, but neither turns this into a revenue measure.
  · Criticality coverage is thin. 2 of 529 edges carry it today, so almost
    every path scores at the unknown floor and ranking is currently driven by
    distance. The mechanism is here so that verifying an edge changes the
    answer; until the map is verified, it mostly does not.

Why the ranking is weighted at all — the failure it fixes:

    Three hops with unweighted edges reaches most of the graph, so most of the
    graph ties. A five-holding semiconductor book ranked AMC Theatres at 100%
    of its downstream exposure, above a four-way tie at 81%, because AMC is
    reachable from every holding in three steps. Nothing about that was false;
    it simply answered "what can I get to from here" when the question was
    "what does this book rest on".
"""
from __future__ import annotations

import collections

MAX_HOPS = 3

# Each hop out, halve what the dependency counts for. The justification is
# plain: every intermediary is a company that can dual-source, hold inventory,
# or absorb a shock before it reaches you, and a half is the honest way to say
# "call it even odds it gets absorbed" without inventing a decimal the evidence
# cannot carry. A three-hop link therefore counts a quarter of a direct one,
# which is the "substantially" this needs — enough to sort real dependencies
# above graph noise, not so much that distant structure vanishes entirely.
HOP_DECAY = 0.5

# What a link is worth, by what the map records about it. A sole-source link is
# a full dependency; anything weaker is a fraction of one.
CRITICALITY_WEIGHT = {"sole-source": 1.0, "major": 0.85, "minor": 0.7}

# Absent, unrecognised, or unproven: the floor. Not zero — an unverified edge is
# still structure, just unproven, and dropping it would silently assert
# independence the map has no basis for. It shares the floor with `minor` on
# purpose: if unknown scored *below* minor, then tagging an edge `minor` would
# raise its score, and a community-editable file should never pay a contributor
# for adding an unsourced downgrade.
UNKNOWN_WEIGHT = 0.7

# A criticality claim with no source behind it is a curator's opinion. It still
# counts — it just cannot reach the top tier on assertion alone, or the file
# that "takes pull requests" becomes the file that ranks whoever edits it.
UNBACKED_CLAIM = {"sole-source": "major", "major": "minor"}


def _claim_is_backed(edge: dict) -> bool:
    """Does a source actually substantiate this edge's criticality?

    The schema's rule, applied by a consumer: there is no partial credit. A
    filing that establishes a relationship exists does not thereby establish
    that it is sole-source, so only a source naming `criticality` in `supports`
    counts — and only on an edge marked verified.
    """
    if edge.get("confidence") != "verified":
        return False
    return any("criticality" in (src.get("supports") or [])
               for src in (edge.get("sources") or []))


def _edge_strength(edge: dict) -> float:
    """What one link counts for, in 0..1."""
    claim = edge.get("criticality")
    if claim not in CRITICALITY_WEIGHT:       # absent, or a value from a later
        return UNKNOWN_WEIGHT                 # schema we do not recognise yet
    if not _claim_is_backed(edge):
        claim = UNBACKED_CLAIM.get(claim, claim)
    return CRITICALITY_WEIGHT[claim]


def _merged_graph(chain: dict):
    """One directed graph across every network. Edges run supplier -> customer.

    Neighbours carry their edge record, because the weighting needs what the
    map says about the link, not just that a link exists.
    """
    nodes = {}
    up, down = collections.defaultdict(list), collections.defaultdict(list)
    for net_id, net in (chain.get("networks") or {}).items():
        for n in net.get("nodes", []):
            existing = nodes.setdefault(n["id"], dict(n, nets=[]))
            if net_id not in existing["nets"]:
                existing["nets"].append(net_id)
        for e in net.get("edges", []):
            up[e["to"]].append((e["from"], e))
            down[e["from"]].append((e["to"], e))
    return nodes, up, down


def _reachable(start: str, adj: dict, max_hops: int) -> dict:
    """Everything reachable from `start`: {node: (hops, link strength)}.

    A chain is worth its weakest link — a sole-source supplier reached through
    a link nobody has assessed is still only as certain as that second link, so
    the path takes the minimum. Where several equally short routes exist, the
    strongest wins: the dependency runs along the firmest one the map knows.
    """
    best, frontier = {}, {start: 1.0}
    for hop in range(1, max_hops + 1):
        nxt: dict[str, float] = {}
        for node, carried in frontier.items():
            for nb, edge in adj.get(node, ()):
                if nb == start or nb in best:
                    continue
                strength = min(carried, _edge_strength(edge))
                if strength > nxt.get(nb, 0.0):
                    nxt[nb] = strength
        for nb, strength in nxt.items():
            best[nb] = (hop, strength)
        frontier = nxt
        if not frontier:
            break
    return best


def _rank(direction_adj, symbols, weights, nodes, max_hops):
    """Companies more than one holding reaches, ranked by weighted exposure.

    Two numbers come out of this and they mean different things:

      weight_pct  the share of your money that reaches this company at all,
                  at any distance. What this panel used to rank on.
      score_pct   the same share after each holding is discounted for how far
                  away it sits and how strong the map says the links are. What
                  it ranks on now, and what the panel shows.

    score_pct is always the smaller of the two, deliberately. Reaching a
    company in three steps down unproven links is not the same as depending
    on it directly, and the old number could not tell those apart.
    """
    reach = collections.defaultdict(dict)
    for sym in symbols:
        for other, (hops, strength) in _reachable(sym, direction_adj, max_hops).items():
            reach[other][sym] = (hops, strength)

    out = []
    for cid, hits in reach.items():
        if len(hits) < 2:                     # one holding is a dependency, not a chokepoint
            continue
        node = nodes.get(cid, {})
        raw = sum(weights.get(s, 0.0) for s in hits)
        score = sum(weights.get(s, 0.0) * (HOP_DECAY ** (hops - 1)) * strength
                    for s, (hops, strength) in hits.items())
        out.append({
            "id": cid,
            "label": node.get("label") or cid,
            "ticker": node.get("ticker", cid),
            "industries": node.get("nets", [])[:3],
            "held": cid in symbols,
            "count": len(hits),
            "weight_pct": round(raw, 1),
            "score_pct": round(score, 1),
            "min_hops": min(h for h, _ in hits.values()),
            "reaches": sorted(
                ({"symbol": s, "hops": h} for s, (h, _) in hits.items()),
                key=lambda r: (r["hops"], r["symbol"]),
            ),
        })
    out.sort(key=lambda r: (-r["score_pct"], -r["count"], r["min_hops"]))
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
        "decay": HOP_DECAY,
        "note": ("Graph structure from a hand-curated map, not revenue data. "
                 "A shared supplier is a shared dependency, not a shared income "
                 "statement — and a missing link may just be a gap in the map."),
    }
