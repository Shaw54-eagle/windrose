/* Windrose tutorial — live numbers + demos. Vanilla JS.
   Everything here reads the same APIs as the dashboard, so the prose stays
   true to whatever the book actually looks like right now. */

const $ = (id) => document.getElementById(id);
const css = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = (n, d = 2) => (n == null ? "—" : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }));
const money = (n) => (n == null ? "—" : "$" + fmt(Math.abs(n), 2));

function put(key, text, cls) {
  document.querySelectorAll(`[data-live="${key}"]`).forEach(el => {
    el.textContent = text;
    if (cls) el.className = cls;
  });
}

/* ---- mark tutorial as seen (server-side, so the first-run gate lifts) ---- */
fetch("/api/tutorial/seen", { method: "POST" }).catch(() => {});

/* ---- first-run banner ---------------------------------------------------- */
if (new URLSearchParams(location.search).get("first")) {
  const b = $("firstrun");
  if (b) b.style.display = "block";
}

/* ========================================================================= */
/*  live injection                                                           */
/* ========================================================================= */

let TOTAL = null;   // portfolio value, used by the VaR demo

(async function inject() {
  let a = null;
  try { a = await (await fetch("/api/analysis")).json(); } catch (e) {}
  const p = a && a.portfolio && a.portfolio.ok ? a.portfolio : null;
  const stocks = (a && a.stocks || []).filter(s => s.score);

  // conditions score: best / worst
  if (stocks.length) {
    const sorted = [...stocks].sort((x, y) => y.score.total - x.score.total);
    put("best-sym", sorted[0].symbol);
    put("best-score", fmt(sorted[0].score.total, 0) + "/100 " + sorted[0].score.label);
    const w = sorted[sorted.length - 1];
    put("worst-sym", w.symbol);
    put("worst-score", fmt(w.score.total, 0) + "/100 " + w.score.label);
  } else {
    const line = $("score-live-line");
    if (line) line.textContent = "Add a position on the console and this paragraph fills in with your own strongest and weakest card.";
  }

  if (!p) {
    ["n-pos","n-pos-2","eff-n","beta","div-ratio"].forEach(k => put(k, "—"));
    put("pair-line", "Once you hold two or more sized positions, this sentence names the tightest pair in your book, with the real correlation.");
    put("rc-line", "With sized positions, this line compares your biggest position's share of dollars against its share of risk.");
    put("var-compare", "add positions to compare yours");
    return;
  }

  TOTAL = p.total_value;
  const c = p.concentration;
  put("n-pos", String(c.n_positions));
  put("n-pos-2", String(c.n_positions));
  put("eff-n", fmt(c.effective_holdings, 2));
  put("beta", fmt(p.beta, 2));
  put("div-ratio", fmt(p.diversification_ratio, 2));

  // tightest pair — phrased by how bad it actually is
  if (p.highest_pair && p.highest_pair.pair) {
    const [A, B] = p.highest_pair.pair;
    const rho = p.highest_pair.corr;
    let verdict;
    if (rho >= 0.7) verdict = "at that level they are, for risk purposes, one trade wearing two tickers";
    else if (rho >= 0.4) verdict = "owning both is closer to one and a half bets than two";
    else verdict = "genuinely different exposures — that's what diversification is supposed to look like";
    put("pair-line", `The tightest pair in your book right now is ${A} and ${B}, with a one-year correlation of ${fmt(rho, 2)} — ${verdict}.`);

    // preload the correlation demo with the real pair
    corrDefaults(A, B, rho, stocks, p);
  }

  // risk contribution vs weight — the concentration story in one line
  const rc = p.risk_contribution || {};
  const top = Object.entries(rc).sort((x, y) => y[1] - x[1])[0];
  if (top) {
    const [sym, riskShare] = top;
    const pos = (p.positions || []).find(q => q.symbol === sym);
    const wPct = pos ? pos.weight_pct : null;
    if (wPct != null) {
      const spread = riskShare - wPct;
      const tail = Math.abs(spread) < 5
        ? "weight and risk are roughly in line — the book's risk is at least honest about where it lives"
        : spread > 0
          ? `it punches ${fmt(spread, 0)} points above its weight — volatility and correlation both feeding the same name`
          : `it actually carries less risk than its size suggests — the rest of the book is doing the thrashing`;
      put("rc-line", `Right now ${sym} holds ${fmt(wPct, 0)}% of the dollars and drives ${fmt(riskShare, 0)}% of the risk — ${tail}.`);
    }
  }

  // VaR: historical vs parametric, in dollars
  const v = p.var || {};
  if (v.hist_95_dollar != null && v.param_95_dollar != null) {
    const h = v.hist_95_dollar, b = v.param_95_dollar;
    put("var-compare", h > b
      ? `yours: historical ${money(h)} vs bell-curve ${money(b)} — the record is uglier than the curve`
      : `yours: historical ${money(h)} vs bell-curve ${money(b)} — an unusually polite window; don't count on it lasting`);
  }
})();

/* ========================================================================= */
/*  demo 1: RSI balance                                                      */
/* ========================================================================= */

(function rsiDemo() {
  const inp = $("rsi-in");
  if (!inp) return;
  const upd = () => {
    const v = parseInt(inp.value, 10);
    $("rsi-lab").textContent = v + "%";
    $("rsi-out").textContent = v;
    $("rsi-bar").style.width = v + "%";
    $("rsi-bar").className = "bfill " + (v >= 70 || v <= 30 ? "red" : v >= 55 ? "green" : "");
    $("rsi-zone").textContent = "reads as: " +
      (v >= 70 ? "overbought — the recent tape has been one-way traffic upward" :
       v >= 55 ? "strong — buyers doing most of the moving" :
       v >= 45 ? "neutral — a fair fight" :
       v > 30  ? "weak — sellers in charge lately" :
                 "oversold — one-way traffic downward, which is stretched, not necessarily cheap");
  };
  inp.addEventListener("input", upd); upd();
})();

/* ========================================================================= */
/*  demo 2: drawdown recovery asymmetry                                      */
/* ========================================================================= */

(function ddDemo() {
  const inp = $("dd-in");
  if (!inp) return;
  const upd = () => {
    const d = parseInt(inp.value, 10);
    const need = d / (100 - d) * 100;
    $("dd-lab").textContent = "−" + d + "%";
    $("dd-o1").textContent = "−" + d + "%";
    $("dd-o2").textContent = "+" + fmt(need, need >= 100 ? 0 : 1) + "%";
    $("dd-bar1").style.width = d + "%";
    $("dd-bar2").style.width = Math.min(100, need) + "%";
    $("dd-read").textContent =
      d <= 15 ? `Shallow cuts heal at nearly one-to-one: −${d}% needs +${fmt(need,1)}%. This is the zone where risk management is cheap.` :
      d <= 40 ? `Lose ${d}%, and you need +${fmt(need,1)}% just to be whole. The asymmetry is arithmetic, not opinion — and it's the entire case for caring about risk before return.` :
      d <= 60 ? `At −${d}% you need +${fmt(need,0)}% to recover — years of good returns spent repairing one bad stretch.` :
                `−${d}% needs +${fmt(need,0)}%. Below here, portfolios don't recover on math — they recover on new money or not at all.`;
  };
  inp.addEventListener("input", upd); upd();
})();

/* ========================================================================= */
/*  demo 3: two-asset correlation (preloaded with the real tightest pair)    */
/* ========================================================================= */

let CORR = { s1: 30, s2: 30, n1: "A", n2: "B" };

function corrDefaults(A, B, rho, stocks, p) {
  const find = (sym) => stocks.find(s => s.symbol === sym) || {};
  const v1 = find(A).ewma_vol_pct || find(A).vol_annual_pct || 30;
  const v2 = find(B).ewma_vol_pct || find(B).vol_annual_pct || 30;
  CORR = { s1: v1, s2: v2, n1: A, n2: B };
  $("c-n1").textContent = A;
  $("c-r").value = Math.round(rho * 100);
  // weight of A within the A+B pair
  const pa = (p.positions || []).find(q => q.symbol === A);
  const pb = (p.positions || []).find(q => q.symbol === B);
  if (pa && pb) $("c-w").value = Math.round(pa.weight_pct / (pa.weight_pct + pb.weight_pct) * 100);
  corrUpdate();
}

function corrUpdate() {
  const w = parseInt($("c-w").value, 10) / 100;
  const rho = parseInt($("c-r").value, 10) / 100;
  const { s1, s2, n1, n2 } = CORR;
  $("c-wlab").textContent = Math.round(w * 100) + "%";
  $("c-rlab").textContent = fmt(rho, 2);
  const avg = w * s1 + (1 - w) * s2;
  const combo = Math.sqrt(Math.max(0, w*w*s1*s1 + (1-w)*(1-w)*s2*s2 + 2*w*(1-w)*rho*s1*s2));
  const scale = Math.max(s1, s2) * 1.05;
  $("c-o1").textContent = fmt(avg, 1) + "%";
  $("c-o2").textContent = fmt(combo, 1) + "%";
  $("c-bar1").style.width = (avg / scale * 100) + "%";
  $("c-bar2").style.width = (combo / scale * 100) + "%";
  const saved = avg - combo;
  $("c-read").textContent =
    rho >= 0.95 ? `At correlation ~1, the combination saves you nothing — ${n1} and ${n2} would just be one position with extra paperwork.` :
    saved < 1   ? `Only ${fmt(saved,1)} points of volatility cancelled — at ρ=${fmt(rho,2)}, these two mostly rise and fall together.` :
    rho <= 0    ? `${fmt(saved,1)} points of volatility simply vanish (${fmt(avg,1)}% → ${fmt(combo,1)}%). Negative correlation is the closest thing to a free lunch in finance — and between two long stocks, about as rare.` :
                  `${fmt(saved,1)} points of volatility cancel out (${fmt(avg,1)}% → ${fmt(combo,1)}%) — risk that disappears without giving up either position. That cancellation is the entire product diversification sells.`;
}

["c-w", "c-r"].forEach(id => { const el = $(id); if (el) el.addEventListener("input", corrUpdate); });
if ($("c-w")) corrUpdate();

/* ========================================================================= */
/*  demo 4: VaR on the book's real return distribution                       */
/* ========================================================================= */

let RET = null;

(async function varDemo() {
  const cv = $("v-hist");
  if (!cv) return;
  try {
    const d = await (await fetch("/api/tutorial/returns")).json();
    if (!d.ok) { $("v-read").textContent = d.note || "No sized positions yet — the console can fix that."; return; }
    RET = d.returns_pct.slice().sort((a, b) => a - b);
    TOTAL = TOTAL || d.total_value;
    $("v-in").addEventListener("input", drawVar);
    window.addEventListener("resize", () => { clearTimeout(window._vt); window._vt = setTimeout(drawVar, 150); });
    drawVar();
  } catch (e) {
    $("v-read").textContent = "Couldn't load the return series — is the server still running?";
  }
})();

function drawVar() {
  const conf = parseInt($("v-in").value, 10);
  $("v-lab").textContent = conf + "%";
  const cv = $("v-hist");
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight || 180;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);

  const n = RET.length;
  const q = (1 - conf / 100) * (n - 1);
  const lo = Math.floor(q), fr = q - lo;
  const cut = RET[lo] * (1 - fr) + RET[Math.min(n - 1, lo + 1)] * fr;
  const tail = RET.filter(r => r <= cut);
  const cvar = tail.length ? tail.reduce((s, r) => s + r, 0) / tail.length : cut;

  // histogram
  const mn = RET[0], mx = RET[n - 1];
  const bins = 36, bw = (mx - mn) / bins || 1;
  const counts = new Array(bins).fill(0);
  RET.forEach(r => counts[Math.min(bins - 1, Math.floor((r - mn) / bw))]++);
  const peak = Math.max(...counts);

  const padB = 18, padT = 6;
  const X = (val) => ((val - mn) / (mx - mn)) * (W - 2) + 1;
  const up = css("--up") || "#43B37D", down = css("--down") || "#E5565C", dim = css("--text-dim") || "#5C6476";

  for (let i = 0; i < bins; i++) {
    const x0 = X(mn + i * bw), x1 = X(mn + (i + 1) * bw);
    const h = counts[i] / peak * (H - padB - padT);
    const mid = mn + (i + 0.5) * bw;
    ctx.fillStyle = mid <= cut ? down : (css("--accent") || "#7C83E8");
    ctx.globalAlpha = mid <= cut ? 0.85 : 0.45;
    ctx.fillRect(x0 + 0.5, H - padB - h, Math.max(1, x1 - x0 - 1), h);
  }
  ctx.globalAlpha = 1;

  // zero line + cutoff
  ctx.strokeStyle = dim; ctx.setLineDash([3, 4]);
  ctx.beginPath(); ctx.moveTo(X(0), padT); ctx.lineTo(X(0), H - padB); ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle = down; ctx.lineWidth = 1.6;
  ctx.beginPath(); ctx.moveTo(X(cut), padT); ctx.lineTo(X(cut), H - padB); ctx.stroke();

  ctx.font = "10px 'IBM Plex Mono', monospace"; ctx.fillStyle = dim;
  ctx.fillText(fmt(mn, 1) + "%", 2, H - 5);
  ctx.fillText("0", X(0) - 3, H - 5);
  ctx.fillText("+" + fmt(mx, 1) + "%", W - 38, H - 5);

  const oneIn = Math.round(1 / (1 - conf / 100));
  $("v-read").innerHTML =
    `At ${conf}%, the line sits at <b>${fmt(cut, 2)}%</b> (${TOTAL ? money(cut / 100 * TOTAL) : "—"}) — about 1 day in ${oneIn} has finished below it over the last year. ` +
    `When it broke, the breach days averaged <b>${fmt(cvar, 2)}%</b> (${TOTAL ? money(cvar / 100 * TOTAL) : "—"}). That average — CVaR — is the number the line itself refuses to tell you.`;
}

/* ========================================================================= */
/*  demo 5: terminal value share of a DCF                                    */
/* ========================================================================= */

(function tvDemo() {
  const r = $("tv-r");
  if (!r) return;
  const upd = () => {
    const rr = parseFloat($("tv-r").value) / 100;
    const gt = parseFloat($("tv-g").value) / 100;
    $("tv-rlab").textContent = fmt(rr * 100, 1) + "%";
    $("tv-glab").textContent = fmt(gt * 100, 2) + "%";
    let fcf = 100, pvStage = 0;
    for (let t = 1; t <= 10; t++) { fcf *= 1.05; pvStage += fcf / Math.pow(1 + rr, t); }
    const pvTV = (fcf * (1 + gt) / (rr - gt)) / Math.pow(1 + rr, 10);
    const share = pvTV / (pvStage + pvTV) * 100;
    $("tv-o1").textContent = fmt(100 - share, 0) + "%";
    $("tv-o2").textContent = fmt(share, 0) + "%";
    $("tv-b1").style.width = (100 - share) + "%";
    $("tv-b2").style.width = share + "%";
    $("tv-read").textContent =
      share >= 70 ? `${fmt(share,0)}% of this valuation is the "forever" assumption. Ten years of actual forecasting decide the minority — which is why two analysts with the same spreadsheet can be 40% apart and both be "rigorous."` :
                    `${fmt(share,0)}% of the value sits past year ten. Higher discount rates shrink the forever-part's grip — one honest argument for demanding more than the textbook rate.`;
  };
  ["tv-r", "tv-g"].forEach(id => $(id).addEventListener("input", upd)); upd();
})();

/* ========================================================================= */
/*  demo 6: leverage amplification                                           */
/* ========================================================================= */

(function levDemo() {
  const a = $("lv-a");
  if (!a) return;
  const upd = () => {
    const ar = parseInt($("lv-a").value, 10);
    const d = parseInt($("lv-d").value, 10);
    $("lv-alab").textContent = (ar >= 0 ? "+" : "") + ar + "%";
    $("lv-dlab").textContent = d + "%";
    const eqIn = 100 - d;
    const eqOut = Math.max(0, 100 * (1 + ar / 100) - d);
    const eqR = (eqOut / eqIn - 1) * 100;
    $("lv-read").innerHTML = eqOut <= 0
      ? `The asset fell ${Math.abs(ar)}% against ${d}% debt: equity is <b>wiped out (−100%)</b>. The lender gets the keys. Leverage has no memory of your good years.`
      : `A ${ar >= 0 ? "+" : ""}${ar}% move in the asset becomes <b>${eqR >= 0 ? "+" : ""}${fmt(eqR, 0)}%</b> on the equity slice at ${d}% debt — a ${fmt(Math.abs(d < 100 ? 1 / (1 - d / 100) : 0), 1)}× multiplier that works exactly as hard against you. Interest, ignored here, makes both directions worse.`;
  };
  ["lv-a", "lv-d"].forEach(id => $(id).addEventListener("input", upd)); upd();
})();

/* ========================================================================= */
/*  table of contents scrollspy                                              */
/* ========================================================================= */

(function spy() {
  const links = [...document.querySelectorAll("#toc a")];
  const map = new Map(links.map(l => [l.getAttribute("href").slice(1), l]));
  const obs = new IntersectionObserver((entries) => {
    entries.forEach(en => {
      if (en.isIntersecting) {
        links.forEach(l => l.classList.remove("on"));
        const l = map.get(en.target.id);
        if (l) l.classList.add("on");
      }
    });
  }, { rootMargin: "-15% 0px -75% 0px" });
  document.querySelectorAll(".prose h2[id]").forEach(h => obs.observe(h));
})();
