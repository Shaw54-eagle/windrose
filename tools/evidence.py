#!/usr/bin/env python3
"""
evidence.py — find filing passages that support one supply-chain edge.

    ./venv/bin/python tools/evidence.py ASML TSM
    ./venv/bin/python tools/evidence.py ZEISS ASML --accept 1 --criticality sole-source

The pilot showed the slow part is not judgement, it is fetching: one 10-K is
several megabytes and the automated pass read them one at a time, then guessed
at a single answer and got it wrong three times in eleven. This does the
opposite. It fetches in parallel, shows you every passage it found ranked by
how well it carries a claim, and lets you decide. `--accept N` then writes that
passage into supply_chain.json with its provenance filled in.

Nothing here writes an edge you have not looked at, and nothing is quoted that
was not downloaded — every candidate is re-checked as a verbatim substring of
the document before it is printed.

SEC's fair-access policy needs a contact address in the User-Agent and caps
you near 10 requests/second. Set yours before running:

    export WINDROSE_SEC_UA='Windrose research (you@example.com)'

A GitHub noreply alias will not do — SEC returns 403 for addresses it cannot
reach, and that is what most clones have in git config.
"""
from __future__ import annotations

import argparse, gzip, html, json, os, re, sys, threading, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAIN = ROOT / "supply_chain.json"
CACHE = Path(os.getenv("WINDROSE_SEC_CACHE", "/tmp/edgar_cache")); CACHE.mkdir(exist_ok=True)
def _ua():
    """SEC asks for a real contact address, and refuses requests without one.

    Taken from WINDROSE_SEC_UA, else your git identity — so a fork sends its
    own address rather than inheriting a stranger's from a source file.
    """
    ua = os.getenv("WINDROSE_SEC_UA")
    if ua:
        return ua
    import subprocess
    try:
        email = subprocess.run(["git", "config", "user.email"], cwd=ROOT,
                               capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        email = ""
    # SEC returns 403 for addresses it cannot actually reach, and GitHub's
    # noreply alias is the common case — it is what most clones have in git
    # config. Better to say so here than to 403 four calls deep.
    if not email or "noreply" in email or "@" not in email:
        sys.exit(
            "SEC's fair-access policy needs a contact address it can reach,\n"
            "and refuses requests without one (HTTP 403).\n"
            f"{'  git config user.email is ' + email + ', which SEC rejects.' if email else ''}\n"
            "\nSet a real one for this shell:\n"
            "    export WINDROSE_SEC_UA='Windrose research (you@example.com)'\n")
    return f"Windrose supply-chain research ({email})"


UA = _ua()

RATE = 8.0                      # requests/second, under SEC's ~10
_lock = threading.Lock(); _last = [0.0]
STATS = {"req": 0, "cached": 0, "bytes": 0}


def _throttle():
    with _lock:
        wait = _last[0] + 1.0 / RATE - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def get(url, timeout=30):
    key = CACHE / (re.sub(r"[^A-Za-z0-9]", "_", url)[-180:] + ".bin")
    if key.exists():
        STATS["cached"] += 1
        return key.read_bytes()
    _throttle(); STATS["req"] += 1
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
    STATS["bytes"] += len(b)
    key.write_bytes(b)
    return b


def fts(q, cik=None, forms="10-K,20-F"):
    p = {"q": q, "forms": forms}
    if cik:
        p["ciks"] = cik
    try:
        return json.loads(get("https://efts.sec.gov/LATEST/search-index?" + urllib.parse.urlencode(p)))
    except Exception:
        return {"hits": {"hits": []}}


TAG = re.compile(r"<[^>]+>"); WS = re.compile(r"\s+")


def doc_text(cik, adsh, fname):
    url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{adsh.replace('-','')}/{fname}"
    try:
        raw = get(url).decode("utf8", "ignore")
    except Exception:
        return "", url
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    return WS.sub(" ", html.unescape(TAG.sub(" ", raw))).strip(), url


SOLE = ["sole supplier", "sole source", "sole-source", "only supplier", "single source",
        "single supplier", "sole provider", "sole manufacturer", "only qualified supplier",
        "exclusive supplier", "only source"]
MAJOR = ["principal supplier", "primary supplier", "largest supplier", "major supplier",
         "key supplier", "significant supplier", "we depend on", "we rely on", "depend upon",
         "relies on", "largest customer", "principal customer", "significant customer",
         "major customer", "substantially all"]
REL_PAT = [r"purchas\w*\s+from", r"sourc\w*\s+from", r"suppli\w*\s+(by|to|from)",
           r"revenues?\s+from", r"net\s+sales\s+to", r"top\s+customers?",
           r"largest\s+customers?", r"principal\s+customers?", r"major\s+customers?",
           r"\bis\s+(a|our|the)\s+\w*\s*(supplier|vendor|foundry|customer)",
           r"(supplier|vendor|foundry|customer)s?\s+(include|are|is|such\s+as)",
           r"manufactur\w*\s+(by|for)", r"fabricat\w*\s+(by|for)", r"assembl\w*\s+(by|for)",
           r"licens\w*\s+from", r"foundry\s+partner", r"produced\s+by", r"wafers?\s+(are|is)"]
NOT_SUPPLY = ["director", "officer", "prior to joining", "served as", "board of",
              "vice president of", " age ", "mr.", "ms.", "shares of", "stock exchange",
              "litigation", "lawsuit", "patent infringement", "infring", "class action",
              "trustee", "table of contents"]

ALIAS = json.loads((Path(__file__).parent / "aliases.json").read_text()) \
    if (Path(__file__).parent / "aliases.json").exists() else {}


def sents(t):
    return re.split(r"(?<=[.;])\s+", t)


def passages(text, alias, max_words=15):
    """Every sentence naming `alias` that also asserts something about supply."""
    out, norm = [], WS.sub(" ", text)
    low, al = norm.lower(), alias.lower()
    for m in re.finditer(re.escape(al), low):
        for sent in sents(norm[max(0, m.start() - 400): m.end() + 400]):
            sl = sent.lower()
            if al not in sl or any(n in sl for n in NOT_SUPPLY):
                continue
            sig = next((s for s in SOLE if s in sl), None)
            kind = "sole-source"
            if not sig:
                sig = next((s for s in MAJOR if s in sl), None); kind = "major"
            if not sig:
                mm = next((re.search(p, sl) for p in REL_PAT if re.search(p, sl)), None)
                if not mm:
                    continue
                sig, kind = mm.group(0), "rel"
            words = sent.split()
            if len(words) <= max_words:
                cand = sent
            else:
                ai = sl.find(al); upto = len(sent[:ai].split())
                start = max(0, upto - 5)
                while start < len(words) and len(words[start]) <= 2 and start < upto:
                    start += 1
                cand = " ".join(words[start:start + max_words])
            cand = cand.strip(" ,;:.—-“”\"'()")
            toks = cand.split()
            if len(toks) < 5 or al not in cand.lower():
                continue
            if sum(1 for t in toks if re.fullmatch(r"[\d%.,$()\-]+", t)) / len(toks) > 0.3:
                continue
            if WS.sub(" ", cand) not in norm:      # never print what we cannot prove
                continue
            out.append({"quote": cand, "signal": sig, "kind": kind})
    return out


def candidates(frm, to, ciks, forms="10-K,20-F", since="2019-01-01", workers=8):
    """Search both directions, fetch every promising filing at once."""
    jobs = []
    for filer, other in ((to, frm), (frm, to)):
        if filer not in ciks:
            continue
        cik = ciks[filer][0]
        for alias in ALIAS.get(other, [other]):
            for probe in (None, "sole supplier", "single source", "largest customer"):
                q = f'"{alias}"' + (f' "{probe}"' if probe else "")
                jobs.append((filer, cik, alias, q))

    seen, fetches = set(), []
    for filer, cik, alias, q in jobs:
        for h in fts(q, cik=cik, forms=forms).get("hits", {}).get("hits", []):
            src = h["_source"]
            fn = h["_id"].split(":", 1)[1] if ":" in h["_id"] else ""
            if src.get("file_date", "") < since or not fn.lower().endswith((".htm", ".html", ".txt")):
                continue
            k = (cik, src["adsh"], fn)
            if k in seen:
                continue
            seen.add(k)
            fetches.append((filer, cik, alias, src, fn))

    out = []
    def work(job):
        filer, cik, alias, src, fn = job
        text, url = doc_text(cik, src["adsh"], fn)
        return [dict(p, filer=filer, filer_cik=cik, alias=alias, url=url,
                     doc_type=src.get("form"), filed=src.get("file_date"),
                     accession=src["adsh"]) for p in passages(text, alias)] if text else []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for got in ex.map(work, fetches[:40]):
            out.extend(got)

    rank = {"sole-source": 0, "major": 1, "rel": 2}
    uniq = {}
    for p in out:
        uniq.setdefault(p["quote"], p)
    return sorted(uniq.values(), key=lambda p: (rank[p["kind"]], p["filed"]), reverse=False)[:120]


def load_ciks():
    """SEC's ticker->CIK map, fetched and cached rather than vendored.

    It is 800KB and it goes stale as companies list and delist, so a copy
    committed to this repo would be both bloat and a slowly-rotting lie.
    """
    cached = CACHE / "company_tickers.json"
    if not cached.exists():
        cached.write_bytes(get("https://www.sec.gov/files/company_tickers.json"))
    raw = json.loads(cached.read_text())
    return {v["ticker"]: [str(v["cik_str"]).zfill(10), v["title"]] for v in raw.values()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frm"); ap.add_argument("to")
    ap.add_argument("--network", default="semiconductors")
    ap.add_argument("--accept", type=int, help="write candidate N into supply_chain.json")
    ap.add_argument("--criticality", choices=["sole-source", "major", "minor"])
    ap.add_argument("--supports", default="rel")
    ap.add_argument("--since", default="2019-01-01")
    ap.add_argument("--show", type=int, default=8)
    a = ap.parse_args()

    ciks = load_ciks()
    t0 = time.time()
    cands = candidates(a.frm, a.to, ciks, since=a.since)
    el = time.time() - t0

    if not cands:
        print(f"no supporting passage found for {a.frm} -> {a.to} "
              f"({el:.0f}s, {STATS['req']} fetched, {STATS['cached']} cached)")
        print("leave it confidence:\"unverified\" — that is a real answer, not a failure")
        return 1

    if a.accept is None:
        print(f"{len(cands)} candidate passage(s) for {a.frm} -> {a.to}   "
              f"[{el:.0f}s, {STATS['req']} fetched, {STATS['cached']} cached]\n")
        for i, c in enumerate(cands[:a.show], 1):
            print(f"  [{i}] {c['kind']:<11} {c['doc_type']:<5} {c['filed']}  filer={c['filer']}")
            print(f"      \"{c['quote']}\"")
            print(f"      {c['url']}\n")
        print(f"accept with:  --accept N [--criticality sole-source|major|minor] "
              f"[--supports rel,criticality]")
        return 0

    c = cands[a.accept - 1]
    chain = json.loads(CHAIN.read_text())
    edges = chain["networks"][a.network]["edges"]
    e = next((x for x in edges if x["from"] == a.frm and x["to"] == a.to), None)
    if e is None:
        print(f"no such edge in {a.network}: {a.frm} -> {a.to}"); return 1
    e["confidence"] = "verified"
    e.setdefault("sources", []).append({
        "url": c["url"], "doc_type": c["doc_type"], "filer_cik": c["filer_cik"],
        "accession": c["accession"], "filed": c["filed"],
        "retrieved": time.strftime("%Y-%m-%d"), "quote": c["quote"],
        "supports": [s.strip() for s in a.supports.split(",")],
    })
    if a.criticality:
        e["criticality"] = a.criticality
    CHAIN.write_text(json.dumps(chain, indent=2) + "\n")
    print(f"wrote {a.frm} -> {a.to}: {c['doc_type']} {c['filed']}"
          f"{', criticality=' + a.criticality if a.criticality else ''}")
    print(f'  "{c["quote"]}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
