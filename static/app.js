/* Windrose console v2 — vanilla JS, no framework.

   Adds: canvas price charts (close + SMA20/50), table sparklines,
   conditions-score bars, weight-vs-risk paired bars, VaR/CVaR block. */

// Anything that came from a person, a contributed data file, or an external
// API is untrusted and must not be interpolated raw into innerHTML. A crafted
// supply-chain label was able to run arbitrary JavaScript here.
function esc(v) {
  if (v === null || v === undefined) return "";
  return String(v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}


const THEMES = [
  ["auto",     "Auto",          "follows your system setting"],
  ["graphite", "Graphite",      "dark, ember accent"],
  ["midnight", "Midnight",      "deep navy, easier at night"],
  ["terminal", "Terminal",      "phosphor green, mono everywhere"],
  ["paper",    "Paper",         "clean light"],
  ["sepia",    "Sepia",         "warm light, gentler for long reads"],
  ["contrast", "High contrast", "maximum legibility"],
];

// Layout presets. Each names the panels for the two columns and the full-width
// row; anything unlisted is hidden. They exist because "arrange 10 panels
// yourself" is not a reasonable first experience.
const PRESETS = {
  overview: {
    label: "Overview",
    blurb: "Everything, in a sensible order. The default.",
    left: ["holdings", "benchmark", "alerts", "journal"],
    right: ["risk", "sandbox"],
    full: ["chokepoints", "perholding", "workbench", "chain"],
  },
  watching: {
    label: "Watching",
    blurb: "For market hours. Positions, alerts and news up top, analysis out of the way.",
    left: ["holdings", "alerts"],
    right: ["risk", "journal"],
    full: ["chain"],
  },
  research: {
    label: "Research",
    blurb: "Digging into one company. Workbench and the map get the space.",
    left: ["holdings", "perholding"],
    right: ["risk"],
    full: ["workbench", "chain", "chokepoints"],
  },
  risk: {
    label: "Risk",
    blurb: "How the book behaves as a whole, and what it rests on.",
    left: ["holdings", "benchmark"],
    right: ["risk", "sandbox"],
    full: ["chokepoints", "perholding"],
  },
  minimal: {
    label: "Minimal",
    blurb: "Am I up, and am I beating the index? Nothing else.",
    left: ["holdings"],
    right: ["benchmark"],
    full: [],
  },
};

/* The saved layout is an ordered list of columns plus a full-width row:
   {cols: [[...ids], [...ids]], full: [...ids]}. It is stored at whatever
   column count it was arranged in and is never rewritten by a resize —
   fitPlan() adapts it to the window on the way to the screen, folding columns
   together when there is no room and splitting them apart when there is. Both
   directions are pure, so widening a window undoes narrowing it exactly, and
   a layout saved on a 27" monitor still opens on a laptop with everything in
   it. Only a drag writes to disk. */
const LAYOUT_KEY = "windrose-layout3";
let LAYOUT_COLS = 0;          // columns currently on screen

/* 3 columns past ~1600px, 4 past ~2100px. Two is the floor on a laptop and one
   on a phone. Ordered widest-first; the first match wins. */
const COL_BREAKS = [[2100, 4], [1600, 3], [1000, 2], [0, 1]];

const DEF_PLAN = {
  cols: [["holdings", "benchmark", "alerts", "journal"], ["risk", "sandbox"]],
  full: ["chokepoints", "perholding", "workbench", "chain"],
};

function colCount(w) {
  w = w == null ? window.innerWidth : w;
  for (const [min, n] of COL_BREAKS) if (w >= min) return n;
  return 1;
}

/* Roughly how tall each panel runs, from data-weight in the template. Used
   only to decide where to split a column — a wrong number costs balance, never
   correctness. Counting panels instead was tried first and put Portfolio risk,
   which is taller than the other three put together, alone in the fourth
   column beside three short ones. */
function panelWeight(id) {
  const el = document.querySelector(`.panel[data-panel="${id}"]`);
  const w = el && parseFloat(el.dataset.weight);
  return w > 0 ? w : 4;
}
const colWeight = (ids) => ids.reduce((t, id) => t + panelWeight(id), 0);

/* Adapt a saved column list to n columns without mutating it.
   Too many columns for the window: column i folds into column i % n, so
   nothing is hidden and the fold is reversible. Too few: the heaviest column
   splits at its most even point, repeatedly, until every column is used — an
   empty column on a wide monitor is the thing this whole change exists to
   remove. Weights are declared rather than measured so that the same window
   width always produces the same arrangement, before and after the data
   arrives. */
function fitPlan(cols, n) {
  const out = (cols || []).map(c => c.slice()).filter(c => c.length);
  if (!out.length) return Array.from({ length: n }, () => []);
  while (out.length > n) {
    const tail = out.pop();
    out[out.length % n].push(...tail);
  }
  while (out.length < n) {
    let bi = -1, best = 0;
    out.forEach((c, i) => {
      const w = c.length > 1 ? colWeight(c) : 0;   // a lone panel cannot split
      if (w > best) { best = w; bi = i; }
    });
    if (bi < 0) break;                       // nothing left worth splitting
    const col = out[bi];
    let run = 0, cut = 1, bestGap = Infinity;
    for (let k = 0; k < col.length - 1; k++) {
      run += panelWeight(col[k]);
      const gap = Math.abs(best - 2 * run);  // |rest - head|, minimised
      if (gap < bestGap) { bestGap = gap; cut = k + 1; }
    }
    out.splice(bi + 1, 0, col.slice(cut));
    out[bi] = col.slice(0, cut);
  }
  while (out.length < n) out.push([]);       // genuinely fewer panels than columns
  return out;
}

// localStorage is editable by hand and survives version changes, so nothing
// out of it is trusted to be the shape it was written in.
const idList = (v) => (Array.isArray(v) ? v.filter(x => typeof x === "string") : []);

function loadPlan() {
  try {
    const p = JSON.parse(localStorage.getItem(LAYOUT_KEY) || "null");
    if (p && Array.isArray(p.cols)) {
      return { cols: p.cols.map(idList).filter(c => c.length), full: idList(p.full) };
    }
  } catch (e) {}
  // pre-v5.6 shape, under both keys it was ever written to
  for (const k of ["ledger-layout2", "windrose-layout2"]) {
    try {
      const o = JSON.parse(localStorage.getItem(k) || "null");
      if (o && Array.isArray(o.left)) {
        return { cols: [idList(o.left), idList(o.right)].filter(c => c.length), full: idList(o.full) };
      }
    } catch (e) {}
  }
  return { cols: DEF_PLAN.cols.map(c => c.slice()), full: DEF_PLAN.full.slice() };
}

function applyPreset(name) {
  const p = PRESETS[name];
  if (!p) return;
  const all = Object.keys(PANEL_LABELS);
  const shown = [...p.left, ...p.right, ...p.full];
  // A preset is a two-column arrangement; fitPlan splits it out again on a
  // wide screen. It has to be written under the key the layout engine reads —
  // this used to write "windrose-layout2" while initLayout read
  // "ledger-layout2", so choosing a preset hid the right panels and then moved
  // none of them.
  try {
    localStorage.setItem(LAYOUT_KEY,
      JSON.stringify({ cols: [p.left, p.right], full: p.full }));
  } catch (e) {}
  SET.hidden = all.filter(x => !shown.includes(x));
  SET.preset = name;
  saveSettings({ hidden: SET.hidden, preset: name });
  location.reload();     // the layout engine places panels at boot
}

const $  = (id) => document.getElementById(id);
const fmtMoney = (n, d = 2) => (n == null ? "—" : "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }));
const fmtNum   = (n, d = 2) => (n == null ? "—" : Number(n).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d }));
const signPct  = (n) => (n == null ? "—" : (n >= 0 ? "+" : "") + Number(n).toFixed(2) + "%");
const cls      = (n) => (n == null ? "" : n >= 0 ? "up" : "down");

let HOLDINGS = [];
let SPARK = {};            // sym -> {dates, close, sma20, sma50}
const lastPrice = {};

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function accentRGBA(a) {
  let h = (css("--accent") || "#7C83E8").replace("#", "");
  if (h.length === 3) h = h.split("").map(c => c + c).join("");
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

/* ======================= canvas drawing ================================== */

function drawLine(ctx, xs, ys, color, width) {
  ctx.strokeStyle = color; ctx.lineWidth = width;
  ctx.beginPath();
  let started = false;
  for (let i = 0; i < xs.length; i++) {
    if (ys[i] == null) continue;
    if (!started) { ctx.moveTo(xs[i], ys[i]); started = true; }
    else ctx.lineTo(xs[i], ys[i]);
  }
  ctx.stroke();
}

function seriesChart(canvas, data, sym) {
  // full chart: close (bright) + SMA20 + SMA50, fill under close, hi/lo labels
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight || 120;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);

  const all = [...data.close, ...data.sma20, ...data.sma50].filter(v => v != null);
  if (!all.length) return;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (hi === lo) { hi += 1; lo -= 1; }
  const padT = 12, padB = 14, padL = 2, padR = 44;
  const X = (i) => padL + (i / (data.close.length - 1)) * (W - padL - padR);
  const Y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);

  const xs = data.close.map((_, i) => X(i));
  const yC  = data.close.map(v => v == null ? null : Y(v));
  const y20 = data.sma20.map(v => v == null ? null : Y(v));
  const y50 = data.sma50.map(v => v == null ? null : Y(v));

  // fill under close
  const closeColor = css("--accent") || "#7C83E8";
  ctx.beginPath();
  let first = null, last = null;
  for (let i = 0; i < xs.length; i++) {
    if (yC[i] == null) continue;
    if (first == null) { first = i; ctx.moveTo(xs[i], yC[i]); }
    else ctx.lineTo(xs[i], yC[i]);
    last = i;
  }
  if (first != null) {
    ctx.lineTo(xs[last], H - padB + 6); ctx.lineTo(xs[first], H - padB + 6); ctx.closePath();
    const g = ctx.createLinearGradient(0, 0, 0, H);
    g.addColorStop(0, accentRGBA(.22)); g.addColorStop(1, accentRGBA(0));
    ctx.fillStyle = g; ctx.fill();
  }

  drawLine(ctx, xs, y50, "rgba(154,164,182,.55)", 1);
  drawLine(ctx, xs, y20, (css("--warn") || "#D9A441"), 1);
  drawLine(ctx, xs, yC, closeColor, 1.6);

  // last-price marker + hi/lo labels
  if (last != null) {
    ctx.fillStyle = closeColor;
    ctx.beginPath(); ctx.arc(xs[last], yC[last], 2.6, 0, Math.PI * 2); ctx.fill();
  }
  ctx.font = "9.5px 'IBM Plex Mono', monospace";
  ctx.fillStyle = "rgba(154,164,182,.85)";
  ctx.textAlign = "left";
  ctx.fillText(hi.toFixed(hi >= 1000 ? 0 : 2), W - padR + 6, padT + 4);
  ctx.fillText(lo.toFixed(lo >= 1000 ? 0 : 2), W - padR + 6, H - padB + 2);

  // journal markers: ▲ buys, ▼ sells, ◆ notes — on the dates you logged
  if (sym && window.JOURNAL_BY_SYM && JOURNAL_BY_SYM[sym] && data.dates) {
    const upC = css("--up") || "#43B37D", dnC = css("--down") || "#E5565C";
    for (const e of JOURNAL_BY_SYM[sym]) {
      let idx = data.dates.indexOf(e.date);
      if (idx === -1) {           // nearest date at/after the entry
        idx = data.dates.findIndex(d => d >= e.date);
        if (idx === -1) continue;
      }
      const x = xs[idx], y = yC[idx];
      if (y == null) continue;
      ctx.beginPath();
      if (e.side === "buy") {
        ctx.fillStyle = upC;
        ctx.moveTo(x, y + 14); ctx.lineTo(x - 4.5, y + 21); ctx.lineTo(x + 4.5, y + 21);
      } else if (e.side === "sell") {
        ctx.fillStyle = dnC;
        ctx.moveTo(x, y - 14); ctx.lineTo(x - 4.5, y - 21); ctx.lineTo(x + 4.5, y - 21);
      } else {
        ctx.fillStyle = "rgba(154,164,182,.9)";
        ctx.rect(x - 3, y - 17, 6, 6);
      }
      ctx.closePath(); ctx.fill();
    }
  }
}

function sparkline(canvas, closes) {
  const dpr = window.devicePixelRatio || 1;
  // the canvas is what sets the row height in the holdings table, so it has to
  // shrink with the density or 11px rows sit in 26px of empty space
  const dense = document.body.dataset.density === "dense";
  const W = dense ? 72 : 92, H = dense ? 15 : 26;
  canvas.width = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W + "px"; canvas.style.height = H + "px";
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const vals = closes.filter(v => v != null);
  if (vals.length < 2) return;
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) { hi += 1; lo -= 1; }
  const X = (i) => (i / (closes.length - 1)) * (W - 2) + 1;
  const Y = (v) => 2 + (1 - (v - lo) / (hi - lo)) * (H - 5);
  const upTrend = vals[vals.length - 1] >= vals[0];
  const color = upTrend ? (css("--up") || "#43B37D") : (css("--down") || "#E5565C");
  ctx.strokeStyle = color; ctx.lineWidth = 1.2; ctx.beginPath();
  let started = false;
  closes.forEach((v, i) => {
    if (v == null) return;
    if (!started) { ctx.moveTo(X(i), Y(v)); started = true; }
    else ctx.lineTo(X(i), Y(v));
  });
  ctx.stroke();
}

/* ---- small panel charts -------------------------------------------------
   Every panel that has a series behind it gets a picture of it. These reuse
   the same 2d-canvas approach as the holdings charts rather than pulling in a
   charting library: the app has no build step, and a line with a fill under it
   is not worth 200KB of dependency.

   All of them read their colours from CSS variables at draw time, so themes
   and colour-blind-safe mode carry through without the charts knowing. */

function miniChart(canvas, lines, opts) {
  opts = opts || {};
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight || 80;
  if (!W || !H) return;                       // hidden panel — nothing to size to
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const all = [];
  for (const l of lines) for (const v of l.values) if (v != null && isFinite(v)) all.push(v);
  if (all.length < 2) return;
  let lo = Math.min(...all), hi = Math.max(...all);
  if (opts.zero != null) { lo = Math.min(lo, opts.zero); hi = Math.max(hi, opts.zero); }
  if (hi === lo) { hi += Math.abs(hi) * 0.01 || 1; lo -= Math.abs(lo) * 0.01 || 1; }

  const labels = opts.labels !== false;
  const padT = 6, padB = 5, padL = 1, padR = labels ? 42 : 2;
  const len = Math.max(...lines.map(l => l.values.length));
  const X = (i) => padL + (i / Math.max(1, len - 1)) * (W - padL - padR);
  const Y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);

  if (opts.zero != null) {                    // the line that means "flat"
    ctx.strokeStyle = css("--line") || "#222938";
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(padL, Y(opts.zero)); ctx.lineTo(W - padR, Y(opts.zero)); ctx.stroke();
  }

  for (const l of lines) {
    const xs = l.values.map((_, i) => X(i));
    const ys = l.values.map(v => (v == null || !isFinite(v)) ? null : Y(v));
    if (l.fill) {
      const base = opts.zero != null ? Y(opts.zero) : H - padB;
      ctx.beginPath();
      let first = null, last = null;
      for (let i = 0; i < xs.length; i++) {
        if (ys[i] == null) continue;
        if (first == null) { first = i; ctx.moveTo(xs[i], ys[i]); } else ctx.lineTo(xs[i], ys[i]);
        last = i;
      }
      if (first != null) {
        ctx.lineTo(xs[last], base); ctx.lineTo(xs[first], base); ctx.closePath();
        const g = ctx.createLinearGradient(0, padT, 0, H);
        g.addColorStop(0, l.fill); g.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = g; ctx.fill();
      }
    }
    drawLine(ctx, xs, ys, l.color, l.width || 1.4);
    const li = l.values.length - 1;
    if (l.dot !== false && ys[li] != null) {
      ctx.fillStyle = l.color;
      ctx.beginPath(); ctx.arc(xs[li], ys[li], 2.2, 0, Math.PI * 2); ctx.fill();
    }
  }

  if (labels) {
    const f = opts.fmt || ((v) => v.toFixed(Math.abs(v) >= 100 ? 0 : 1));
    ctx.font = "9.5px 'IBM Plex Mono', monospace";
    ctx.fillStyle = css("--text-dim") || "#5C6476";
    ctx.textAlign = "left";
    ctx.fillText(f(hi), W - padR + 5, padT + 4);
    ctx.fillText(f(lo), W - padR + 5, H - padB);
  }
}

/* Histogram of daily portfolio returns, with the VaR and CVaR cut-offs drawn
   on it. The bars and the numbers in the panel above come from the same array,
   so where the marker falls is where the loss figure came from. */
function histChart(canvas, h) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight || 60;
  if (!W || !H || !h || !h.counts || !h.counts.length) return;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  const lo = h.edges[0], hi = h.edges[h.edges.length - 1];
  if (hi <= lo) return;
  const maxC = Math.max(...h.counts) || 1;
  const padB = 11, padT = 3;
  const X = (v) => ((v - lo) / (hi - lo)) * W;
  const upC = css("--up") || "#43B37D", dnC = css("--down") || "#E5565C";

  for (let i = 0; i < h.counts.length; i++) {
    const x0 = X(h.edges[i]), x1 = X(h.edges[i + 1]);
    const bh = (h.counts[i] / maxC) * (H - padT - padB);
    ctx.fillStyle = h.edges[i] < 0 ? dnC : upC;
    ctx.globalAlpha = 0.45;
    ctx.fillRect(x0 + 0.5, H - padB - bh, Math.max(1, x1 - x0 - 1), bh);
  }
  ctx.globalAlpha = 1;

  ctx.font = "9.5px 'IBM Plex Mono', monospace";
  for (const [v, lab, col] of [[h.var95_pct, "VaR95", dnC], [h.cvar95_pct, "CVaR", css("--warn") || "#D9A441"]]) {
    if (v == null || v < lo || v > hi) continue;
    const x = X(v);
    ctx.strokeStyle = col; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, padT); ctx.lineTo(x, H - padB); ctx.stroke();
    ctx.fillStyle = col;
    ctx.textAlign = x < W * 0.4 ? "left" : "right";
    ctx.fillText(lab, x + (x < W * 0.4 ? 3 : -3), padT + 8);
  }
  ctx.fillStyle = css("--text-dim") || "#5C6476";
  ctx.textAlign = "left";  ctx.fillText(lo.toFixed(1) + "%", 1, H - 2);
  ctx.textAlign = "right"; ctx.fillText(hi.toFixed(1) + "%", W - 1, H - 2);
}

/* The panel canvases repaint from whatever the last fetch left behind, so a
   resize or a column change never needs the network. */
let PORTF = null, BENCH = null;

function drawPanelCharts() {
  document.querySelectorAll("canvas.pchart[data-pchart]").forEach(cv => {
    const kind = cv.dataset.pchart;
    const sr = PORTF && PORTF.series;
    if (kind === "equity" && sr && sr.equity) {
      miniChart(cv, [{ values: sr.equity, color: css("--accent") || "#7C83E8", width: 1.5, fill: accentRGBA(.22) }],
                { fmt: v => v.toFixed(1) });
    } else if (kind === "drawdown" && sr && sr.drawdown) {
      miniChart(cv, [{ values: sr.drawdown, color: css("--down") || "#E5565C", width: 1.2, fill: "rgba(229,86,92,.28)", dot: false }],
                { zero: 0, fmt: v => v.toFixed(0) + "%" });
    } else if (kind === "returns" && sr && sr.returns) {
      histChart(cv, sr.returns);
    } else if (kind === "bench" && BENCH && BENCH.series && BENCH.series.book) {
      miniChart(cv, [
        { values: BENCH.series.shadow, color: css("--warn") || "#D9A441", width: 1.2, dot: false },
        { values: BENCH.series.book, color: css("--accent") || "#7C83E8", width: 1.5, fill: accentRGBA(.18) },
      ], { fmt: v => (v >= 10000 ? (v / 1000).toFixed(0) + "k" : v.toFixed(0)) });
    }
  });
}

/* ======================= clock / status ================================== */

setInterval(() => { $("clock").textContent = new Date().toLocaleTimeString(); }, 1000);

async function pollStatus() {
  try {
    const s = await (await fetch("/api/status")).json();
    const m = $("mkt");
    if (s.market.open) { m.className = "mkt open"; m.textContent = "● OPEN · " + s.market.et; }
    else { m.className = "mkt closed"; m.textContent = "○ CLOSED · " + s.market.et; }
  } catch (e) {}
}

/* ======================= live prices ===================================== */

function applyQuotes(q, src) {
  const dot = $("livedot"), hb = $("heartbeat");
  if (src === "alpaca-ws") { dot.className = "dot on"; hb.title = "streaming — alpaca websocket"; }
  else if (src === "alpaca-iex") { dot.className = "dot on"; hb.title = "live — alpaca iex"; }
  else if (src === "yfinance-delayed") { dot.className = "dot warn"; hb.title = "delayed quotes — add Alpaca keys to .env for live"; }
  else { dot.className = "dot off"; hb.title = "no data feed"; }
  if (src && src !== "none") { dot.classList.remove("pulse"); void dot.offsetWidth; dot.classList.add("pulse"); }

  for (const h of HOLDINGS) {
    const row = document.querySelector(`tr[data-sym="${h.symbol}"]`);
    const quote = q[h.symbol];
    if (!row || !quote || quote.price == null) continue;
    const px = quote.price;
    const pxCell = row.querySelector(".px");
    if (lastPrice[h.symbol] != null && px !== lastPrice[h.symbol]) {
      pxCell.classList.remove("tick-up", "tick-down"); void pxCell.offsetWidth;
      pxCell.classList.add(px > lastPrice[h.symbol] ? "tick-up" : "tick-down");
    }
    lastPrice[h.symbol] = px;
    pxCell.textContent = fmtNum(px);
    const day = row.querySelector(".day");
    day.textContent = signPct(quote.change_pct);
    day.className = "day num " + cls(quote.change_pct);
    if (h.shares > 0) {
      const val = px * h.shares, pl = (px - h.cost_basis) * h.shares;
      const plp = h.cost_basis ? (px / h.cost_basis - 1) * 100 : null;
      row.querySelector(".val").textContent = fmtMoney(val);
      const plCell = row.querySelector(".pl"); plCell.textContent = (pl >= 0 ? "+" : "") + fmtMoney(pl); plCell.className = "pl num " + cls(pl);
      const plpCell = row.querySelector(".plp"); plpCell.textContent = signPct(plp); plpCell.className = "plp num " + cls(plp);
    }
  }
}

async function pollLive() {
  try {
    const data = await (await fetch("/api/live")).json();
    applyQuotes(data.quotes || {}, data.src);
  } catch (e) {}
}

/* SSE: the server pushes every tick; polling becomes the fallback. */
let SSE_OK = false, FALLBACK_TIMER = null;
function startStream() {
  try {
    const es = new EventSource("/api/stream");
    es.onmessage = (m) => {
      SSE_OK = true;
      if (FALLBACK_TIMER) { clearInterval(FALLBACK_TIMER); FALLBACK_TIMER = null; }
      try {
        const d = JSON.parse(m.data);
        if (d.type === "quotes") applyQuotes(d.quotes || {}, d.src);
        if (d.type === "alerts") onAlertEvents(d.events || []);
      } catch (e) {}
    };
    es.onerror = () => {
      if (!FALLBACK_TIMER) FALLBACK_TIMER = setInterval(pollLive, 1500);
    };
  } catch (e) {
    FALLBACK_TIMER = setInterval(pollLive, 1500);
  }
}

/* ======================= futures ========================================= */

const DEF_STRIP = ["ES=F", "NQ=F", "YM=F", "CL=F", "GC=F", "^VIX"];
function stripSyms() {
  try {
    const s = JSON.parse(localStorage.getItem("ledger-strip") || "null");
    if (Array.isArray(s) && s.length) return s;
  } catch (e) {}
  return DEF_STRIP;
}

async function pollFutures() {
  try {
    const syms = stripSyms();
    const fut = await (await fetch("/api/strip?symbols=" + encodeURIComponent(syms.join(",")))).json();
    const wrap = $("futures");
    if (wrap.querySelector(".stripform")) return;      // editor open — don't clobber
    if (!fut.length) { wrap.innerHTML = '<div class="fut"><span class="fl">strip unavailable</span></div>'; return; }
    wrap.innerHTML = fut.map(f => `
      <div class="fut">
        <span class="fl">${f.short}${f.symbol.endsWith("=F") ? " ·F" : ""}</span>
        <span class="fp num">${fmtNum(f.price)}</span>
        <span class="fc num ${cls(f.change_pct)}">${signPct(f.change_pct)}</span>
      </div>`).join("")
      + '<div class="fut futedit" id="stripedit" title="choose your own tickers for this strip">✎</div>';
    $("stripedit").addEventListener("click", stripEditor);
  } catch (e) {}
}

function stripEditor() {
  const wrap = $("futures");
  wrap.innerHTML = `<div class="stripform">
    <input id="stripin" value="${stripSyms().join(", ")}" spellcheck="false"
      placeholder="ES=F, NQ=F, ^VIX, AAPL, NVDA — futures need =F, indices ^">
    <button id="stripsave">save</button>
    <button id="stripcancel" class="ghost">cancel</button>
  </div>`;
  $("stripin").focus();
  const done = () => {
    wrap.innerHTML = '<div class="fut"><span class="fl">updating…</span></div>';
    pollFutures();
  };
  $("stripsave").addEventListener("click", () => {
    const syms = $("stripin").value.split(",").map(s => s.trim().toUpperCase()).filter(Boolean).slice(0, 12);
    try { localStorage.setItem("ledger-strip", JSON.stringify(syms.length ? syms : DEF_STRIP)); } catch (e) {}
    done();
  });
  $("stripcancel").addEventListener("click", done);
  $("stripin").addEventListener("keydown", e => { if (e.key === "Enter") $("stripsave").click(); if (e.key === "Escape") done(); });
}

/* ======================= holdings ======================================== */

async function loadHoldings() {
  HOLDINGS = await (await fetch("/api/holdings")).json();
  const body = $("holdbody");
  $("holdmeta").textContent = HOLDINGS.length ? `${HOLDINGS.length} position${HOLDINGS.length > 1 ? "s" : ""}` : "";
  if (!HOLDINGS.length) {
    body.innerHTML = `<tr><td colspan="9" class="empty">
      Nothing here yet — add your first position below.<br>
      <button class="samplebtn" id="samplebook">or load a sample book to look around</button>
    </td></tr>`;
    const sb = $("samplebook");
    if (sb) sb.addEventListener("click", async () => {
      sb.disabled = true; sb.textContent = "loading sample positions…";
      const SAMPLE = [
        { symbol: "AAPL", shares: 12, cost_basis: 268.40 },
        { symbol: "JPM",  shares: 8,  cost_basis: 331.75 },
        { symbol: "XOM",  shares: 20, cost_basis: 166.20 },
        { symbol: "KO",   shares: 35, cost_basis: 79.90 },
        { symbol: "UNH",  shares: 5,  cost_basis: 425.50 },
      ];
      for (const s of SAMPLE) {
        await fetch("/api/holdings", { method: "POST",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify(s) });
      }
      await loadHoldings(); loadAnalysis(); loadSpark(); loadEarnings();
      if (typeof loadChainQuotes === "function") loadChainQuotes();
    });
    return;
  }
  body.innerHTML = HOLDINGS.map(h => {
    const watch = h.shares > 0 ? "" : '<span class="watch-tag">WATCH</span>';
    return `<tr data-sym="${h.symbol}">
      <td class="l"><span class="caret" data-news="${esc(h.symbol)}">▸</span><span class="sym">${esc(h.symbol)}</span>${watch}</td>
      <td class="l sparkcell"><canvas data-spark="${h.symbol}"></canvas></td>
      <td class="px num">—</td>
      <td class="day num">—</td>
      <td class="num">${h.shares || 0}</td>
      <td class="val num">${h.shares > 0 ? "—" : ""}</td>
      <td class="pl num">${h.shares > 0 ? "—" : ""}</td>
      <td class="plp num">${h.shares > 0 ? "—" : ""}</td>
      <td><button class="edit" title="Edit" data-edit="${h.symbol}">✎</button><button class="del" title="Remove" data-del="${h.symbol}">✕</button></td>
    </tr>`;
  }).join("");
  body.querySelectorAll("[data-del]").forEach(b =>
    b.addEventListener("click", () => deletePosition(b.dataset.del)));
  body.querySelectorAll("[data-news]").forEach(c =>
    c.addEventListener("click", () => toggleSymNews(c.dataset.news)));
  [...OPEN_NEWS].forEach(s => { OPEN_NEWS.delete(s); toggleSymNews(s); });
  body.querySelectorAll("[data-edit]").forEach(b =>
    b.addEventListener("click", () => {
      const h = HOLDINGS.find(x => x.symbol === b.dataset.edit);
      if (!h) return;
      $("in-sym").value = h.symbol; $("in-shares").value = h.shares;
      $("in-cost").value = h.cost_basis; $("in-date").value = h.acquired || "";
      $("in-date").focus();
    }));
  drawSparklines();
  pollLive();
}

async function loadSpark() {
  try {
    SPARK = await (await fetch("/api/spark")).json();
    drawSparklines();
    drawCharts();
  } catch (e) {}
}

function drawSparklines() {
  document.querySelectorAll("[data-spark]").forEach(cv => {
    const d = SPARK[cv.dataset.spark];
    if (d) sparkline(cv, d.close);
  });
}

function drawCharts() {
  document.querySelectorAll("canvas.chart[data-chart]").forEach(cv => {
    const d = SPARK[cv.dataset.chart];
    if (d) seriesChart(cv, d, cv.dataset.chart);
  });
}

/* One repaint entry point. Canvases size themselves to their container, so
   anything that changes a container — a resize, a column-count change, a drag,
   soloing a panel — has to come back through here or half the panels keep
   painting at their old width. */
function repaintPanels() {
  drawSparklines();
  drawCharts();
  drawPanelCharts();
  if (typeof chainDraw === "function" && CH && CH.nodes) chainDraw();
}

async function addPosition() {
  const sym = $("in-sym").value.trim().toUpperCase();
  if (!sym) { $("in-sym").focus(); return; }
  const shares = parseFloat($("in-shares").value) || 0;
  const cost = parseFloat($("in-cost").value) || 0;
  await fetch("/api/holdings", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: sym, shares, cost_basis: cost, acquired: $("in-date").value.trim() || null }),
  });
  $("in-sym").value = ""; $("in-shares").value = ""; $("in-cost").value = ""; $("in-date").value = "";
  await loadHoldings();
  loadAnalysis(); loadSpark(); loadDividends(); loadBenchmark(); loadSandbox(); loadJournal(); loadEarnings();
}

async function deletePosition(sym) {
  await fetch("/api/holdings/" + sym, { method: "DELETE" });
  delete lastPrice[sym];
  await loadHoldings();
  loadAnalysis(); loadSpark(); loadDividends(); loadBenchmark(); loadSandbox(); loadJournal(); loadEarnings();
}

/* ======================= analysis ======================================== */

async function loadAnalysis() {
  let a;
  try { a = await (await fetch("/api/analysis")).json(); }
  catch (e) { return; }
  $("anmeta").textContent = a.generated_at ? "as of " + a.generated_at : "";
  PORTF = a.portfolio;
  renderPortfolio(a.portfolio);
  renderStocks(a.stocks || []);
  drawCharts();
}

function renderPortfolio(p) {
  const el = $("portfolio");
  if (!p || !p.ok) {
    el.innerHTML = `<div class="empty">${(p && p.reason) || "No portfolio data yet."}</div>`;
    return;
  }
  const c = p.concentration || {};
  const rc = p.risk_contribution || {};
  const corr = p.correlation || {};
  const syms = Object.keys(corr);
  const v = p.var || {};
  const sr = p.series || {};

  // signature: weight vs risk-contribution paired bars
  const wrRows = (p.positions || []).map(pos => {
    const risk = rc[pos.symbol] != null ? rc[pos.symbol] : 0;
    return `<div class="wr-row">
      <div class="wr-sym">${pos.symbol}</div>
      <div class="wr-bars">
        <div class="wr-bar"><div class="wr-fill weight" style="width:${pos.weight_pct}%"></div></div>
        <div class="wr-bar"><div class="wr-fill risk" style="width:${risk}%"></div></div>
        <div class="wr-lab"><span>weight ${fmtNum(pos.weight_pct, 0)}%</span><span>risk ${fmtNum(risk, 0)}%</span></div>
      </div>
    </div>`;
  }).join("");

  let corrHtml = "";
  if (syms.length > 1) {
    corrHtml = `<div class="sect advonly">Correlation (daily returns, 1y)</div>
      <table class="corr"><tr><th></th>${syms.map(s => `<th>${s}</th>`).join("")}</tr>
      ${syms.map(r => `<tr><th>${r}</th>${syms.map(cc => {
        const val = corr[r][cc];
        const self = r === cc;
        const color = self ? "" : (val >= 0.6 ? "down" : val <= 0.2 ? "up" : "");
        return `<td class="${self ? "self" : ""} ${color}">${self ? "—" : (val == null ? "·" : val.toFixed(2))}</td>`;
      }).join("")}</tr>`).join("")}</table>`;
  }

  el.innerHTML = `
    <div class="bignum">${fmtMoney(p.total_value)}</div>
    <div class="bigsub ${cls(p.total_pl_dollar)}">
      ${p.total_pl_dollar >= 0 ? "+" : ""}${fmtMoney(p.total_pl_dollar)} (${signPct(p.total_pl_pct)}) all-in
    </div>
    ${sr.equity ? `<div class="chartlab" style="margin-top:8px"><span>book, rebased to 100 over the price window</span>
        <span><b>${fmtNum(sr.equity[sr.equity.length - 1], 1)}</b></span></div>
      <canvas class="pchart" data-pchart="equity"></canvas>` : ""}

    <div class="statgrid">
      <div class="stat"><div class="k">Effective holdings</div><div class="v">${fmtNum(c.effective_holdings, 2)} <span class="dim">/ ${c.n_positions}</span></div></div>
      <div class="stat"><div class="k">Beta vs S&P</div><div class="v">${fmtNum(p.beta, 2)}</div></div>
      <div class="stat advonly"><div class="k">Diversification</div><div class="v">${fmtNum(p.diversification_ratio, 2)}×</div></div>
      <div class="stat advonly"><div class="k">Vol (current regime)</div><div class="v">${fmtNum(p.ewma_vol_pct, 1)}%</div></div>
      <div class="stat advonly"><div class="k">Vol (1y avg)</div><div class="v">${fmtNum(p.vol_annual_pct, 1)}%</div></div>
      <div class="stat"><div class="k">Max drawdown</div><div class="v down">${fmtNum(p.max_drawdown_pct, 1)}%</div></div>
    </div>

    <div class="sect">Where the money is vs what moves it</div>
    <div class="wr">${wrRows}</div>
    <div class="wr-legend"><span class="li-w"><i></i>share of value</span><span class="li-r"><i></i>share of risk</span></div>

    ${sr.drawdown ? `<div class="sect advonly">Underwater — how far below the last peak</div>
      <canvas class="pchart short advonly" data-pchart="drawdown"></canvas>` : ""}

    <div class="sect advonly">A bad day, in dollars</div>
    ${sr.returns ? `<canvas class="pchart short advonly" data-pchart="returns"></canvas>
      <div class="chartlab advonly">
        <span>every daily move in the window · the markers are the two cut-offs below</span></div>` : ""}
    <div class="varblock advonly">
      <div class="varcell"><div class="k">1-in-20 day (hist. VaR 95)</div><div class="v down">−${fmtMoney(v.hist_95_dollar)}</div><div class="s">${fmtNum(v.hist_95_pct, 1)}% · from actual returns</div></div>
      <div class="varcell"><div class="k">Average of those days (CVaR)</div><div class="v down">−${fmtMoney(v.cvar_95_dollar)}</div><div class="s">${fmtNum(v.cvar_95_pct, 1)}% · expected shortfall</div></div>
      <div class="varcell"><div class="k">1-in-100 day (hist. VaR 99)</div><div class="v down">−${fmtMoney(v.hist_99_dollar)}</div><div class="s">${fmtNum(v.hist_99_pct, 1)}%</div></div>
      <div class="varcell"><div class="k">Bell-curve estimate (95)</div><div class="v down">−${fmtMoney(v.param_95_dollar)}</div><div class="s">${fmtNum(v.param_95_pct, 1)}% · parametric</div></div>
    </div>

    <div class="riskread advonly">${p.risk_read || ""}</div>
    <div class="riskread simpleonly">${p.risk_read_plain || p.risk_read || ""}</div>
    ${corrHtml}`;

  drawPanelCharts();
}

function renderStocks(stocks) {
  const el = $("stocks");
  if (!stocks.length) { el.innerHTML = '<div class="empty">Per-holding breakdown appears here.</div>'; return; }

  el.innerHTML = stocks.map(s => {
    if (!s.trend) return `<div class="scard"><div class="hd"><span class="sym">${s.symbol}</span></div><div class="sm">${s.summary || ""}</div></div>`;
    const px = s.live_price != null ? s.live_price : s.price;
    const sc = s.score || {};
    const comp = sc.components || {};
    const scCls = sc.total >= 55 ? "up" : sc.total >= 45 ? "" : "down";
    const rsiCls = s.rsi == null ? "" : (s.rsi >= 70 || s.rsi <= 30 ? "bad" : s.rsi >= 50 ? "good" : "");
    const momCls = s.mom_20d == null ? "" : (s.mom_20d >= 0 ? "good" : "bad");
    const rsCls  = s.rs_20d == null ? "" : (s.rs_20d >= 0 ? "good" : "bad");
    const macdTag = s.macd_rising == null ? "" :
      `<span class="chip ${s.macd_rising ? "good" : "bad"}">MACD ${s.macd_rising ? "rising" : "fading"}</span>`;
    return `<div class="scard">
      <div class="hd">
        <span class="sym">${s.symbol}</span><span class="px">${fmtNum(px)}</span>
        <span class="sc ${scCls}"><b>${fmtNum(sc.total, 0)}</b>/100 ${sc.label || ""}</span>
      </div>
      <div class="scorebar"><div class="fill"></div><div class="tick" style="left:calc(${sc.total || 0}% - 1px)"></div></div>
      <div class="subscores">
        <span>trend <b>${fmtNum(comp.trend, 0)}</b></span>
        <span>mom <b>${fmtNum(comp.momentum, 0)}</b></span>
        <span>vs-SPY <b>${fmtNum(comp.rel, 0)}</b></span>
        <span>risk <b>${fmtNum(comp.risk, 0)}</b></span>
        <span>stretch <b>${fmtNum(comp.stretch, 0)}</b></span>
      </div>
      <canvas class="chart" data-chart="${s.symbol}"></canvas>
      <div class="sm">${s.summary || ""}</div>
      <div class="chips">
        <span class="chip ${rsiCls}">RSI <b>${fmtNum(s.rsi, 0)}</b></span>
        ${macdTag}
        <span class="chip ${momCls}">20d <b>${signPct(s.mom_20d)}</b></span>
        <span class="chip ${rsCls}">vs SPY <b>${signPct(s.rs_20d)}</b></span>
        <span class="chip">vol <b>${fmtNum(s.ewma_vol_pct != null ? s.ewma_vol_pct : s.vol_annual_pct, 0)}%</b></span>
        <span class="chip">maxDD <b>${fmtNum(s.max_drawdown_pct, 0)}%</b></span>
        <span class="chip">Sharpe <b>${fmtNum(s.sharpe, 2)}</b></span>
        <span class="chip">52w <b>${s.range_52w_pos != null ? Math.round(s.range_52w_pos * 100) + "%" : "—"}</b></span>
      </div>
      <div class="divline" id="divs-${s.symbol}"></div>
      <div class="outlook" id="outlook-${s.symbol}"><span class="ol-k">analyst outlook loading…</span></div>
    </div>`;
  }).join("");

  stocks.filter(s => s.trend).forEach(s => loadOutlook(s.symbol));
  fillDividendLines();
  drawCharts();
}

async function loadOutlook(sym) {
  try {
    const o = await (await fetch("/api/outlook/" + sym)).json();
    const el = $("outlook-" + sym);
    if (!el) return;
    if (!o.ok) { el.innerHTML = '<span class="ol-k">analyst outlook unavailable</span>'; return; }
    const implCls = o.implied_pct == null ? "" : (o.implied_pct >= 0 ? "up" : "down");
    el.innerHTML = `
      ${o.rating ? `<span><span class="ol-k">consensus</span> <span class="ol-v">${o.rating}</span>${o.n_analysts ? ` <span class="ol-k">(${o.n_analysts})</span>` : ""}</span>` : ""}
      ${o.target_mean ? `<span><span class="ol-k">target</span> <span class="ol-v">${fmtMoney(o.target_mean)}</span> <span class="${implCls}">${signPct(o.implied_pct)}</span></span>` : ""}
      ${o.next_earnings ? `<span><span class="ol-k">earnings</span> <span class="ol-v">${o.next_earnings}</span></span>` : ""}`;
  } catch (e) {}
}

/* ======================= news ============================================ */

const OPEN_NEWS = new Set();
const NEWS_CACHE = {};

async function fetchSymNews(sym) {
  const hit = NEWS_CACHE[sym];
  if (hit && Date.now() - hit.ts < 180000) return hit.items;
  const items = await (await fetch("/api/news/" + sym)).json();
  NEWS_CACHE[sym] = { ts: Date.now(), items };
  return items;
}

function renderNewsRows(items) {
  if (items.length && items[0]._notice) return `<div class="notice">${items[0]._notice}</div>`;
  if (!items.length) return '<div class="empty" style="padding:6px 0">Nothing in the last 10 days.</div>';
  return items.map(n => `
    <div class="nh">${n.url ? `<a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.headline)}</a>` : esc(n.headline)}</div>
    <div class="nm">${esc(n.source)} · ${esc(n.when)}</div>`).join("");
}

async function toggleSymNews(sym) {
  const row = document.querySelector(`tr[data-sym="${sym}"]`);
  if (!row) return;
  const caret = row.querySelector(".caret");
  const existing = row.nextElementSibling;
  if (existing && existing.classList.contains("symnews")) {
    existing.remove(); caret.classList.remove("open"); OPEN_NEWS.delete(sym); return;
  }
  OPEN_NEWS.add(sym); caret.classList.add("open");
  const tr = document.createElement("tr");
  tr.className = "symnews";
  tr.innerHTML = `<td colspan="9"><div class="empty" style="padding:4px 0">loading ${sym} news…</div></td>`;
  row.after(tr);
  const items = await fetchSymNews(sym);
  tr.innerHTML = `<td colspan="9">${renderNewsRows(items)}</td>`;
}

function initMarketWire() {
  const btn = $("newsbtn"), dd = $("newsdd");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    dd.classList.toggle("open");
    if (dd.classList.contains("open")) {
      dd.innerHTML = '<div class="empty">loading the wire…</div>';
      const items = await fetchSymNews("MARKET");
      dd.innerHTML = items.length && !items[0]._notice
        ? items.map(n => `<div class="nrow"><div class="nh"><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.headline)}</a></div><div class="nm">${esc(n.source)} · ${esc(n.when)}</div></div>`).join("")
        : renderNewsRows(items);
    }
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".newswrap")) dd.classList.remove("open");
  });
}

/* ======================= boot ============================================ */

$("addbtn").addEventListener("click", addPosition);
["in-sym", "in-shares", "in-cost", "in-date"].forEach(id =>
  $(id).addEventListener("keydown", e => { if (e.key === "Enter") addPosition(); }));

let resizeTimer;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { drawSparklines(); drawCharts(); drawPanelCharts(); }, 150);
});

(async function init() {
  initLayout();
  await loadHoldings();
  await loadSettings(); initChrome(); initSolo();
  setTimeout(checkForUpdate, 4000);
  setInterval(checkForUpdate, 6 * 3600 * 1000);
  pollStatus(); pollFutures(); loadAnalysis(); loadSpark(); initMarketWire();
  loadDividends(); loadBenchmark(); loadSandbox(); loadAlerts(); loadJournal(); loadEarnings(); initChain(); loadChokepoints();
  startStream();
  pollLive();                       // one immediate paint while SSE connects
  setInterval(pollStatus, 5000);
  setInterval(pollFutures, 15000);
  setInterval(loadAnalysis, 45000);
  setInterval(loadSpark, 300000);
  setInterval(loadEarnings, 1800000);
  try {
    const s = await (await fetch("/api/status")).json();
    window.APP_VERSION = s.version;
    applySettings();
    // ?walk=1 is how the learn page hands you back to the dashboard with the
    // advanced walkthrough already running. It beats the first-run tour.
    const wantWalk = new URLSearchParams(location.search).get("walk") === "1";
    if (wantWalk) {
      history.replaceState(null, "", location.pathname);   // don't re-fire on reload
      setTimeout(walkStart, 2200);
    } else if (!SET.mode) showWelcome();       // never chosen -> ask first
    else if (s.first_run) setTimeout(tourStart, 1600);
  } catch (e) {}
})();

/* ======================================================================== */
/*  MODELS WORKBENCH                                                        */
/* ======================================================================== */

const MW = {
  tab: "rdcf",
  sym: null,           // active ticker for per-ticker tabs
  timer: null,
  ctl: {},             // current slider values per tab
};

const MW_DEFS = {
  rdcf: { perTicker: true, sliders: [
    { id: "r",  label: "Discount rate", min: 5, max: 20, step: 0.5, def: 9, unit: "%" },
    { id: "gt", label: "Terminal growth", min: 0, max: 4.5, step: 0.25, def: 2.5, unit: "%" },
  ]},
  comps: { perTicker: true, sliders: [] },
  stmts: { perTicker: true, sliders: [] },
  lbo: { perTicker: true, sliders: [
    { id: "premium", label: "Entry premium", min: 0, max: 80, step: 5, def: 25, unit: "%" },
    { id: "debt",    label: "Debt financing", min: 20, max: 90, step: 5, def: 60, unit: "%" },
    { id: "rate",    label: "Cost of debt", min: 3, max: 15, step: 0.5, def: 9, unit: "%" },
    { id: "growth",  label: "EBITDA growth", min: -5, max: 20, step: 1, def: 4, unit: "%/yr" },
    { id: "years",   label: "Hold period", min: 3, max: 7, step: 1, def: 5, unit: "yr" },
  ]},
  mna: { perTicker: false, sliders: [
    { id: "premium", label: "Premium", min: 0, max: 80, step: 5, def: 25, unit: "%" },
    { id: "stock",   label: "Paid in stock", min: 0, max: 100, step: 10, def: 50, unit: "%" },
    { id: "rate",    label: "Debt rate", min: 2, max: 12, step: 0.5, def: 6, unit: "%" },
    { id: "syn",     label: "Synergies", min: 0, max: 5000, step: 100, def: 0, unit: "$M" },
  ]},
  mc: { perTicker: false, sliders: [
    { id: "horizon", label: "Horizon", min: 21, max: 756, step: 21, def: 252, unit: "days" },
  ]},
  stress: { perTicker: false, sliders: [] },
  lab: { perTicker: true, sliders: [] },
};

function mwSymbols() {
  const s = HOLDINGS.map(h => h.symbol);
  const base = s.length ? s : ["SPY"];
  // A ticker sent over from the supply-chain map isn't in the book, but it
  // still belongs in the dropdown — otherwise the next re-render throws it away.
  if (MW.sym && !base.includes(MW.sym)) return [...base, MW.sym];
  return base;
}

function mwRenderSel() {
  const el = $("modelsel");
  const def = MW_DEFS[MW.tab];
  if (!def.perTicker && MW.tab !== "mna") { el.innerHTML = ""; return; }
  if (!MW.sym || !mwSymbols().includes(MW.sym)) MW.sym = mwSymbols()[0];
  if (MW.tab === "mna") {
    el.innerHTML = `
      <label>acquirer</label>
      <select id="mw-acq">${mwSymbols().map(s => `<option ${s === MW.sym ? "selected" : ""}>${s}</option>`).join("")}</select>
      <label>target</label>
      <input id="mw-tgt" placeholder="TICKER" maxlength="6" value="${MW.ctl.mna_tgt || ""}">`;
    $("mw-acq").addEventListener("change", e => { MW.sym = e.target.value; mwFetch(); });
    $("mw-tgt").addEventListener("keydown", e => {
      if (e.key === "Enter") { MW.ctl.mna_tgt = e.target.value.trim().toUpperCase(); mwFetch(); }
    });
    return;
  }
  el.innerHTML = `
    <label>ticker</label>
    <select id="mw-sym">${mwSymbols().map(s => `<option ${s === MW.sym ? "selected" : ""}>${s}</option>`).join("")}</select>
    <input id="mw-free" placeholder="or any" maxlength="6">`;
  $("mw-sym").addEventListener("change", e => { MW.sym = e.target.value; mwFetch(); });
  $("mw-free").addEventListener("keydown", e => {
    if (e.key === "Enter" && e.target.value.trim()) { MW.sym = e.target.value.trim().toUpperCase(); mwFetch(); }
  });
}

function mwRenderCtl() {
  const el = $("modelctl");
  const def = MW_DEFS[MW.tab];
  if (!def.sliders.length) { el.innerHTML = ""; return; }
  const key = (id) => MW.tab + "_" + id;
  el.innerHTML = def.sliders.map(s => {
    const v = MW.ctl[key(s.id)] != null ? MW.ctl[key(s.id)] : s.def;
    MW.ctl[key(s.id)] = v;
    return `<div class="ctl">
      <label>${s.label} <b id="lab-${s.id}">${v}${s.unit}</b></label>
      <input type="range" min="${s.min}" max="${s.max}" step="${s.step}" value="${v}" data-ctl="${s.id}" data-unit="${s.unit}">
    </div>`;
  }).join("");
  el.querySelectorAll("input[type=range]").forEach(inp => {
    inp.addEventListener("input", () => {
      MW.ctl[key(inp.dataset.ctl)] = parseFloat(inp.value);
      $("lab-" + inp.dataset.ctl).textContent = inp.value + inp.dataset.unit;
      clearTimeout(MW.timer);
      MW.timer = setTimeout(mwFetch, 320);
    });
  });
}

function mwSwitch(tab) {
  MW.tab = tab;
  document.querySelectorAll("#modeltabs button").forEach(b =>
    b.classList.toggle("on", b.dataset.tab === tab));
  mwRenderSel();
  mwRenderCtl();
  mwFetch();
}

async function mwFetch() {
  const body = $("modelbody");
  body.innerHTML = '<div class="empty">Computing…</div>';
  const v = (id) => MW.ctl[MW.tab + "_" + id];
  try {
    let url = null;
    if (MW.tab === "rdcf") url = `/api/models/rdcf/${MW.sym}?r=${v("r")}&gt=${v("gt")}`;
    if (MW.tab === "comps") url = `/api/models/comps/${MW.sym}`;
    if (MW.tab === "stmts") url = `/api/models/statements/${MW.sym}`;
    if (MW.tab === "lbo") url = `/api/models/lbo/${MW.sym}?premium=${v("premium")}&debt=${v("debt")}&rate=${v("rate")}&growth=${v("growth")}&years=${v("years")}`;
    if (MW.tab === "mna") {
      const tgt = MW.ctl.mna_tgt;
      if (!tgt) { body.innerHTML = '<div class="empty">Enter a target ticker (top right) and press Enter.</div>'; return; }
      url = `/api/models/mna?acq=${MW.sym}&tgt=${tgt}&premium=${v("premium")}&stock=${v("stock")}&rate=${v("rate")}&syn=${v("syn")}`;
    }
    if (MW.tab === "mc") url = `/api/models/montecarlo?horizon=${v("horizon")}`;
    if (MW.tab === "stress") url = `/api/models/stress`;
    if (MW.tab === "lab") url = `/api/models/backtest/${MW.sym}`;
    const d = await (await fetch(url)).json();
    if (!d.ok) { body.innerHTML = `<div class="empty">${d.note || "Unavailable."}</div>`; return; }
    MW_RENDER[MW.tab](body, d);
  } catch (e) {
    body.innerHTML = '<div class="empty">Model fetch failed — is the server still running?</div>';
  }
}

/* ---------- renderers ---------------------------------------------------- */

const MW_RENDER = {

  rdcf(el, d) {
    const g = d.implied_growth_pct;
    el.innerHTML = `
      <div class="mhero">
        <div class="h-big ${g != null && d.hist_fcf_cagr_pct != null && g > d.hist_fcf_cagr_pct ? "down" : "up"}">${g == null ? ">60" : fmtNum(g, 1)}%<span class="dim" style="font-size:14px">/yr implied FCF growth</span></div>
        <div class="h-sub">what the current price requires for ${d.inputs.years} years, then ${d.inputs.terminal_pct}% forever</div>
      </div>
      <div class="kgrid">
        <div class="kcell"><div class="k">FCF (ttm)</div><div class="v">$${fmtNum(d.inputs.fcf_ttm, 2)}B</div></div>
        <div class="kcell"><div class="k">FCF yield</div><div class="v">${fmtNum(d.fcf_yield_pct, 2)}%</div></div>
        <div class="kcell"><div class="k">Actual FCF CAGR (reported yrs)</div><div class="v">${d.hist_fcf_cagr_pct == null ? "—" : fmtNum(d.hist_fcf_cagr_pct, 1) + "%"}</div></div>
        <div class="kcell"><div class="k">Net debt</div><div class="v">$${fmtNum(d.inputs.net_debt_b, 1)}B</div></div>
      </div>
      <table class="mtable"><tr><th class="l">implied growth grid</th>${d.grid_gts.map(g2 => `<th>gt ${g2}%</th>`).join("")}</tr>
        ${d.grid.map(row => `<tr class="${row.r === d.inputs.discount_pct ? "hl" : ""}"><td class="l">r ${row.r}%</td>${row.cells.map(c => `<td>${c.g == null ? ">60" : c.g + "%"}</td>`).join("")}</tr>`).join("")}
      </table>
      <div class="mread">${d.read}</div>`;
  },

  comps(el, d) {
    const cols = [["pe_t","P/E ttm"],["pe_f","P/E fwd"],["ev_ebitda","EV/EBITDA"],["ev_rev","EV/Rev"],["pb","P/B"],["fcf_yield","FCF yld %"],["op_margin_pct","Op margin %"],["rev_growth_pct","Rev gr %"]];
    const row = (r, hl) => `<tr class="${hl ? "hl" : ""}"><td class="l">${r.symbol}</td><td>${fmtNum(r.mcap_b,0)}</td>${cols.map(([k]) => `<td>${r[k] == null ? "—" : fmtNum(r[k], k==="ev_rev"||k==="pb"?2:1)}</td>`).join("")}</tr>`;
    el.innerHTML = `
      <table class="mtable">
        <tr><th class="l">sym</th><th>mcap $B</th>${cols.map(([,l]) => `<th>${l}</th>`).join("")}</tr>
        ${row(d.target, true)}
        ${d.peers.map(p => row(p, false)).join("")}
        <tr><td class="l dim">peer median</td><td></td>${cols.map(([k]) => `<td class="dim">${d.medians[k] == null ? "—" : d.medians[k]}</td>`).join("")}</tr>
      </table>
      <div class="kgrid">
        ${Object.entries(d.implied_price).map(([k, val]) => `
          <div class="kcell"><div class="k">implied @ median ${k}</div><div class="v">${fmtMoney(val)}</div>
          <div class="s ${d.vs_price_pct[k] >= 0 ? "up" : "down"}">${signPct(d.vs_price_pct[k])} vs price</div></div>`).join("")}
      </div>
      <div class="mread">${d.read}</div>`;
  },

  stmts(el, d) {
    const tbl = (title, rows) => `
      <table class="mtable"><tr><th class="l">${title} ($B)</th>${d.years.map(y => `<th>${y}</th>`).join("")}</tr>
      ${rows.map(r => `<tr><td class="l">${r.label}</td>${r.values.map(v => `<td class="${v != null && v < 0 ? "neg" : ""}">${v == null ? "—" : fmtNum(v, 2)}</td>`).join("")}</tr>`).join("")}</table>`;
    el.innerHTML = tbl("Income statement", d.income) + tbl("Balance sheet", d.balance) + tbl("Cash flow", d.cashflow)
      + (d.link ? `<div class="mread">${d.link}</div>` : "");
  },

  lbo(el, d) {
    el.innerHTML = `
      <div class="mhero">
        <div class="h-big ${d.irr_pct != null && d.irr_pct >= 20 ? "up" : "down"}">${d.irr_pct == null ? "—" : fmtNum(d.irr_pct, 1) + "%"}<span class="dim" style="font-size:14px"> IRR</span></div>
        <div class="h-big">${fmtNum(d.moic, 2)}×<span class="dim" style="font-size:14px"> MOIC</span></div>
        <div class="h-sub">sponsors typically underwrite to ~20%+ IRR</div>
      </div>
      <div class="kgrid">
        <div class="kcell"><div class="k">Entry EV</div><div class="v">$${fmtNum(d.entry.ev_b, 1)}B</div><div class="s">${fmtNum(d.entry.entry_multiple, 1)}× EBITDA</div></div>
        <div class="kcell"><div class="k">Debt / equity in</div><div class="v">$${fmtNum(d.entry.debt_b, 1)}B / $${fmtNum(d.entry.sponsor_equity_b, 1)}B</div></div>
        <div class="kcell"><div class="k">FCF conversion (actual)</div><div class="v">${Math.round(d.inputs.fcf_conversion * 100)}%</div><div class="s">of EBITDA becomes cash</div></div>
        <div class="kcell"><div class="k">Exit equity (yr ${d.inputs.years})</div><div class="v">$${fmtNum(d.exit.equity_b, 1)}B</div><div class="s">at ${fmtNum(d.inputs.exit_multiple, 1)}× exit</div></div>
      </div>
      <table class="mtable"><tr><th class="l">yr</th><th>EBITDA $B</th><th>interest $B</th><th>paydown $B</th><th>debt left $B</th></tr>
        ${d.years_table.map(y => `<tr><td class="l">${y.year}</td><td>${fmtNum(y.ebitda_b, 2)}</td><td>${fmtNum(y.interest_b, 2)}</td><td>${fmtNum(y.paydown_b, 2)}</td><td>${fmtNum(y.debt_b, 2)}</td></tr>`).join("")}
      </table>
      <div class="mread">${d.read}</div>`;
  },

  mna(el, d) {
    const acc = d.accretion_pct;
    el.innerHTML = `
      <div class="mhero">
        <div class="h-big ${acc >= 0 ? "up" : "down"}">${signPct(acc)}<span class="dim" style="font-size:14px"> EPS ${acc >= 0 ? "accretion" : "dilution"}</span></div>
        <div class="h-sub">combined EPS vs acquirer standalone, year one, bookkeeping basis</div>
      </div>
      <div class="kgrid">
        <div class="kcell"><div class="k">Deal value</div><div class="v">$${fmtNum(d.deal_value_b, 1)}B</div></div>
        <div class="kcell"><div class="k">EPS before → after</div><div class="v">${fmtNum(d.eps_before, 2)} → ${fmtNum(d.eps_after, 2)}</div></div>
        <div class="kcell"><div class="k">New shares issued</div><div class="v">${fmtNum(d.new_shares_m, 0)}M</div></div>
        <div class="kcell"><div class="k">Breakeven synergies</div><div class="v">$${fmtNum(d.breakeven_synergies_m, 0)}M</div><div class="s">pre-tax / yr</div></div>
      </div>
      <div class="mread">${d.read}</div>`;
  },

  mc(el, d) {
    el.innerHTML = `
      <div class="kgrid">
        <div class="kcell"><div class="k">Median outcome</div><div class="v">${fmtNum(d.terminal.median, 2)}×</div><div class="s">${fmtMoney(d.dollars.median)}</div></div>
        <div class="kcell"><div class="k">5th percentile</div><div class="v down">${fmtNum(d.terminal.p5, 2)}×</div><div class="s">${fmtMoney(d.dollars.p5)}</div></div>
        <div class="kcell"><div class="k">95th percentile</div><div class="v up">${fmtNum(d.terminal.p95, 2)}×</div><div class="s">${fmtMoney(d.dollars.p95)}</div></div>
        <div class="kcell"><div class="k">P(any loss)</div><div class="v">${fmtNum(d.terminal.prob_loss_pct, 1)}%</div></div>
        <div class="kcell"><div class="k">P(−20% or worse)</div><div class="v">${fmtNum(d.terminal.prob_down20_pct, 1)}%</div></div>
        <div class="kcell"><div class="k">Avg of worst 5%</div><div class="v down">${fmtNum(d.terminal.es5, 2)}×</div><div class="s">${fmtMoney(d.dollars.es5)}</div></div>
      </div>
      <canvas class="mchart" id="mc-cone"></canvas>
      <div class="legend"><span><i style="background:rgba(124,131,232,.8)"></i>median path</span><span><i style="background:rgba(124,131,232,.35)"></i>25–75%</span><span><i style="background:rgba(124,131,232,.16)"></i>5–95%</span></div>
      <div class="mread">${d.read}</div>`;
    mcCone($("mc-cone"), d);
  },

  stress(el, d) {
    el.innerHTML = `
      <table class="mtable">
        <tr><th class="l">window</th><th>dates</th><th>your book</th><th>$ impact</th><th>SPY</th><th class="l">notes</th></tr>
        ${d.windows.map(w => `<tr>
          <td class="l">${w.name}</td><td class="dim">${w.from} → ${w.to}</td>
          <td class="${w.portfolio_pct >= 0 ? "pos" : "neg"}">${signPct(w.portfolio_pct)}</td>
          <td class="${w.dollar_impact >= 0 ? "pos" : "neg"}">${w.dollar_impact >= 0 ? "+" : "−"}${fmtMoney(Math.abs(w.dollar_impact))}</td>
          <td class="${(w.spy_pct || 0) >= 0 ? "pos" : "neg"}">${w.spy_pct == null ? "—" : signPct(w.spy_pct)}</td>
          <td class="l dim" style="font-family:var(--sans);white-space:normal">${Object.entries(w.per_holding).map(([s, v]) => `${s} ${v >= 0 ? "+" : ""}${v}%`).join(" · ")}${w.note ? " — " + w.note : ""}</td>
        </tr>`).join("")}
      </table>
      <div class="mread">${d.read}</div>`;
  },

  lab(el, d) {
    el.innerHTML = `
      <table class="mtable">
        <tr><th class="l">strategy</th><th>total</th><th>CAGR</th><th>vol</th><th>Sharpe</th><th>max DD</th><th>in market</th><th>trades</th></tr>
        ${d.rows.map(r => `<tr class="${r.key === "buy_hold" ? "hl" : ""}">
          <td class="l">${r.label}</td>
          <td class="${r.total_pct >= 0 ? "pos" : "neg"}">${signPct(r.total_pct)}</td>
          <td>${fmtNum(r.cagr_pct, 1)}%</td><td>${fmtNum(r.vol_pct, 0)}%</td>
          <td>${r.sharpe == null ? "—" : fmtNum(r.sharpe, 2)}</td>
          <td class="neg">${fmtNum(r.max_dd_pct, 0)}%</td>
          <td>${fmtNum(r.exposure_pct, 0)}%</td><td>${r.trades}</td>
        </tr>`).join("")}
      </table>
      <canvas class="mchart" id="lab-curves"></canvas>
      <div class="legend" id="lab-legend"></div>
      <div class="mread">${d.window} · signals act next day · ${d.cost_bps} bps per flip. ${d.read}</div>`;
    labCurves($("lab-curves"), $("lab-legend"), d);
  },
};

/* ---------- workbench charts --------------------------------------------- */

function mcCone(canvas, d) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight || 210;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const b = d.bands;
  const all = [...b["5"], ...b["95"]];
  let lo = Math.min(...all), hi = Math.max(...all);
  const padT = 10, padB = 16, padL = 4, padR = 46;
  const X = (i) => padL + (i / (d.xs.length - 1)) * (W - padL - padR);
  const Y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);

  const band = (loArr, hiArr, fill) => {
    ctx.beginPath();
    loArr.forEach((v, i) => i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v)));
    for (let i = hiArr.length - 1; i >= 0; i--) ctx.lineTo(X(i), Y(hiArr[i]));
    ctx.closePath(); ctx.fillStyle = fill; ctx.fill();
  };
  band(b["5"], b["95"], accentRGBA(.16));
  band(b["25"], b["75"], accentRGBA(.30));

  ctx.strokeStyle = accentRGBA(.95); ctx.lineWidth = 1.6; ctx.beginPath();
  b["50"].forEach((v, i) => i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v)));
  ctx.stroke();

  // 1.0× reference line
  ctx.strokeStyle = "rgba(154,164,182,.35)"; ctx.setLineDash([4, 4]); ctx.beginPath();
  ctx.moveTo(padL, Y(1)); ctx.lineTo(W - padR, Y(1)); ctx.stroke(); ctx.setLineDash([]);

  ctx.font = "10px 'IBM Plex Mono', monospace"; ctx.fillStyle = "rgba(154,164,182,.9)";
  [["95", b["95"]], ["50", b["50"]], ["5", b["5"]]].forEach(([lab, arr]) => {
    ctx.fillText(arr[arr.length - 1].toFixed(2) + "×", W - padR + 5, Y(arr[arr.length - 1]) + 3);
  });
}

function labCurves(canvas, legendEl, d) {
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight || 210;
  canvas.width = W * dpr; canvas.height = H * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const colors = { buy_hold: (css("--text-2") || "#9AA4B6"), sma_cross: (css("--accent") || "#7C83E8"), tsmom: (css("--warn") || "#D9A441"), rsi2: (css("--up") || "#43B37D") };
  const keys = Object.keys(d.curves);
  const all = keys.flatMap(k => d.curves[k]);
  let lo = Math.min(...all), hi = Math.max(...all);
  const padT = 8, padB = 14, padL = 4, padR = 44;
  const n = Math.max(...keys.map(k => d.curves[k].length));
  const X = (i) => padL + (i / (n - 1)) * (W - padL - padR);
  const Y = (v) => padT + (1 - (v - lo) / (hi - lo)) * (H - padT - padB);

  ctx.strokeStyle = "rgba(154,164,182,.3)"; ctx.setLineDash([4, 4]); ctx.beginPath();
  ctx.moveTo(padL, Y(1)); ctx.lineTo(W - padR, Y(1)); ctx.stroke(); ctx.setLineDash([]);

  keys.forEach(k => {
    const c = d.curves[k];
    ctx.strokeStyle = colors[k] || "#fff";
    ctx.lineWidth = k === "buy_hold" ? 2 : 1.3;
    ctx.beginPath();
    c.forEach((v, i) => i ? ctx.lineTo(X(i), Y(v)) : ctx.moveTo(X(i), Y(v)));
    ctx.stroke();
    ctx.font = "10px 'IBM Plex Mono', monospace"; ctx.fillStyle = colors[k];
    ctx.fillText(c[c.length - 1].toFixed(2) + "×", W - padR + 5, Y(c[c.length - 1]) + 3);
  });
  const labels = { buy_hold: "buy & hold", sma_cross: "SMA 50/200", tsmom: "12-1 momentum", rsi2: "RSI(2) mean-rev" };
  legendEl.innerHTML = keys.map(k => `<span><i style="background:${colors[k]}"></i>${labels[k]}</span>`).join("");
}

/* ---------- workbench boot ------------------------------------------------ */

document.querySelectorAll("#modeltabs button").forEach(b =>
  b.addEventListener("click", () => mwSwitch(b.dataset.tab)));

setTimeout(() => mwSwitch("rdcf"), 400);   // after holdings load


/* ======================================================================== */
/*  THEME SWITCHER                                                          */
/* ======================================================================== */

(function themes() {
  const sel = $("themesel");
  if (!sel) return;
  const mq = matchMedia("(prefers-color-scheme: light)");
  const resolve = (pref) => pref === "auto" ? (mq.matches ? "paper" : "graphite") : pref;
  const repaint = () => {
    drawSparklines();
    drawCharts();
    if (typeof mwFetch === "function") mwFetch();
  };
  // built from THEMES so adding a theme is a one-line change
  sel.innerHTML = THEMES.map(([v, label]) => `<option value="${v}">${label}</option>`).join("");
  const VALID = THEMES.map(t => t[0]);
  let pref = "auto";
  try {
    const saved = localStorage.getItem("windrose-theme") || localStorage.getItem("ledger-theme");
    if (VALID.includes(saved)) pref = saved;
  } catch (e) {}
  document.documentElement.dataset.theme = resolve(pref);
  sel.value = pref;
  sel.addEventListener("change", () => {
    pref = sel.value;
    try { localStorage.setItem("windrose-theme", pref); } catch (e) {}
    document.documentElement.dataset.theme = resolve(pref);
    repaint();
  });
  // macOS flips appearance at sunset — follow it live when on auto
  mq.addEventListener("change", () => {
    if (pref === "auto") {
      document.documentElement.dataset.theme = resolve(pref);
      repaint();
    }
  });
})();

/* ======================================================================== */
/*  PANEL LAYOUT — zones + pointer drag (Safari-proof), gated by ⠿ layout   */
/* ======================================================================== */

function initLayout() {
  const root = $("layout");
  root.classList.add("layoutgrid");
  const plan = loadPlan();
  const zones = { cols: [], full: null };

  // A panel the saved plan has never heard of — one added by an upgrade —
  // joins its declared home rather than disappearing.
  const adopt = () => {
    const named = new Set([...plan.cols.flat(), ...plan.full]);
    root.querySelectorAll(".panel[data-panel]").forEach(p => {
      const id = p.dataset.panel;
      if (named.has(id)) return;
      named.add(id);
      const home = p.dataset.defcol || "full";
      if (home === "full") plan.full.push(id);
      else if (!plan.cols.length) plan.cols.push([id]);
      else if (home === "right" && plan.cols.length > 1) plan.cols[1].push(id);
      else plan.cols[0].push(id);
    });
  };

  const render = (n) => {
    adopt();
    const cols = fitPlan(plan.cols, n);
    const frag = document.createDocumentFragment();
    const made = [];
    const take = (id) => root.querySelector(`.panel[data-panel="${id}"]`);

    cols.forEach((ids, i) => {
      const d = document.createElement("div");
      d.className = "zone";
      d.dataset.zone = "c" + i;
      ids.forEach(id => { const p = take(id); if (p) d.appendChild(p); });
      frag.appendChild(d);
      made.push(d);
    });
    const f = document.createElement("div");
    f.className = "zone";
    f.dataset.zone = "full";
    plan.full.forEach(id => { const p = take(id); if (p) f.appendChild(p); });
    frag.appendChild(f);

    // the old wrappers are empty by now — every panel has been moved out
    root.querySelectorAll(":scope > .zone").forEach(z => z.remove());
    root.appendChild(frag);
    root.dataset.cols = n;
    zones.cols = made;
    zones.full = f;
    LAYOUT_COLS = n;
  };

  render(colCount());

  // Resizing never edits the plan: it re-derives the screen from it. Crossing
  // a breakpoint back and forth leaves what was saved exactly as it was.
  let rt;
  window.addEventListener("resize", () => {
    clearTimeout(rt);
    rt = setTimeout(() => {
      const n = colCount();
      if (n === LAYOUT_COLS) return;
      render(n);
      repaintPanels();
    }, 160);
  });

  /* A drag is what you see is what you get: the columns on screen become the
     saved columns. Rearranging at two columns therefore flattens a four-column
     plan — which is the honest reading of "put this panel here", and the only
     rule that never moves a panel somewhere the user did not watch it go. */
  const save = () => {
    plan.cols = zones.cols.map(z =>
      [...z.querySelectorAll(":scope > .panel")].map(p => p.dataset.panel));
    plan.full = [...zones.full.querySelectorAll(":scope > .panel")].map(p => p.dataset.panel);
    try { localStorage.setItem(LAYOUT_KEY, JSON.stringify(plan)); } catch (e) {}
  };
  window._layoutSave = save;

  // --- edit mode toggle ---
  const btn = $("layoutbtn"), rst = $("layoutreset");
  btn.addEventListener("click", () => {
    const on = document.body.classList.toggle("layout-edit");
    btn.classList.toggle("on", on);
    rst.style.display = on ? "" : "none";
  });
  rst.addEventListener("click", () => {
    // clear the old keys too, or the migration below would resurrect them
    for (const k of [LAYOUT_KEY, "ledger-layout2", "windrose-layout2"]) {
      try { localStorage.removeItem(k); } catch (e) {}
    }
    location.reload();
  });

  // --- pointer-based drag (no HTML5 DnD — works in Safari) ---
  let lift = null, ghost = null, slot = null;
  root.addEventListener("pointerdown", (e) => {
    const h = e.target.closest(".drag");
    if (!h || !document.body.classList.contains("layout-edit")) return;
    e.preventDefault();
    lift = h.closest(".panel");
    lift.classList.add("lifting");
    ghost = document.createElement("div");
    ghost.id = "dragghost";
    ghost.textContent = "⠿ " + lift.dataset.panel;
    document.body.appendChild(ghost);
    slot = document.createElement("div");
    slot.className = "dropslot";
    moveGhost(e);
    document.addEventListener("pointermove", moveGhost);
    document.addEventListener("pointerup", drop, { once: true });
  });

  function targetZone(e) {
    const fr = zones.full.getBoundingClientRect();
    if (fr.height > 20 && e.clientY > fr.top - 10) return zones.full;
    const r = root.getBoundingClientRect();
    const n = zones.cols.length;
    const i = Math.floor((e.clientX - r.left) / (r.width / n));
    return zones.cols[Math.min(n - 1, Math.max(0, i))];
  }

  function moveGhost(e) {
    if (!lift) return;
    ghost.style.left = (e.clientX + 14) + "px";
    ghost.style.top = (e.clientY + 10) + "px";
    const zone = targetZone(e);
    const kids = [...zone.querySelectorAll(".panel")].filter(p => p !== lift);
    let before = null;
    for (const k of kids) {
      const r = k.getBoundingClientRect();
      if (e.clientY < r.top + r.height / 2) { before = k; break; }
    }
    if (before) zone.insertBefore(slot, before); else zone.appendChild(slot);
  }

  function drop() {
    document.removeEventListener("pointermove", moveGhost);
    if (slot && slot.parentNode) slot.parentNode.insertBefore(lift, slot);
    if (slot) slot.remove();
    if (ghost) ghost.remove();
    if (lift) lift.classList.remove("lifting");
    lift = ghost = slot = null;
    save();
    repaintPanels();
  }
}

/* ======================================================================== */
/*  EARNINGS STRIP                                                          */
/* ======================================================================== */

async function loadEarnings() {
  try {
    const rows = await (await fetch("/api/earnings")).json();
    const el = $("earnstrip");
    if (!rows.length) { el.innerHTML = ""; return; }
    el.innerHTML = '<span class="et">EARNINGS</span>' + rows.map(r => {
      const cl = r.days <= 0 ? "today" : r.days <= 7 ? "soon" : "";
      const label = r.days <= 0 ? "today" : r.days + "d";
      return `<span class="${cl}"><b>${r.symbol}</b> ${label} <span class="dim">· ${r.date}</span></span>`;
    }).join("");
  } catch (e) {}
}

/* ======================================================================== */
/*  DIVIDENDS + INCOME                                                      */
/* ======================================================================== */

let DIVS = null;

async function loadDividends() {
  try {
    DIVS = await (await fetch("/api/dividends")).json();
    fillDividendLines();
    renderFactors();       // income line lives with factors
  } catch (e) {}
}

function fillDividendLines() {
  if (!DIVS) return;
  for (const d of DIVS.rows || []) {
    const el = $("divs-" + d.symbol);
    if (!el) continue;
    if (!d.ok) { el.textContent = ""; continue; }
    if (!d.pays) { el.innerHTML = '<span class="dim">pays no dividend</span>'; continue; }
    let s = `div <b>${fmtNum(d.yield_pct, 2)}%</b>`;
    if (d.rate_annual) s += ` · $${fmtNum(d.rate_annual, 2)}/sh yr`;
    if (d.ex_next) s += ` · ex ${d.ex_next}`;
    if (d.total_return) {
      const t = d.total_return;
      s += ` · <b>incl divs:</b> <span class="${cls(t.total_pl)}">${t.total_pl >= 0 ? "+" : ""}${fmtMoney(t.total_pl)} (${signPct(t.total_pl_pct)})</span>` +
           ` <span class="dim">($${fmtNum(t.dividends_received, 2)} received since ${t.acquired})</span>`;
    }
    el.innerHTML = s;
  }
}

/* ======================================================================== */
/*  FACTORS (defense beta etc) — renders under the risk panel               */
/* ======================================================================== */

let FACTORS = null;

async function loadFactors() {
  try {
    FACTORS = await (await fetch("/api/factors")).json();
    renderFactors();
  } catch (e) {}
}

function renderFactors() {
  const el = $("factors");
  if (!el) return;
  if (!FACTORS || !FACTORS.ok) { el.innerHTML = ""; return; }
  const b = FACTORS.benches || {};
  // correlation runs -1..1, so the bar is diverging from a centre line rather
  // than filling from the left — a corr of -0.4 and one of +0.4 are different
  // facts and a left-filled bar would draw them the same width apart.
  const corrBar = (c) => {
    if (c == null) return "";
    const w = Math.min(50, Math.abs(c) * 50);
    return `<div class="dbar fbar"><i class="mid"></i>
      <i class="${c >= 0 ? "acc" : "neg"}" style="left:${c >= 0 ? 50 : 50 - w}%;width:${w}%"></i></div>`;
  };
  const row = (name, label) => b[name]
    ? `<div class="frow"><span class="fk">${label}</span><span class="fv">β ${fmtNum(b[name].beta, 2)} · corr ${fmtNum(b[name].corr, 2)}</span></div>
       ${corrBar(b[name].corr)}` : "";
  const ita = b.ITA ? b.ITA.corr : null;
  const secs = FACTORS.sectors || [];
  // one stacked bar instead of a row of percentages to add up by eye. Shades of
  // the accent rather than a colour per sector: the chips below carry the
  // names, and inventing eight hues would collide with green/red meaning gains.
  const secbar = secs.length
    ? `<div class="secbar">${secs.map((x, i) =>
        `<span title="${esc(x.sector)} ${fmtNum(x.weight_pct, 0)}%" style="width:${x.weight_pct}%;background:${accentRGBA(0.85 - Math.min(0.55, i * 0.11))};box-shadow:inset -1px 0 0 var(--panel)"></span>`).join("")}</div>`
    : "";
  const sectors = secs.map(s =>
    `<span class="chip">${s.sector} <b>${fmtNum(s.weight_pct, 0)}%</b></span>`).join("");
  const income = DIVS && DIVS.income && DIVS.income.annual_income
    ? `<div class="frow"><span class="fk">Dividend income / yr (current rates)</span><span class="fv up">$${fmtNum(DIVS.income.annual_income, 2)}</span></div>` : "";
  el.innerHTML = `<div class="factors">
    <div class="sect">Factor exposure — what your book actually tracks</div>
    ${row("SPY", "vs S&P 500 (SPY)")}
    ${row("ITA", "vs Defense (ITA)")}
    ${row("XLI", "vs Industrials (XLI)")}
    ${income}
    ${secbar}
    <div class="sectorchips">${sectors}</div>
    ${ita != null && ita >= 0.5 ? `<div class="riskread" style="margin-top:12px">Your book moves with the defense ETF (corr ${fmtNum(ita, 2)}) far more than with the market — however many tickers it holds, it is substantially one macro trade.</div>` : ""}
  </div>`;
}

/* ======================================================================== */
/*  BENCHMARK — the do-nothing test                                         */
/* ======================================================================== */

async function loadBenchmark() {
  const el = $("benchmark");
  try {
    const d = await (await fetch("/api/benchmark")).json();
    if (!d.ok) { el.innerHTML = `<div class="empty">${d.note}</div>`; return; }
    BENCH = d;
    const t = d.totals;
    const scale = Math.max(t.book, t.shadow, t.spent) * 1.05;
    const sr = d.series || {};
    el.innerHTML = `
      <div class="bm-hero">
        <span class="bm-big ${cls(t.book_pct)}">${signPct(t.book_pct)} <span class="bm-vs">your book</span></span>
        <span class="bm-big ${cls(t.shadow_pct)}">${signPct(t.shadow_pct)} <span class="bm-vs">SPY, same dollars</span></span>
        <span class="bm-big ${cls(t.alpha)}">${t.alpha >= 0 ? "+" : "−"}${fmtMoney(Math.abs(t.alpha))} <span class="bm-vs">the difference</span></span>
      </div>
      ${sr.book ? `<div class="chartlab"><span><b style="color:var(--accent)">━</b> your book</span>
          <span><b style="color:var(--warn)">━</b> the same dollars in SPY</span>
          <span>from ${esc(sr.dates[0])}</span></div>
        <canvas class="pchart" data-pchart="bench"></canvas>` : ""}
      <div class="bm-bars">
        <div class="brow" style="display:grid;grid-template-columns:110px 1fr 84px;gap:10px;align-items:center;font-family:var(--mono);font-size:11px;color:var(--text-2)">
          <span>your book</span><div class="btrack" style="height:10px;background:var(--panel-2);border-radius:3px;overflow:hidden"><div style="height:100%;width:${t.book/scale*100}%;background:var(--accent);opacity:.8"></div></div><span>${fmtMoney(t.book)}</span></div>
        <div class="brow" style="display:grid;grid-template-columns:110px 1fr 84px;gap:10px;align-items:center;font-family:var(--mono);font-size:11px;color:var(--text-2)">
          <span>SPY shadow</span><div class="btrack" style="height:10px;background:var(--panel-2);border-radius:3px;overflow:hidden"><div style="height:100%;width:${t.shadow/scale*100}%;background:var(--warn);opacity:.85"></div></div><span>${fmtMoney(t.shadow)}</span></div>
      </div>
      <table class="sbtable" style="margin-top:10px">
        <tr><th class="l">sym</th><th>spent</th><th>now</th><th>SPY shadow</th><th>±</th><th class="l"></th></tr>
        ${d.rows.map(r => `<tr><td class="l">${r.symbol}</td><td>${fmtMoney(r.spent)}</td><td>${fmtMoney(r.now)}</td><td>${fmtMoney(r.shadow)}</td>
          <td class="${cls(r.alpha)}">${r.alpha >= 0 ? "+" : "−"}${fmtMoney(Math.abs(r.alpha))}</td>
          <td class="l dim" style="font-family:var(--sans)">${r.dated ? "" : "≈ no date set"}</td></tr>`).join("")}
      </table>
      <div class="riskread" style="margin-top:12px">${d.read}</div>`;
    drawPanelCharts();
  } catch (e) {
    el.innerHTML = '<div class="empty">Benchmark unavailable.</div>';
  }
}

/* ======================================================================== */
/*  WHAT-IF SANDBOX                                                         */
/* ======================================================================== */

let SB_TIMER = null;

async function loadSandbox() {
  const el = $("sandbox");
  const sized = HOLDINGS.filter(h => h.shares >= 0);
  if (!HOLDINGS.length) { el.innerHTML = '<div class="empty">Add positions first.</div>'; return; }
  el.innerHTML = `
    <div class="sb-rows">
      ${HOLDINGS.map(h => `<div class="sb-row">
        <span class="sym">${h.symbol}</span>
        <input type="text" inputmode="decimal" data-sb="${h.symbol}" value="${h.shares}">
        <span class="cur">currently ${h.shares}</span>
      </div>`).join("")}
    </div>
    <div class="sb-add">
      <input id="sb-newsym" placeholder="+ TICKER" maxlength="6">
      <input id="sb-newsh" placeholder="shares" inputmode="decimal">
    </div>
    <div id="sb-out" class="empty">Change a number to see the risk math move.</div>
    <div class="sb-actions"><button id="sb-reset">Reset to current</button></div>`;
  el.querySelectorAll("[data-sb], #sb-newsym, #sb-newsh").forEach(inp =>
    inp.addEventListener("input", () => { clearTimeout(SB_TIMER); SB_TIMER = setTimeout(runWhatif, 450); }));
  $("sb-reset").addEventListener("click", loadSandbox);
}

async function runWhatif() {
  const parts = [];
  document.querySelectorAll("[data-sb]").forEach(inp => {
    const v = parseFloat(inp.value);
    if (!isNaN(v)) parts.push(inp.dataset.sb + ":" + v);
  });
  const ns = $("sb-newsym") ? $("sb-newsym").value.trim().toUpperCase() : "";
  const nv = $("sb-newsh") ? parseFloat($("sb-newsh").value) : NaN;
  if (ns && !isNaN(nv)) parts.push(ns + ":" + nv);
  if (!parts.length) return;
  const out = $("sb-out");
  out.innerHTML = '<div class="empty">Computing…</div>';
  try {
    const d = await (await fetch("/api/whatif?shares=" + encodeURIComponent(parts.join(",")))).json();
    const c = d.current, h = d.hypothetical;
    if (!h.ok) { out.innerHTML = `<div class="empty">${h.reason || "not computable"}</div>`; return; }
    const g = (obj, path) => path.split(".").reduce((o, k) => (o || {})[k], obj);
    const rows = [
      ["Effective holdings", "concentration.effective_holdings", 2, false],
      ["Largest position %", "concentration.max_weight_pct", 0, true],
      ["Vol (EWMA) %/yr", "ewma_vol_pct", 1, true],
      ["1-day VaR95 $", "var.hist_95_dollar", 2, true],
      ["CVaR95 $", "var.cvar_95_dollar", 2, true],
      ["Beta vs S&P", "beta", 2, null],
    ];
    const topRisk = (p) => {
      const rc = p.risk_contribution || {};
      const t = Object.entries(rc).sort((a, b) => b[1] - a[1])[0];
      return t ? `${t[0]} ${fmtNum(t[1], 0)}%` : "—";
    };
    // Each metric is in its own unit, so the bar shows the move as a share of
    // where the number started rather than against the other rows. Clamped at
    // half the width: past ±50% the exact length stops meaning anything and
    // the figure beside it is the thing to read.
    const dbar = (a, delta, good) => {
      if (a == null || delta == null || Math.abs(a) < 1e-9 || Math.abs(delta) < 1e-9) return "";
      const w = Math.min(50, Math.abs(delta / a) * 100);
      const kind = good === null ? "acc" : (good ? "pos" : "neg");
      return `<div class="dbar"><i class="mid"></i>
        <i class="${kind}" style="left:${delta >= 0 ? 50 : 50 - w}%;width:${w}%"></i></div>`;
    };
    out.innerHTML = `<table class="sbtable">
      <tr><th class="l">metric</th><th>now</th><th>hypothetical</th><th>Δ</th><th></th></tr>
      ${rows.map(([label, path, dp, lowerBetter]) => {
        const a = c.ok ? g(c, path) : null, b2 = g(h, path);
        const delta = (a != null && b2 != null) ? b2 - a : null;
        let dCls = "", good = null;
        if (delta != null && lowerBetter !== null) {
          good = lowerBetter ? delta < 0 : delta > 0;
          dCls = Math.abs(delta) < 1e-9 ? "" : (good ? "pos" : "neg");
        }
        return `<tr><td class="l" style="font-family:var(--sans)">${label}</td>
          <td>${fmtNum(a, dp)}</td><td>${fmtNum(b2, dp)}</td>
          <td class="${dCls}">${delta == null ? "—" : (delta >= 0 ? "+" : "") + fmtNum(delta, dp)}</td>
          <td style="width:74px">${dbar(a, delta, good)}</td></tr>`;
      }).join("")}
      <tr><td class="l" style="font-family:var(--sans)">Top risk driver</td>
        <td>${c.ok ? topRisk(c) : "—"}</td><td>${topRisk(h)}</td><td></td><td></td></tr>
    </table>
    <div class="hint" style="margin-top:8px">Hypothetical only — your real holdings are untouched. When a change you like shows up here, you make it at your broker, on purpose.</div>`;
  } catch (e) {
    out.innerHTML = '<div class="empty">What-if failed — server running?</div>';
  }
}

/* ======================================================================== */
/*  ALERTS                                                                  */
/* ======================================================================== */

const METRIC_LABELS = {
  price_above: "price crosses above", price_below: "price falls below",
  day_move_abs: "day move exceeds ±%", rsi_above: "RSI rises to", rsi_below: "RSI falls to",
  cross_above_sma20: "crosses above SMA20", cross_below_sma20: "crosses below SMA20",
  cross_above_sma50: "crosses above SMA50", cross_below_sma50: "crosses below SMA50",
  port_drawdown: "portfolio drawdown from 1y peak exceeds %",
};

function notifBtnLabel() {
  if (!("Notification" in window)) return "Notifications unsupported";
  if (Notification.permission === "granted") return "\u2713 Desktop notifications on";
  if (Notification.permission === "denied") return "Notifications blocked";
  return "Enable desktop notifications";
}

/* Open a GitHub issue with the boring facts already filled in.
   What goes in the body is exactly what /api/diagnostics returns and nothing
   else — no tickers, no share counts, no journal text, no keys. The user sees
   the whole thing on GitHub before they press submit, which is the point: they
   can read what they are about to send. */
async function reportProblem() {
  let diag = {};
  try {
    diag = await (await fetch("/api/diagnostics")).json();
  } catch (e) {
    diag = { version: "unknown", note: "diagnostics unavailable — server not reachable" };
  }
  const repo = diag.repo || "Shaw54-eagle/windrose";
  const facts = Object.entries(diag)
    .filter(([k]) => k !== "repo")
    .map(([k, v]) => `| ${k} | ${v} |`).join("\n");
  const body =
    "**What happened?**\n\n\n**What did you expect instead?**\n\n\n" +
    "**Steps to reproduce**\n1. \n2. \n\n---\n\n" +
    "<sub>Filled in automatically. No holdings, keys or notes are included.</sub>\n\n" +
    "| | |\n|---|---|\n" + facts + "\n";
  const url = `https://github.com/${repo}/issues/new` +
    `?title=${encodeURIComponent("[" + (diag.version || "?") + "] ")}` +
    `&body=${encodeURIComponent(body)}`;
  window.open(url, "_blank", "noopener");
}

function notifUnblockHint() {
  const ua = navigator.userAgent;
  const where = /Firefox/.test(ua)
    ? "click the padlock in the address bar, then Clear permission"
    : /Edg\//.test(ua)
      ? "click the padlock in the address bar, then Permissions for this site, and allow Notifications"
      : (/Safari/.test(ua) && !/Chrome/.test(ua))
        ? "Safari menu, then Settings, Websites, Notifications, and allow 127.0.0.1"
        : "click the padlock (or info icon) in the address bar, then Site settings, and allow Notifications";
  return "This browser is blocking notifications for this page. To fix it, " + where +
         ", then reload. Windrose can also notify you through your operating system " +
         "even when no tab is open.";
}

async function loadAlerts() {
  const el = $("alertsbody");
  try {
    const d = await (await fetch("/api/alerts")).json();
    const syms = HOLDINGS.map(h => h.symbol);
    const needsVal = (m) => !m.startsWith("cross_");
    el.innerHTML = `
      <div class="al-form">
        <select id="al-sym">${syms.map(s => `<option>${s}</option>`).join("")}<option value="PORT">PORTFOLIO</option></select>
        <select id="al-metric">${d.metrics.map(m => `<option value="${m}">${METRIC_LABELS[m] || m}</option>`).join("")}</select>
        <input class="val" id="al-val" placeholder="value" inputmode="decimal">
        <input class="note" id="al-note" placeholder="note to self (optional)">
        <button id="al-add">Add alert</button>
        <button id="al-notif" class="notifbtn">${notifBtnLabel()}</button>
      </div>
      <div class="alertcaveat">Alerts only fire while Windrose is running. Close it
        or sleep the computer and nothing is watching — use <b>Run at Login</b>
        in the Windrose folder to keep it up.</div>
      <div class="nothint" id="al-nothint" style="display:none"></div>
      <div id="al-rules">${d.rules.length ? d.rules.map(alertRuleHtml).join("") : '<div class="empty">No alerts yet. Watching without staring starts here.</div>'}</div>
      <div class="al-fired" id="al-fired">${(d.recent || []).slice(-6).reverse().map(e =>
        `<div class="al-evt"><span class="when">${e.when}</span>${e.text}</div>`).join("")}</div>`;
    $("al-metric").addEventListener("change", () => {
      $("al-val").style.display = needsVal($("al-metric").value) ? "" : "none";
    });
    $("al-add").addEventListener("click", addAlert);
    $("al-notif").addEventListener("click", async () => {
      if (!("Notification" in window)) {
        $("al-notif").textContent = "Not supported in this browser";
        return;
      }
      // A denied browser never prompts again, so asking is pointless —
      // point at the real switch instead.
      if (Notification.permission === "denied") {
        $("al-notif").textContent = "Blocked — see below";
        const h = $("al-nothint");
        if (h) { h.textContent = notifUnblockHint(); h.style.display = ""; }
        return;
      }
      const p = await Notification.requestPermission();
      $("al-notif").textContent = notifBtnLabel();
      const h = $("al-nothint");
      if (p === "denied" && h) { h.textContent = notifUnblockHint(); h.style.display = ""; }
      if (p === "granted") {
        try { new Notification("Windrose", { body: "Notifications are on — alerts will appear here." }); } catch (e) {}
      }
    });
    el.querySelectorAll("[data-aldel]").forEach(b =>
      b.addEventListener("click", async () => { await fetch("/api/alerts/" + b.dataset.aldel, { method: "DELETE" }); loadAlerts(); }));
    el.querySelectorAll("[data-altog]").forEach(b =>
      b.addEventListener("click", async () => { await fetch("/api/alerts/" + b.dataset.altog + "/toggle", { method: "POST" }); loadAlerts(); }));
    $("alertmeta").textContent = d.rules.length ? `${d.rules.filter(r => r.enabled).length} armed` : "";
  } catch (e) {
    el.innerHTML = '<div class="empty">Alerts unavailable.</div>';
  }
}

function alertRuleHtml(r) {
  const needsVal = !r.metric.startsWith("cross_");
  return `<div class="al-rule ${r.enabled ? "" : "off"}">
    <span class="r-txt"><span class="mono">${esc(r.symbol)}</span> ${METRIC_LABELS[r.metric] || esc(r.metric)}${needsVal ? ` <span class="mono">${r.value}</span>` : ""}${r.note ? ` <span class="dim">— ${esc(r.note)}</span>` : ""}${r.last_fired ? ` <span class="dim">(last: ${r.last_fired})</span>` : ""}</span>
    <button class="al-toggle" data-altog="${r.id}">${r.enabled ? "on" : "off"}</button>
    <button class="del" data-aldel="${r.id}">✕</button>
  </div>`;
}

async function addAlert() {
  const metric = $("al-metric").value;
  const body = {
    symbol: $("al-sym").value, metric,
    value: metric.startsWith("cross_") ? 0 : parseFloat($("al-val").value),
    note: $("al-note").value,
  };
  if (!metric.startsWith("cross_") && isNaN(body.value)) { $("al-val").focus(); return; }
  await fetch("/api/alerts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  $("al-val").value = ""; $("al-note").value = "";
  loadAlerts();
}

function onAlertEvents(events) {
  for (const e of events) {
    if ("Notification" in window && Notification.permission === "granted") {
      try { new Notification("Windrose — " + e.symbol, { body: e.text }); } catch (err) {}
    }
    const box = $("al-fired");
    if (box) box.insertAdjacentHTML("afterbegin",
      `<div class="al-evt"><span class="when">${e.when}</span>${e.text}</div>`);
  }
  if (events.length) loadAlerts();
}

/* ======================================================================== */
/*  DECISION JOURNAL                                                        */
/* ======================================================================== */

window.JOURNAL_BY_SYM = {};

/* ======================================================================== */
/*  CHOKEPOINTS — the dependencies underneath the portfolio                  */
/* ======================================================================== */

async function loadChokepoints() {
  const body = $("chokebody");
  if (!body) return;
  try {
    const d = await (await fetch("/api/chokepoints")).json();
    if (!d.ok) {
      body.innerHTML = `<div class="empty">None of your holdings appear in the
        supply-chain map yet, so there is nothing to trace.</div>`;
      return;
    }
    const meta = $("cpmeta");
    if (meta) meta.textContent = `${d.mapped.length} of ${d.mapped.length + d.unmapped.length} holdings mapped · within ${d.hops} hops, discounted by distance`;

    const row = (x, dir) => {
      const who = x.reaches.map(r => `${esc(r.symbol)}<span class="hp">${r.hops}</span>`).join(" ");
      // score_pct is the weighted number — value share discounted for distance
      // and for what the map records about each link. weight_pct is the raw
      // reach it is discounted from, kept so the two can be told apart.
      const pct = x.score_pct != null ? x.score_pct : x.weight_pct;
      const bar = Math.max(2, Math.min(100, pct));
      return `<tr>
        <td class="l"><span class="mono">${esc(x.ticker || x.id)}</span>${x.held ? ' <span class="ownedtag">owned</span>' : ""}
          <div class="cplabel">${esc(x.label)}</div></td>
        <td class="cpbarcell"><div class="cpbar" style="width:${bar}%"></div></td>
        <td class="num">${pct.toFixed(0)}%</td>
        <td class="l cpwho">${who}</td>
      </tr>`;
    };

    const table = (rows, dir, blurb, emptyMsg) => rows.length
      ? `<div class="cpsect">${blurb}</div>
         <table class="cptable"><tbody>${rows.map(x => row(x, dir)).join("")}</tbody></table>`
      : `<div class="cpsect">${blurb}</div><div class="empty">${emptyMsg}</div>`;

    const basisNote = d.basis === "equal"
      ? "Prices haven't loaded yet, so every holding is weighted equally here."
      : "Percentages start from the share of your portfolio value sitting behind each company.";

    body.innerHTML =
      table(d.downstream, "down",
            "<b>Who your companies sell to.</b> Shared customers are demand-side concentration: if this buyer pulls back, several holdings feel it at once.",
            "No customer is shared by two or more of your holdings.") +
      table(d.upstream, "up",
            "<b>What your companies depend on.</b> Shared suppliers are the concentration you did not choose — you may not own any of these.",
            "No supplier is shared by two or more of your holdings. Structurally, that is what diversification looks like.") +
      `<div class="cpnote">${esc(basisNote)} That share is then discounted twice:
        once for distance — a direct link counts in full, each further hop counts
        half — and once for what the map records about the links themselves, where
        a sole-source dependency a filing backs counts for more than one nobody has
        checked. So these numbers are smaller than the share of your money that
        merely reaches each company, deliberately: reaching something in three
        steps down unproven links is not the same as depending on it. The number
        beside each holding is how many steps away it sits. ${esc(d.note)}</div>` +
      (d.unmapped.length ? `<div class="cpnote">Not in the map: ${d.unmapped.map(esc).join(", ")} —
        add them to supply_chain.json to include them here.</div>` : "");
  } catch (e) {
    body.innerHTML = `<div class="empty">Could not work out dependencies.</div>`;
  }
}

async function loadJournal() {
  const el = $("journal");
  try {
    const d = await (await fetch("/api/journal")).json();
    JOURNAL_BY_SYM = {};
    for (const e of d.entries) {
      (JOURNAL_BY_SYM[e.symbol] = JOURNAL_BY_SYM[e.symbol] || []).push({ date: e.date, side: e.side });
    }
    const syms = HOLDINGS.map(h => h.symbol);
    el.innerHTML = `
      <div class="j-form">
        <input id="j-date" value="${new Date().toISOString().slice(0, 10)}" size="10">
        <select id="j-sym">${syms.map(s => `<option>${s}</option>`).join("")}</select>
        <select id="j-side"><option>buy</option><option>sell</option><option>note</option></select>
        <input id="j-price" placeholder="price" inputmode="decimal" size="7">
        <input id="j-shares" placeholder="shares" inputmode="decimal" size="6">
        <input class="reason" id="j-reason" placeholder="why? one honest sentence — future-you is the audience">
        <button id="j-add">Log it</button>
      </div>
      <div class="j-stats">${d.graded ? `Marked to today: <b>${d.wins}/${d.graded}</b> calls in the green (<b>${fmtNum(d.hit_rate_pct, 0)}%</b>).${d.note ? " " + d.note : ""}` : "Log real decisions with a reason. The chart markers and the hit rate come free."}</div>
      <div>${d.entries.slice().reverse().map(e => `
        <div class="j-entry">
          <span class="jd">${e.date}</span>
          <span class="js ${e.side === "buy" ? "up" : e.side === "sell" ? "down" : "dim"}">${e.side.toUpperCase()} ${e.symbol}${e.price ? " @ " + fmtNum(e.price) : ""}${e.shares ? " ×" + e.shares : ""}</span>
          <span class="jr">${esc(e.reason || "")}</span>
          ${e._ret_pct != null ? `<span class="j-badge ${e._win ? "win" : "loss"}">${signPct(e._ret_pct)} since</span>` : ""}
          <button class="del" data-jdel="${e.id}">✕</button>
        </div>`).join("") || '<div class="empty">Nothing logged yet.</div>'}</div>`;
    $("j-add").addEventListener("click", addJournal);
    $("j-sym").addEventListener("change", prefillJournalPrice);
    prefillJournalPrice();
    el.querySelectorAll("[data-jdel]").forEach(b =>
      b.addEventListener("click", async () => { await fetch("/api/journal/" + b.dataset.jdel, { method: "DELETE" }); loadJournal(); drawCharts(); }));
    $("jmeta").textContent = d.entries.length ? `${d.entries.length} entries` : "";
    drawCharts();     // repaint markers
  } catch (e) {
    el.innerHTML = '<div class="empty">Journal unavailable.</div>';
  }
}

function prefillJournalPrice() {
  const s = $("j-sym") && $("j-sym").value;
  if (s && lastPrice[s]) $("j-price").value = lastPrice[s];
}

async function addJournal() {
  const body = {
    date: $("j-date").value.trim(), symbol: $("j-sym").value, side: $("j-side").value,
    price: parseFloat($("j-price").value) || null,
    shares: parseFloat($("j-shares").value) || null,
    reason: $("j-reason").value,
  };
  if (!body.reason.trim() && body.side !== "note") {
    $("j-reason").placeholder = "the reason IS the journal — one sentence";
    $("j-reason").focus(); return;
  }
  await fetch("/api/journal", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  $("j-reason").value = ""; $("j-shares").value = "";
  loadJournal();
}

/* ======================================================================== */
/*  SUPPLY CHAIN GRAPH                                                      */
/* ======================================================================== */

const CH = { nodes: [], edges: [], quotes: {}, holdings: [], net: "defense",
             tx: 0, ty: 0, scale: 1, hover: null, draggingNode: null, panning: null };
let chainDraw = null;

async function initChain() {
  const sel = $("chainnet");
  if (!sel) return;
  await loadChain(CH.net);
  sel.addEventListener("change", () => loadChain(sel.value));
  const cv = $("chaincanvas");
  cv.addEventListener("mousedown", chainDown);
  cv.addEventListener("mousemove", chainMove);
  window.addEventListener("mouseup", chainRelease);
  cv.addEventListener("wheel", (e) => {
    e.preventDefault();
    const f = e.deltaY < 0 ? 1.1 : 0.9;
    hideChainCard();
    CH.scale = Math.min(2.2, Math.max(0.45, CH.scale * f));
    clearTimeout(window._chsv); window._chsv = setTimeout(chainSaveState, 400);
    chainDraw();
  }, { passive: false });
  // ---- touch: drag, pinch-zoom, tap for the card, double-tap to focus,
  // long-press to add to the watchlist (the phone stand-in for right-click).
  const touchPt = (t) => ({ clientX: t.clientX, clientY: t.clientY, preventDefault() {} });
  let pinchFrom = null, lastTapAt = 0, lastTapNode = null, pressTimer = null;

  cv.addEventListener("touchstart", (e) => {
    if (e.touches.length === 2) {                       // pinch takes over
      clearTimeout(pressTimer);
      CH.draggingNode = null; CH.panning = null;
      const [a, b2] = [e.touches[0], e.touches[1]];
      pinchFrom = { d: Math.hypot(a.clientX - b2.clientX, a.clientY - b2.clientY), s: CH.scale };
      hideChainCard();
      return;
    }
    if (e.touches.length !== 1) return;
    e.preventDefault();
    const t = e.touches[0];
    const node = chainHit(chainPoint(touchPt(t)));

    // double-tap the same node -> focus its neighbourhood
    const now = Date.now();
    if (node && node === lastTapNode && now - lastTapAt < 420) {
      lastTapAt = 0; lastTapNode = null;
      CH.focus = CH.focus === node ? null : node;
      CH.focusDir = null;
      hideChainCard();
      if (CH.focus) renderFocusInfo(); else renderChainInfo();
      chainDraw();
      CH.downPt = null;
      return;
    }
    lastTapAt = now; lastTapNode = node;

    chainDown(touchPt(t));
    if (node && node.ticker) {                          // long-press = add to watchlist
      pressTimer = setTimeout(async () => {
        CH.draggingNode = null; CH.panning = null; CH.downPt = null;
        const el = $("chaininfo");
        const res = await chainAddWatch(node);
        el.innerHTML = res === "already"
          ? `<b>${node.ticker}</b> is already in your book.`
          : `✓ <b>${node.ticker}</b> added as watch-only.`;
        el.className = "chaininfo on";
        if (navigator.vibrate) navigator.vibrate(12);
      }, 600);
    }
  }, { passive: false });

  cv.addEventListener("touchmove", (e) => {
    if (pinchFrom && e.touches.length === 2) {
      e.preventDefault();
      const [a, b2] = [e.touches[0], e.touches[1]];
      const d = Math.hypot(a.clientX - b2.clientX, a.clientY - b2.clientY);
      CH.scale = Math.min(2.2, Math.max(0.45, pinchFrom.s * (d / (pinchFrom.d || 1))));
      clearTimeout(window._chsv); window._chsv = setTimeout(chainSaveState, 400);
      chainDraw();
      return;
    }
    if (e.touches.length !== 1) return;
    e.preventDefault();
    clearTimeout(pressTimer);                            // any movement cancels long-press
    chainMove(touchPt(e.touches[0]));
  }, { passive: false });

  const endTouch = () => {
    clearTimeout(pressTimer);
    if (pinchFrom) { pinchFrom = null; chainSaveState(); return; }
    chainRelease();
  };
  cv.addEventListener("touchend", endTouch);
  cv.addEventListener("touchcancel", endTouch);

  window.addEventListener("resize", () => { clearTimeout(window._ct); window._ct = setTimeout(() => chainDraw && chainDraw(), 150); });
  cv.addEventListener("dblclick", (e) => {
    const n = chainHit(chainPoint(e));
    CH.focus = (n && CH.focus !== n) ? n : null;
    CH.focusDir = null;
    if (CH.focus) renderFocusInfo();
    else { CH.sel = null; renderChainInfo(); }
    chainDraw();
  });
  cv.addEventListener("contextmenu", async (e) => {
    e.preventDefault();
    const n = chainHit(chainPoint(e));
    if (!n || !n.ticker) return;
    const el = $("chaininfo");
    if (CH.holdings.includes(n.ticker)) {
      el.innerHTML = `<b>${n.ticker}</b> is already in your book.`;
      el.className = "chaininfo on";
      return;
    }
    try {
      await fetch("/api/holdings", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: n.ticker, shares: 0, cost_basis: 0 }) });
      CH.holdings.push(n.ticker);
      el.innerHTML = `✓ <b>${n.ticker}</b> added to holdings as watch-only — full analysis, doesn't count toward the book.`;
      el.className = "chaininfo on";
      loadHoldings(); loadAnalysis(); chainDraw();
    } catch (err) {
      el.innerHTML = `couldn't add ${n.ticker} — is the server up?`;
      el.className = "chaininfo on";
    }
  });
  const cs = $("chainsearch");
  if (cs) cs.addEventListener("input", () => { CH.q = cs.value.trim().toUpperCase(); chainDraw(); });
  const lb = $("chainlabels");
  if (lb) lb.addEventListener("click", () => {
    CH.labelsOn = !CH.labelsOn;
    lb.classList.toggle("on", CH.labelsOn);
    const anyFilter = CH.path || CH.focus || CH.bookOn || CH.q;
    CH.labelsDense = CH.labelsOn && CH.edges.length > 140 && !anyFilter;
    if (CH.labelsDense) {
      const el = $("chaininfo");
      el.innerHTML = "🏷 too dense to label everything at once — search, focus, trace a path, or switch to a single industry and the captions appear.";
      el.className = "chaininfo on";
    }
    chainDraw();
  });
  const pb = $("chainpath");
  if (pb) pb.addEventListener("click", () => {
    CH.pathMode = !CH.pathMode;
    CH.pathA = null;
    pb.classList.toggle("on", CH.pathMode);
    const el = $("chaininfo");
    if (CH.pathMode) {
      el.innerHTML = "⇄ path mode — click the <b>first</b> company…";
      el.className = "chaininfo on";
    } else { CH.path = null; CH.pathEdges = null; renderChainInfo(); chainDraw(); }
  });
  const bb = $("chainbook");
  if (bb) bb.addEventListener("click", () => {
    CH.bookOn = !CH.bookOn;
    bb.classList.toggle("on", CH.bookOn);
    const el = $("chaininfo");
    if (CH.bookOn) {
      CH.bookHops = CH.bookHops || 1;
      CH.bookSet = chainBookSet(CH.bookHops);
      renderBookInfo();
    } else { CH.bookSet = null; renderChainInfo(); }
    chainDraw();
  });
  const xp = $("chainexport");
  if (xp) xp.addEventListener("click", () => {
    chainDraw();
    cv.toBlob((blob) => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `windrose-chain-${CH.net || "map"}.png`;
      a.click(); URL.revokeObjectURL(a.href);
    });
  });
  const mx = $("chainmax");
  if (mx) mx.addEventListener("click", () => {
    cv.classList.toggle("max");
    mx.classList.toggle("on", cv.classList.contains("max"));
    chainDraw();
  });
  setInterval(() => loadChainQuotes(), 60000);
}

async function loadChain(net) {
  try {
    const info = $("chaininfo");
    if (info) {
      info.textContent = net === "all"
        ? "Loading every industry — this one is big…"
        : `Loading ${net}…`;
      info.className = "chaininfo on";
    }
    // graph first (fast), prices second (slow) — see api_chain's quotes flag
    const d = await (await fetch("/api/chain?net=" + net + "&quotes=0")).json();
    if (!d.ok) return;
    CH.net = d.id;
    CH.quotes = d.quotes || {};
    CH.holdings = d.holdings || [];
    const sel = $("chainnet");
    sel.innerHTML = d.available.map(a => `<option value="${a}" ${a === d.id ? "selected" : ""}>${a}</option>`).join("");
    // build nodes with force-layout seed
    const cv = $("chaincanvas");
    const W = cv.clientWidth || 900, H = 430;
    let seed = 42;
    const rnd = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
    let savedPos = {};
    try { savedPos = JSON.parse(localStorage.getItem("ledger-chain:" + d.id) || "{}"); } catch (e) {}
    // FLOW LAYOUT — supply reads left to right: pure producers in column 0,
    // end customers in the last column. Longest-path layering, cycle-capped.
    const netList = (d.available || []).filter(x => x !== "all");
    const rawEdges = d.network.edges || [];
    const layer = {};
    d.network.nodes.forEach(n => { layer[n.id] = 0; });
    for (let it = 0; it < 14; it++) {
      let moved = false;
      for (const e of rawEdges) {
        const cand = (layer[e.from] || 0) + 1;
        if (cand > (layer[e.to] || 0) && cand <= 12) { layer[e.to] = cand; moved = true; }
      }
      if (!moved) break;
    }
    const maxL = Math.max(1, ...Object.values(layer));
    // stack order within each column: by home industry (merged) or type, then id
    const cols = {};
    d.network.nodes.forEach(n => { (cols[layer[n.id]] = cols[layer[n.id]] || []).push(n); });
    const rowOf = {};
    for (const L of Object.keys(cols)) {
      cols[L].sort((a, b) =>
        ((a.nets ? a.nets[0] : a.type) || "").localeCompare((b.nets ? b.nets[0] : b.type) || "") ||
        a.id.localeCompare(b.id));
      cols[L].forEach((n, i) => { rowOf[n.id] = [i, cols[L].length]; });
    }
    const padX = 70;
    CH.nodes = d.network.nodes.map(n => {
      const sp = savedPos[n.id];
      const ax = padX + (layer[n.id] / maxL) * (W - padX * 2);
      const [ri, rc] = rowOf[n.id];
      const ay = H * 0.09 + (rc === 1 ? H * 0.41 : (ri / (rc - 1)) * H * 0.82);
      return {
        ...n, ticker: n.ticker === undefined ? n.id : n.ticker,
        _ax: ax, _ay: ay, _layer: layer[n.id],
        x: sp ? sp[0] : ax + (rnd() - 0.5) * 30,
        y: sp ? sp[1] : ay + (rnd() - 0.5) * 24,
        vx: 0, vy: 0, pinned: !!sp,
      };
    });
    // the merged graph needs room — expand automatically
    // columns win the x-axis; physics keeps the y-axis organic
    setTimeout(() => {
      for (const n of CH.nodes) if (!n.pinned && n._ax != null) n.x = n._ax * 0.65 + n.x * 0.35;
      chainDraw();
    }, 1200);
    const _cv = $("chaincanvas"), _mx = $("chainmax");
    if (d.id === "all" && _cv && !_cv.classList.contains("max")) {
      _cv.classList.add("max"); if (_mx) _mx.classList.add("on");
    }
    if (savedPos._view) { CH.tx = savedPos._view[0]; CH.ty = savedPos._view[1]; CH.scale = savedPos._view[2]; }
    else { CH.tx = 0; CH.ty = 0; CH.scale = 1; }
    hideChainCard(); clearTimeout(CH._dwellT); CH._dwellNode = null;
    CH.sel = null; CH.q = ""; CH.focus = null; CH.focusDir = null;
    CH.path = null; CH.pathEdges = null; CH.pathMode = false; CH.pathA = null;
    CH.bookOn = false; CH.bookSet = null; CH.bookHops = 1;
    ["chainpath", "chainbook"].forEach(id => { const b = $(id); if (b) b.classList.remove("on"); });
    const _cs = $("chainsearch"); if (_cs) _cs.value = "";
    renderChainInfo();
    const byId = Object.fromEntries(CH.nodes.map(n => [n.id, n]));
    CH.edges = d.network.edges.filter(e => byId[e.from] && byId[e.to])
      .map(e => ({ ...e, a: byId[e.from], b: byId[e.to] }));
    forceLayout(W, H, 260);
    CH.tx = 0; CH.ty = 0; CH.scale = 1; CH.hover = null;
    loadChainQuotes();                     // prices arrive a moment later
    if (CH.labelsOn && CH.edges.length > 140) {
      const el = $("chaininfo");
      el.innerHTML = "🏷 labels stay hidden at this density — search, focus, or trace a path and they appear.";
      el.className = "chaininfo on";
    }
    $("chainlegend").innerHTML = d.id === "all"
      ? `<span class="meta">${CH.nodes.length} companies · ${CH.edges.length} links · ${netList.length} industries fused — double-click a node to isolate its world</span>`
      : [...new Set(CH.nodes.map(n => n.type))].map(t =>
          `<span><i style="background:${typeColor(t)}"></i>${t}</span>`).join("");
    chainDraw();
    if (d.note && !(CH.labelsOn && CH.edges.length > 140)) {
      $("chaininfo").textContent = d.note; $("chaininfo").className = "chaininfo on";
    } else if ($("chaininfo").textContent.startsWith("Loading")) {
      $("chaininfo").textContent = ""; $("chaininfo").className = "chaininfo";
    }
  } catch (e) {}
}

async function loadChainQuotes() {
  try {
    const d = await (await fetch("/api/chain?net=" + CH.net)).json();
    if (d.ok) { CH.quotes = d.quotes || {}; chainDraw(); }
  } catch (e) {}
}

function forceLayout(W, H, iters) {
  for (let it = 0; it < iters; it++) {
    const t = 1 - it / iters;
    for (const n of CH.nodes) { n.fx = 0; n.fy = 0; }
    for (let i = 0; i < CH.nodes.length; i++) {
      for (let k = i + 1; k < CH.nodes.length; k++) {
        const a = CH.nodes[i], b = CH.nodes[k];
        let dx = a.x - b.x, dy = a.y - b.y;
        let d2 = dx * dx + dy * dy + 0.01, d = Math.sqrt(d2);
        const rep = 14000 / d2;
        dx /= d; dy /= d;
        a.fx += dx * rep; a.fy += dy * rep;
        b.fx -= dx * rep; b.fy -= dy * rep;
      }
    }
    for (const e of CH.edges) {
      let dx = e.b.x - e.a.x, dy = e.b.y - e.a.y;
      const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const pull = (d - 150) * 0.012;
      dx /= d; dy /= d;
      e.a.fx += dx * pull * d; e.a.fy += dy * pull * d;
      e.b.fx -= dx * pull * d; e.b.fy -= dy * pull * d;
    }
    for (const n of CH.nodes) {
      if (n.pinned) continue;
      const axx = n._ax != null ? n._ax : W / 2, ayy = n._ay != null ? n._ay : H / 2;
      n.fx += (axx - n.x) * (n._ax != null ? 0.1 : 0.012);
      n.fy += (ayy - n.y) * 0.02;
      n.x += Math.max(-14, Math.min(14, n.fx * t));
      n.y += Math.max(-14, Math.min(14, n.fy * t));
      n.x = Math.max(46, Math.min(W - 46, n.x));
      n.y = Math.max(26, Math.min(H - 26, n.y));
    }
  }
}

function typeColor(t) {
  const map = {
    prime: css("--accent"), designer: css("--accent"),
    supplier: css("--warn"), equipment: css("--warn"), subsystems: css("--warn"),
    engines: css("--warn"), memory: css("--warn"), ip: css("--text-2"),
    foundry: css("--up"), customer: css("--text-dim"), airline: css("--text-dim"),
    oem: css("--up"), hyperscaler: css("--text-dim"),
    rail: css("--warn"), parcel: css("--warn"), warehouse: css("--text-2"),
    ocean: css("--text-2"), retail: css("--text-dim"),
    streamer: css("--accent"), studio: css("--up"), rights: css("--warn"),
    ads: css("--text-2"), theater: css("--text-dim"),
    builder: css("--accent"), materials: css("--warn"), distribution: css("--text-2"),
    hvac: css("--warn"), bank: css("--accent"), fintech: css("--text-2"),
    processor: css("--warn"), exchange: css("--text-2"), data: css("--text-2"),
    bigtech: css("--text-dim"), pharma: css("--accent"), tools: css("--warn"),
    cdmo: css("--warn"), pharmacy: css("--up"),
    producer: css("--accent"), refiner: css("--up"), midstream: css("--text-2"),
    lng: css("--up"), generator: css("--up"), load: css("--text-dim"),
  };
  return map[t] || css("--text-2");
}

chainDraw = function () {
  const cv = $("chaincanvas");
  if (!cv || !CH.nodes.length) return;
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = cv.clientHeight || 430;
  cv.width = W * dpr; cv.height = H * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.fillStyle = css("--ink");
  ctx.fillRect(0, 0, W, H);
  ctx.save();
  ctx.translate(CH.tx, CH.ty); ctx.scale(CH.scale, CH.scale);

  const hovered = CH.hover;
  const connected = new Set();
  if (hovered) {
    connected.add(hovered.id);
    for (const e of CH.edges) {
      if (e.a === hovered || e.b === hovered) { connected.add(e.a.id); connected.add(e.b.id); }
    }
  }
  const qs = CH.q || "";
  if (CH.labelsOn) {
    const anyFilter = CH.path || CH.focus || CH.bookOn || qs;
    CH.labelsDense = CH.edges.length > 140 && !anyFilter;
  }
  const P = CH.path ? new Set(CH.path) : null;
  const PE = CH.pathEdges;
  const B = CH.bookOn ? CH.bookSet : null;
  const F = CH.focus;
  const fset = F ? chainFocusSet() : new Set();
  const fTouch = (e) => CH.focusDir === "up" ? e.b === F
                      : CH.focusDir === "down" ? e.a === F
                      : (e.a === F || e.b === F);
  const qmatch = (n) => !qs || n.id.toUpperCase().includes(qs) ||
    (n.label || "").toUpperCase().includes(qs) || (n.ticker || "").toUpperCase().includes(qs);

  // edges
  for (const e of CH.edges) {
    const active = hovered && (e.a === hovered || e.b === hovered);
    ctx.strokeStyle = active ? css("--accent") : css("--line");
    ctx.lineWidth = 1;
    let eAlpha = 1;
    if (PE && PE.has(e)) {
      ctx.strokeStyle = css("--accent"); ctx.lineWidth = 2.4;
    } else {
      const fOut = F && !fTouch(e);
      const bOut = B && !(B.has(e.a.id) && B.has(e.b.id));
      eAlpha = P ? 0.05 : fOut ? 0.05 : bOut ? 0.07 :
        (hovered && !active) || (qs && !(qmatch(e.a) || qmatch(e.b))) ? 0.12 : 1;
    }
    ctx.globalAlpha = eAlpha;
    ctx.lineWidth = active ? 1.6 : 1;
    ctx.beginPath(); ctx.moveTo(e.a.x, e.a.y); ctx.lineTo(e.b.x, e.b.y); ctx.stroke();
    // arrowhead at the customer end
    const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y, d = Math.hypot(dx, dy);
    const ux = dx / d, uy = dy / d;
    const ax = e.b.x - ux * 40, ay = e.b.y - uy * 40;
    ctx.fillStyle = ctx.strokeStyle;
    ctx.beginPath();
    ctx.moveTo(ax, ay);
    ctx.lineTo(ax - ux * 8 - uy * 4, ay - uy * 8 + ux * 4);
    ctx.lineTo(ax - ux * 8 + uy * 4, ay - uy * 8 - ux * 4);
    ctx.closePath(); ctx.fill();
    const wantLabel = active || (CH.labelsOn && eAlpha >= 0.9 && !CH.labelsDense);
    if (wantLabel) {
      ctx.font = "9.5px 'IBM Plex Mono', monospace";
      ctx.fillStyle = css("--text-2");
      ctx.globalAlpha = active ? 1 : 0.85;
      const t = e.rel.length > 30 ? e.rel.slice(0, 29) + "…" : e.rel;
      ctx.fillText(t, (e.a.x + e.b.x) / 2 + 5, (e.a.y + e.b.y) / 2 - 4);
    }
  }
  ctx.globalAlpha = 1;

  // nodes
  for (const n of CH.nodes) {
    const dimmed = (P && !P.has(n.id)) || (B && !B.has(n.id)) ||
      (F && !fset.has(n.id)) || (hovered && !connected.has(n.id)) || (qs && !qmatch(n));
    const q = n.ticker ? CH.quotes[n.ticker] : null;
    const held = CH.holdings.includes(n.ticker);
    const w = 62, h = 30;
    ctx.globalAlpha = dimmed ? 0.22 : 1;
    ctx.fillStyle = css("--panel");
    const isSel = CH.sel === n;
    ctx.strokeStyle = isSel || held ? css("--accent") : typeColor(n.type);
    ctx.lineWidth = isSel ? 2.6 : held ? 2 : 1.2;
    if (held) { ctx.shadowColor = css("--accent"); ctx.shadowBlur = 16; }
    roundRect(ctx, n.x - w / 2, n.y - h / 2, w, h, 6);
    ctx.fill(); ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.textAlign = "center";
    ctx.font = "600 11px 'IBM Plex Mono', monospace";
    ctx.fillStyle = css("--text");
    ctx.fillText(n.ticker || n.id, n.x, n.y - 2);
    ctx.font = "9px 'IBM Plex Mono', monospace";
    if (q && q.change_pct != null) {
      ctx.fillStyle = q.change_pct >= 0 ? css("--up") : css("--down");
      ctx.fillText((q.change_pct >= 0 ? "+" : "") + q.change_pct + "%", n.x, n.y + 10);
    } else {
      ctx.fillStyle = css("--text-dim");
      ctx.fillText(n.ticker ? "…" : "—", n.x, n.y + 10);
    }
  }
  ctx.restore();
};

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

function renderChainInfo() {
  const el = $("chaininfo");
  const n = CH.sel;
  if (!n) { el.className = "chaininfo"; el.innerHTML = ""; return; }
  const q = n.ticker ? CH.quotes[n.ticker] : null;
  const feeds = CH.edges.filter(e => e.a === n).length;
  const fedby = CH.edges.filter(e => e.b === n).length;
  const px = q ? `$${q.price} <span class="${q.change_pct >= 0 ? "up" : "down"}">${q.change_pct >= 0 ? "+" : ""}${q.change_pct}%</span>` : "—";
  el.innerHTML = `<b>${esc(n.ticker || n.id)}</b> ${esc(n.label)} · ${px} · supplies ${feeds} · buys from ${fedby}` +
    (n.ticker ? ` <button class="anlz" id="chainanlz">analyze in workbench ↗</button>` : "");
  el.className = "chaininfo on";
  const btn = $("chainanlz");
  if (btn) btn.addEventListener("click", () => chainAnalyze(n.ticker));
}

function chainFindPath(aId, bId) {
  const adj = new Map();
  const link = (u, v) => { if (!adj.has(u)) adj.set(u, new Set()); adj.get(u).add(v); };
  for (const e of CH.edges) { link(e.a.id, e.b.id); link(e.b.id, e.a.id); }
  if (!adj.has(aId) || !adj.has(bId)) return null;
  const prev = new Map([[aId, null]]);
  const queue = [aId];
  while (queue.length) {
    const u = queue.shift();
    if (u === bId) break;
    for (const v of adj.get(u) || []) {
      if (!prev.has(v)) { prev.set(v, u); queue.push(v); }
    }
  }
  if (!prev.has(bId)) return null;
  const path = [];
  for (let u = bId; u !== null; u = prev.get(u)) path.unshift(u);
  return path;
}

function chainApplyPath(path) {
  CH.path = path;
  CH.pathEdges = new Set();
  const el = $("chaininfo");
  if (!path) {
    el.innerHTML = "no route between those two in this view — try the <b>all</b> view, where every industry connects.";
    el.className = "chaininfo on"; chainDraw(); return;
  }
  const bits = [path[0]];
  for (let i = 0; i < path.length - 1; i++) {
    const u = path[i], v = path[i + 1];
    const e = CH.edges.find(x => (x.a.id === u && x.b.id === v) || (x.a.id === v && x.b.id === u));
    if (e) CH.pathEdges.add(e);
    bits.push(e && e.a.id === u ? " → " : " ← ", path[i + 1]);
  }
  el.innerHTML = `⇄ <b>${path[0]}</b> to <b>${path[path.length - 1]}</b> — ${path.length - 1} hops: ` +
    `<span class="mono">${bits.join("")}</span> · hover an edge for the relationship · click empty space to clear`;
  el.className = "chaininfo on";
  chainDraw();
}
window._chainPath = (a, b) => { const p = chainFindPath(a, b); chainApplyPath(p); return p; };

function chainBookSet(hops = 1) {
  const set = new Set();
  for (const n of CH.nodes) if (n.ticker && CH.holdings.includes(n.ticker)) set.add(n.id);
  for (let h = 0; h < hops; h++) {
    const grow = new Set(set);
    for (const e of CH.edges) {
      if (set.has(e.a.id)) grow.add(e.b.id);
      if (set.has(e.b.id)) grow.add(e.a.id);
    }
    if (grow.size === set.size) break;
    grow.forEach(x => set.add(x));
  }
  return set;
}

function renderBookInfo() {
  const el = $("chaininfo");
  const owned = CH.nodes.filter(n => n.ticker && CH.holdings.includes(n.ticker)).length;
  const reach = Math.max(0, CH.bookSet.size - owned);
  const hops = CH.bookHops || 1;
  el.innerHTML = `◉ your book — ${owned} holding${owned === 1 ? "" : "s"} here, reaching <b>${reach}</b> companies within ` +
    [1, 2, 3].map(h => `<button class="anlz hopbtn${h === hops ? " onhop" : ""}" data-hop="${h}">${h}</button>`).join("") +
    ` hop${hops === 1 ? "" : "s"}.`;
  el.className = "chaininfo on";
  el.querySelectorAll(".hopbtn").forEach(b => b.addEventListener("click", () => {
    CH.bookHops = parseInt(b.dataset.hop, 10);
    CH.bookSet = chainBookSet(CH.bookHops);
    renderBookInfo(); chainDraw();
  }));
}

function chainAnalyze(ticker) {
  if (!ticker) return;
  hideChainCard();                       // the popup was staying up and covering the result

  MW.sym = ticker;
  const def = MW_DEFS[MW.tab];
  if (!def || !def.perTicker) {
    mwSwitch("rdcf");                    // Monte Carlo / stress have no ticker — move to one that does
  } else {
    mwRenderSel();                       // rebuild the dropdown so it shows the new ticker
    mwFetch();
  }

  const panel = document.querySelector('[data-panel="workbench"]');
  if (!panel) return;
  // scrollIntoView tucks the panel under the sticky header; offset by its height
  const head = document.querySelector(".stickyhead");
  const off = (head ? head.getBoundingClientRect().height : 0) + 10;
  const top = panel.getBoundingClientRect().top + window.pageYOffset - off;
  window.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
  panel.classList.add("flash");
  setTimeout(() => panel.classList.remove("flash"), 1200);
}

async function chainAddWatch(n) {
  if (!n.ticker || CH.holdings.includes(n.ticker)) return "already";
  await fetch("/api/holdings", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symbol: n.ticker, shares: 0, cost_basis: 0 }) });
  CH.holdings.push(n.ticker);
  loadHoldings(); loadAnalysis(); chainDraw();
  return "added";
}

function chainFocusSet() {
  const F = CH.focus, set = new Set();
  if (!F) return set;
  set.add(F.id);
  const dir = CH.focusDir;
  for (const e of CH.edges) {
    if (e.a === F && dir !== "up") set.add(e.b.id);
    if (e.b === F && dir !== "down") set.add(e.a.id);
  }
  return set;
}

function renderFocusInfo() {
  const F = CH.focus, el = $("chaininfo");
  if (!F) { renderChainInfo(); return; }
  const sup = CH.edges.filter(e => e.b === F).length;
  const cust = CH.edges.filter(e => e.a === F).length;
  const dir = CH.focusDir || "both";
  const btn = (dv, label) => `<button class="anzl anlz hopbtn${dir === dv ? " onhop" : ""}" data-dir="${dv}">${label}</button>`;
  el.innerHTML = `◎ <b>${F.ticker || F.id}</b> ${F.label || ""} — ` +
    btn("up", `◂ suppliers ${sup}`) + btn("both", "both") + btn("down", `customers ${cust} ▸`) +
    ` <span class="meta">· double-click empty space to exit</span>`;
  el.className = "chaininfo on";
  el.querySelectorAll("[data-dir]").forEach(b => b.addEventListener("click", () => {
    CH.focusDir = b.dataset.dir === "both" ? null : b.dataset.dir;
    renderFocusInfo(); chainDraw();
  }));
}

function fmtMcap(v) {
  if (!v) return "";
  if (v >= 1e12) return "$" + (v / 1e12).toFixed(2) + "T";
  if (v >= 1e9) return "$" + (v / 1e9).toFixed(1) + "B";
  return "$" + (v / 1e6).toFixed(0) + "M";
}

function showChainCard(n) {
  const card = $("chaincard");
  const cv = $("chaincanvas");
  const r = cv.getBoundingClientRect();
  const sx = r.left + (n.x * CH.scale + CH.tx), sy = r.top + (n.y * CH.scale + CH.ty);
  const q = n.ticker ? CH.quotes[n.ticker] : null;
  const px = q ? `$${q.price} <span class="${q.change_pct >= 0 ? "up" : "down"}">${q.change_pct >= 0 ? "+" : ""}${q.change_pct}%</span>` : "";
  const out = CH.edges.filter(e => e.a === n), inn = CH.edges.filter(e => e.b === n);
  const relLine = (e, dir) => `<div class="ccrel">${dir === "out" ? "→ <b>" + esc(e.b.ticker || e.b.id) + "</b>" : "← <b>" + esc(e.a.ticker || e.a.id) + "</b>"} · ${esc(e.rel.length > 26 ? e.rel.slice(0, 25) + "…" : e.rel)}</div>`;
  card.innerHTML = `
    <span class="ccx" id="ccx">×</span>
    <div class="cchead"><span class="ccsym">${esc(n.ticker || n.id)}</span><span class="ccpx">${px}</span></div>
    <div class="ccname">${esc(n.label || "")}</div>
    ${n.ticker ? '<canvas class="ccspark" id="ccspark" width="220" height="34"></canvas>' : ""}
    <span class="cctype">${esc(n.type || "")}</span>
    ${out.slice(0, 2).map(e => relLine(e, "out")).join("")}
    ${inn.slice(0, 2).map(e => relLine(e, "in")).join("")}
    ${out.length + inn.length > 4 ? `<div class="ccrel">… ${out.length + inn.length - 4} more relationships</div>` : ""}
    <div class="ccsector" id="ccsector"></div>
    ${n.ticker ? `<div class="ccrow">
      <button class="anlz" id="ccanlz">analyze ↗</button>
      <button class="anlz" id="ccwatch">${CH.holdings.includes(n.ticker) ? "in book ✓" : "+ watch"}</button>
    </div>` : ""}`;
  card.style.display = "block";
  const cw = 250, chh = card.offsetHeight || 200;
  let x = sx + 46, y = sy - 20;
  if (x + cw > innerWidth - 10) x = sx - cw - 46;
  y = Math.max(10, Math.min(y, innerHeight - chh - 10));
  card.style.left = Math.max(10, x) + "px"; card.style.top = y + "px";
  $("ccx").addEventListener("click", hideChainCard);
  const az = $("ccanlz"); if (az) az.addEventListener("click", () => chainAnalyze(n.ticker));
  const wb = $("ccwatch");
  if (wb) wb.addEventListener("click", async () => {
    const res = await chainAddWatch(n);
    wb.textContent = res === "added" ? "watching ✓" : "in book ✓";
  });
  if (n.ticker) {
    fetch("/api/company/" + n.ticker).then(r => r.json()).then(d => {
      const el = $("ccsector");
      if (el && d.ok && (d.sector || d.market_cap))
        el.textContent = [d.sector, d.industry, fmtMcap(d.market_cap)].filter(Boolean).join(" · ");
      const sc = $("ccspark");
      if (sc && d.ok && d.spark && d.spark.length > 3) {
        const g = sc.getContext("2d");
        const w = sc.width, hgt = sc.height, s = d.spark;
        const mn = Math.min(...s), mx = Math.max(...s), rng = (mx - mn) || 1;
        g.clearRect(0, 0, w, hgt);
        g.beginPath();
        s.forEach((v, i) => {
          const x = (i / (s.length - 1)) * (w - 4) + 2;
          const y = hgt - 4 - ((v - mn) / rng) * (hgt - 8);
          i ? g.lineTo(x, y) : g.moveTo(x, y);
        });
        g.strokeStyle = css(s[s.length - 1] >= s[0] ? "--up" : "--down");
        g.lineWidth = 1.5; g.stroke();
        sc.dataset.drawn = "1";
      }
    }).catch(() => {});
  }
}

function hideChainCard() {
  const c = $("chaincard");
  if (c) c.style.display = "none";
}

function chainRelease() {
    const clean = CH.downPt && !CH.moved && Date.now() - CH.downPt.t < 500;
    if (clean && CH.draggingNode && CH.pathMode) {
      const n = CH.draggingNode.n;
      if (!CH.pathA) {
        CH.pathA = n;
        const el = $("chaininfo");
        el.innerHTML = `⇄ from <b>${n.ticker || n.id}</b> — now click the <b>destination</b>…`;
        el.className = "chaininfo on";
      } else {
        chainApplyPath(chainFindPath(CH.pathA.id, n.id));
        CH.pathMode = false; CH.pathA = null;
        const _pb = $("chainpath"); if (_pb) _pb.classList.remove("on");
      }
    }
    else if (clean && CH.draggingNode) { CH.sel = CH.draggingNode.n; showChainCard(CH.sel); }
    else if (clean && CH.panning) {
      hideChainCard();
      CH.sel = null; CH.path = null; CH.pathEdges = null; CH.bookOn = false; CH.bookSet = null;
      const _bb = $("chainbook"); if (_bb) _bb.classList.remove("on");
      renderChainInfo();
    }
    if (CH.moved && (CH.draggingNode || CH.panning)) chainSaveState();
    CH.draggingNode = null; CH.panning = null; CH.downPt = null;
    chainDraw();
}

function chainSaveState() {
  try {
    const out = { _view: [CH.tx, CH.ty, CH.scale] };
    for (const n of CH.nodes) if (n.pinned) out[n.id] = [Math.round(n.x), Math.round(n.y)];
    localStorage.setItem("ledger-chain:" + CH.net, JSON.stringify(out));
  } catch (e) {}
}

function chainPoint(e) {
  const r = $("chaincanvas").getBoundingClientRect();
  return { x: (e.clientX - r.left - CH.tx) / CH.scale, y: (e.clientY - r.top - CH.ty) / CH.scale };
}

function chainHit(p) {
  for (let i = CH.nodes.length - 1; i >= 0; i--) {
    const n = CH.nodes[i];
    if (Math.abs(p.x - n.x) < 33 && Math.abs(p.y - n.y) < 17) return n;
  }
  return null;
}

function chainDown(e) {
  clearTimeout(CH._dwellT);
  const p = chainPoint(e);
  const n = chainHit(p);
  CH.downPt = { x: e.clientX, y: e.clientY, t: Date.now() };
  CH.moved = false;
  if (n) CH.draggingNode = { n, dx: p.x - n.x, dy: p.y - n.y };
  else CH.panning = { sx: e.clientX - CH.tx, sy: e.clientY - CH.ty };
}

function chainMove(e) {
  const p = chainPoint(e);
  if (CH.downPt && Math.hypot(e.clientX - CH.downPt.x, e.clientY - CH.downPt.y) > 4) CH.moved = true;
  const hv = (!CH.draggingNode && !CH.panning) ? chainHit(chainPoint(e)) : null;
  if (hv !== CH._dwellNode) {
    clearTimeout(CH._dwellT);
    CH._dwellNode = hv;
    const coarse = window.matchMedia && matchMedia("(pointer: coarse)").matches;
    if (hv && !CH.pathMode && !coarse) CH._dwellT = setTimeout(() => showChainCard(hv), 1500);
  }
  if (CH.draggingNode) {
    if (CH.moved) CH.draggingNode.n.pinned = true;
    CH.draggingNode.n.x = p.x - CH.draggingNode.dx;
    CH.draggingNode.n.y = p.y - CH.draggingNode.dy;
    chainDraw(); return;
  }
  if (CH.panning) {
    CH.tx = e.clientX - CH.panning.sx;
    CH.ty = e.clientY - CH.panning.sy;
    chainDraw(); return;
  }
  const n = chainHit(p);
  if (n !== CH.hover) {
    CH.hover = n;
    chainDraw();
    const info = $("chaininfo");
    if (n) {
      const sup = CH.edges.filter(ed => ed.b === n).map(ed => `${ed.a.ticker || ed.a.id} (${ed.rel})`);
      const cust = CH.edges.filter(ed => ed.a === n).map(ed => `${ed.b.ticker || ed.b.id} (${ed.rel})`);
      const q = n.ticker ? CH.quotes[n.ticker] : null;
      info.innerHTML = `<b>${n.label}</b>${q ? ` <span class="${q.change_pct >= 0 ? "up" : "down"}">${fmtNum(q.price)} ${signPct(q.change_pct)}</span>` : ""}
        ${sup.length ? ` · <span class="dim">buys from:</span> ${sup.join(", ")}` : ""}
        ${cust.length ? ` · <span class="dim">sells to:</span> ${cust.join(", ")}` : ""}`;
    } else {
      info.textContent = "";
    }
  }
}

/* analysis hook: factors ride along */
const _origLoadAnalysis = loadAnalysis;
loadAnalysis = async function () {
  await _origLoadAnalysis();
  loadFactors();
};


/* ======================================================================== */
/*  FIRST-RUN GUIDED TOUR — in-place, on the real dashboard                 */
/* ======================================================================== */

const TOUR = [
  { sel: ".futures", title: "The strip",
    body: "Futures, indices, or any tickers you want up here — hit the ✎ at the right end and type your own list. It stays pinned to the top while you scroll." },
  { sel: '[data-panel="holdings"]', title: "Your book",
    body: "Live prices and P/L against your cost. The ▸ next to a ticker drops down that company's news; the ✎ on a row lets you add an acquired date, which unlocks dividend-included returns and the exact SPY comparison." },
  { sel: '[data-panel="risk"]', title: "The panel that earns the rent",
    body: "Not what you own — how it behaves together. The paired bars show each position's share of your money against its share of your risk. They're rarely the same number." },
  { sel: '[data-panel="benchmark"]', title: "vs SPY",
    body: "The same dollars, on the same dates, dropped into the index instead. It's the only benchmark that can't be argued with." },
  { sel: '[data-panel="sandbox"]', title: "What-if",
    body: "Change the share counts — including tickers you don't own — and watch the risk math recompute. Nothing here is saved, and nothing is ever traded." },
  { sel: '[data-panel="alerts"]', title: "Alerts",
    body: "Price levels, day moves, RSI extremes, SMA crosses, drawdown. Each rule fires once when it's crossed, then re-arms when the condition clears — no spam." },
  { sel: '[data-panel="journal"]', title: "Decision journal",
    body: "Write down why, before you trade. Buys get marked to market with a running hit rate — and an honest note that a handful of calls is noise, not skill." },
  { sel: '[data-panel="workbench"]', title: "Workbench",
    body: "Reverse DCF, comps, statements, a paper LBO, M&A math, Monte Carlo, stress replays, and a strategy lab. Every assumption is a visible slider; nothing is hidden in the code." },
  { sel: '[data-panel="chain"]', title: "Supply chain",
    body: "Who feeds whom — 26 industries, ~430 companies, live quotes, flowing left to right from first producer to end customer. Click a company for its card, ⇄ traces a route between any two, ◉ lights up everything your book touches, 🏷 paints the relationships on the map. It remembers where you drag things." },
  { sel: "#modepill", title: "Simple or Advanced",
    body: "This pill switches how much machinery you see. Simple keeps the essentials in plain language; Advanced exposes every model, ratio and tool. Press <b>s</b> to flip it, or open ⚙ to change colours, density, and which panels appear at all." },
  { sel: "#layoutbtn", title: "Make it yours",
    body: "Toggle this, then drag any panel by its ⠿ handle into either column or the full-width row. The arrangement sticks." },
  { sel: 'a[href="/tutorial"]', title: "Going deeper",
    body: "This tour is the two-minute version. The full written walkthrough — every number, where it comes from, where it lies to you — lives behind learn." },
];

let TOUR_I = 0;

function tourStart() { TOUR_I = 0; tourShow(); }

function tourShow() {
  const step = TOUR[TOUR_I];
  const el = step && document.querySelector(step.sel);
  if (!el) { if (TOUR_I < TOUR.length - 1) { TOUR_I++; return tourShow(); } return tourEnd(); }
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  setTimeout(() => {
    const r = el.getBoundingClientRect();
    const box = $("tourbox"), card = $("tourcard");
    box.style.display = "block";
    box.style.left = (r.left - 8) + "px"; box.style.top = (r.top - 8) + "px";
    box.style.width = (r.width + 16) + "px"; box.style.height = (r.height + 16) + "px";
    card.style.display = "block";
    card.innerHTML = `
      <h4>${step.title}</h4><p>${step.body}</p>
      <div class="trow">
        <span class="tstep">${TOUR_I + 1} / ${TOUR.length}</span>
        <button class="ghost" id="tskip">skip tour</button>
        ${TOUR_I > 0 ? '<button class="ghost" id="tback">back</button>' : ""}
        <button id="tnext">${TOUR_I === TOUR.length - 1 ? "done" : "next"}</button>
      </div>`;
    // place the card: right of the target if there's room, else below, else above
    const cw = 350, chH = 190;
    let cx = r.right + 18, cy = r.top;
    if (cx + cw > innerWidth - 12) { cx = Math.min(Math.max(12, r.left), innerWidth - cw - 12); cy = r.bottom + 14; }
    if (cy + chH > innerHeight - 12) cy = Math.max(12, r.top - chH - 14);
    card.style.left = cx + "px"; card.style.top = Math.max(12, cy) + "px";
    $("tnext").addEventListener("click", () => { TOUR_I === TOUR.length - 1 ? tourEnd() : (TOUR_I++, tourShow()); });
    $("tskip").addEventListener("click", tourEnd);
    const tb = $("tback"); if (tb) tb.addEventListener("click", () => { TOUR_I--; tourShow(); });
  }, 380);
}

function tourEnd() {
  $("tourbox").style.display = "none";
  $("tourcard").style.display = "none";
  fetch("/api/tutorial/seen", { method: "POST" }).catch(() => {});
}
window.tourStart = tourStart;

/* ======================================================================== */
/*  ADVANCED WALKTHROUGH — drives the real UI, against the real book        */
/* ======================================================================== */
/*  The first-run tour points at panels and describes them. This one uses
    them: it runs a reverse DCF on a position the user actually holds, traces
    a real route across the map, reads their own chokepoints out loud. Every
    number quoted below is scraped back out of what rendered, so the card can
    never claim something the screen isn't showing.

    Each step is skippable, the whole thing is re-runnable from learn and from
    settings, and every step has to say something sensible when the book is
    empty — a new user is exactly who this is for.                          */

const walkSleep = (ms) => new Promise(r => setTimeout(r, ms));

async function walkUntil(fn, ms = 30000) {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    try { if (fn()) return true; } catch (e) { /* not ready yet */ }
    await walkSleep(200);
  }
  return false;
}

/* Scrape the rendered panel rather than the API response: if the user cannot
   see it, the walkthrough has no business narrating it. */
const walkText = (sel) => {
  const el = document.querySelector(sel);
  return el ? el.textContent.trim() : "";
};

const WALK = [

  { title: "What the price already assumes",
    sel: '[data-panel="workbench"]',
    async run() {
      const h = HOLDINGS[0];
      // An empty book gets a named demonstration rather than SPY: an index fund
      // has no free cash flow to run backwards, so the model would just fail and
      // teach nothing. Better to show it working and say plainly it isn't theirs.
      const sym = (h && h.symbol) || "AAPL";
      MW.sym = sym;
      mwSwitch("rdcf");
      await walkUntil(() => {
        const t = walkText("#modelbody");
        return t && !t.includes("Computing");
      }, 35000);

      const g = walkText("#modelbody .h-big");
      const hist = [...document.querySelectorAll("#modelbody .kcell")]
        .find(c => (c.querySelector(".k") || {}).textContent?.includes("Actual FCF CAGR"));
      const histV = hist ? (hist.querySelector(".v") || {}).textContent : null;

      if (!g) {
        return `The reverse DCF could not price <b>${esc(sym)}</b>. It needs reported
          free cash flow, which banks, REITs, index funds and anything recently
          listed do not give up in a usable form.${h
            ? " Pick another holding from the dropdown and it will run."
            : ""}
          What the model does everywhere else is still worth knowing: it runs a
          discounted cash flow <i>backwards</i>, to find the growth rate that makes
          today's price merely fair. It is never a forecast — it is the hurdle the
          price has already set.`;
      }
      const lead = h
        ? `That is a reverse DCF on <b>${esc(sym)}</b> — your own position, not a demo ticker.`
        : `Your book is empty, so this is a demonstration on <b>${esc(sym)}</b> rather
           than anything of yours. Add a holding and start this again to point it at
           something you actually own.`;
      return `${lead}
        It reads <b>${esc(g)}</b>, and that number is the whole idea:
        it is not a forecast, and nobody here believes ${esc(sym)} will grow at that rate.
        It is the growth the current price has <i>already committed to</i> — run the
        discounted cash flow backwards and this is what has to happen for today's
        price to be merely fair.
        ${histV ? `Next to it sits <b>${esc(histV)}</b>, what the company has actually
          managed. When the implied number sits well above the actual one, the price
          is asking for an acceleration, and something has to pay for it.` : ""}
        Your job shrinks to one judgement you are qualified to make: is that hurdle
        easy or hard?`;
    } },

  { title: "Two companies, and the line between them",
    sel: '[data-panel="chain"]',
    async run() {
      const sel = $("chainnet");
      if (sel) { sel.value = "all"; sel.dispatchEvent(new Event("change")); }
      const ok = await walkUntil(() => CH.net === "all" && CH.nodes.length > 0, 40000);
      if (!ok) {
        return `The full map did not finish loading. It is the heaviest view in the
          app — every industry at once — so give it a moment and try the
          <b>all</b> entry in the dropdown yourself.`;
      }
      document.querySelector('[data-panel="chain"]')
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
      await walkSleep(600);

      const ids = new Set(CH.nodes.map(n => n.id));
      const held = HOLDINGS.map(x => x.symbol).filter(s => ids.has(s));
      let a = held[0] || "ASML", b = null, path = null;
      for (const cand of ["TSM", "ASML", "NVDA", "MSFT", "AAPL", "INTC", "CAT"]) {
        if (cand === a || !ids.has(cand)) continue;
        const p = chainFindPath(a, cand);
        if (p && p.length >= 2) { b = cand; path = p; break; }
      }
      if (!path) { a = "ASML"; b = "MSFT"; path = chainFindPath(a, b); }
      if (path) chainApplyPath(path);

      if (!path) {
        return `No route came back between two mapped companies, which usually means
          the map is still settling. The <b>⇄ path</b> button does this on demand:
          click it, then click any two companies.`;
      }
      const hops = path.length - 1;
      const mine = held.includes(a) ? ` — and <b>${esc(a)}</b> is yours` : "";
      return `The map is on <b>all</b> now: every industry at once, which is the only
        view where the lines <i>between</i> industries exist.
        The lit route is <span class="mono">${esc(path.join(" → "))}</span> —
        ${hops} ${hops === 1 ? "hop" : "hops"}${mine}.
        That is <b>⇄ path</b>, and you can run it on any two companies yourself.
        Read it as "these two are structurally connected", nothing more. The map
        records who feeds whom, hand-curated from filings and news. It carries no
        sense of how much money moves along that line, and it drifts as companies
        get acquired.`;
    } },

  { title: "What your book quietly rests on",
    sel: '[data-panel="chokepoints"]',
    async run() {
      document.querySelector('[data-panel="chokepoints"]')
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
      await loadChokepoints();
      await walkSleep(700);

      const body = walkText("#chokebody");
      if (!HOLDINGS.length) {
        return `This panel needs a book to work on, and yours is empty. It looks for
          companies that sit underneath <i>several</i> of your holdings at once —
          the concentration you did not choose and would not spot from a list of
          tickers. Add a few positions and come back.`;
      }
      if (body.includes("None of your holdings appear")) {
        return `None of your holdings are on the supply-chain map yet, so there is
          nothing to trace. The map covers ~430 companies across 26 industries;
          anything outside it is invisible here. <span class="mono">supply_chain.json</span>
          takes pull requests.`;
      }
      // The panel prints two tables: shared customers first, then shared
      // suppliers. They mean opposite things, so pick deliberately — this step
      // is about what the book depends on, which is the supplier side.
      const sect = [...document.querySelectorAll("#chokebody .cpsect")]
        .find(s => s.textContent.includes("depend on"));
      let table = sect && sect.nextElementSibling;
      let kind = "supplier";
      if (!table || !table.classList.contains("cptable")) {
        table = document.querySelector("#chokebody .cptable");
        kind = "customer";
      }
      const top = table && table.querySelector("tr");
      const who = top ? (top.querySelector(".mono") || {}).textContent : null;
      const pct = top ? (top.querySelector(".num") || {}).textContent : null;
      const meta = walkText("#cpmeta");

      if (!who || !pct) {
        return `Nothing in your book shares a supplier or a customer with anything
          else in it, within the hops the map can see. Structurally, that is what
          diversification actually looks like — and it is the one result here worth
          being pleased about. ${meta ? `<span class="mono">${esc(meta)}</span>.` : ""}`;
      }
      // Whole rows routinely tie at the same percentage — they are reached by the
      // same holdings. Calling the first one "the strongest" would invent a
      // ranking the number does not support.
      const tied = [...table.querySelectorAll("tr")]
        .filter(r => ((r.querySelector(".num") || {}).textContent || "") === pct).length;
      const noun = kind === "supplier" ? "supplier" : "customer";
      const framing = tied > 1
        ? `<b>${tied}</b> companies tie at the top of what your book ${kind === "supplier"
             ? "depends on" : "sells into"} — <b>${esc(who)}</b> among them — each sitting
           behind <b>${esc(pct)}</b> of it. They tie because the same holdings reach all
           of them, which is itself the finding: that is one dependency wearing
           ${tied} names, not ${tied} separate ones.`
        : kind === "supplier"
          ? `The strongest shared <i>supplier</i> under your book is <b>${esc(who)}</b>,
             sitting behind <b>${esc(pct)}</b> of it — concentration you did not pick
             and may not own.`
          : `Nothing in your book shares a supplier, so this is the other table: the
             strongest shared <i>${noun}</i> is <b>${esc(who)}</b>, with <b>${esc(pct)}</b>
             of your book selling into it.`;
      return `${framing}
        ${meta ? `<span class="mono">${esc(meta)}</span>.` : ""}
        Now the part that is easy to over-read, so read it twice:
        <b>this is graph structure, not revenue.</b> ${esc(pct)} is the share of your
        money sitting behind <b>${esc(who)}</b> after two discounts — one for distance,
        so a direct link counts in full and each hop further out counts half, and one
        for what the map records about the links, so a sole-source dependency backed
        by a filing counts more than one nobody has checked. It is still a hand-drawn
        map, and it still does not mean that share of your money commercially depends
        on ${esc(who)}. It is a prompt to go and check, never a finding.`;
    } },

  { title: "The field that argues with you later",
    sel: '[data-panel="journal"]',
    async run() {
      document.querySelector('[data-panel="journal"]')
        ?.scrollIntoView({ block: "center", behavior: "smooth" });
      await walkSleep(500);
      const r = $("j-reason");
      if (r) { r.focus(); r.placeholder = "why — the part you'll want in eight months"; }
      return `Last one, and it is the only part of Windrose with no maths in it.
        Every entry wants a <b>reason</b> before it will take the trade.
        That field is not for you today — today you know exactly why. It is for you
        in eight months, when the position is down and memory has quietly rewritten
        the thesis into whatever would hurt least.
        Buys get marked to market with a running hit rate, and the panel says
        plainly that a handful of calls is noise rather than skill. A journal that
        flattered you would be worse than no journal.`;
    } },
];

let WALK_I = 0;

async function walkStart() {
  tourEnd();
  if (SET.mode !== "advanced") {
    await saveSettings({ mode: "advanced" });
    loadAnalysis();
    await walkSleep(1200);
  }
  WALK_I = 0;
  walkShow();
}

async function walkShow() {
  const step = WALK[WALK_I];
  if (!step) return walkEnd();
  const card = $("tourcard"), box = $("tourbox");

  card.style.display = "block";
  card.className = "walk";
  card.innerHTML = `<h4>${esc(step.title)}</h4><p class="walkwait">Working…</p>`;

  const el = document.querySelector(step.sel);
  if (el) {
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    await walkSleep(420);
  }

  let body;
  try {
    body = await step.run();
  } catch (e) {
    body = `That step could not finish — <span class="mono">${esc(String(e && e.message || e))}</span>.
            Skip on; the rest still works.`;
  }
  if (WALK[WALK_I] !== step) return;    // user moved on while we were working

  const t = document.querySelector(step.sel);
  if (t) {
    const r = t.getBoundingClientRect();
    box.style.display = "block";
    box.style.left = (r.left - 8) + "px"; box.style.top = (r.top - 8) + "px";
    box.style.width = (r.width + 16) + "px"; box.style.height = (r.height + 16) + "px";
  } else {
    box.style.display = "none";
  }

  const last = WALK_I === WALK.length - 1;
  card.innerHTML = `
    <h4>${esc(step.title)}</h4><p>${body}</p>
    <div class="trow">
      <span class="tstep">${WALK_I + 1} / ${WALK.length}</span>
      <button class="ghost" id="wkskip">skip</button>
      ${WALK_I > 0 ? '<button class="ghost" id="wkback">back</button>' : ""}
      <button id="wknext">${last ? "done" : "next"}</button>
    </div>`;

  const cw = 430, chH = 260;
  const r2 = t ? t.getBoundingClientRect() : { right: 20, top: 90, left: 20, bottom: 300 };
  let cx = r2.right + 18, cy = r2.top;
  if (cx + cw > innerWidth - 12) { cx = Math.min(Math.max(12, r2.left), innerWidth - cw - 12); cy = r2.bottom + 14; }
  if (cy + chH > innerHeight - 12) cy = Math.max(12, innerHeight - chH - 14);
  card.style.left = cx + "px"; card.style.top = Math.max(12, cy) + "px";

  $("wknext").addEventListener("click", () => {
    if (last) return walkEnd();
    WALK_I++; walkShow();
  });
  $("wkskip").addEventListener("click", walkEnd);
  const bk = $("wkback");
  if (bk) bk.addEventListener("click", () => { WALK_I--; walkShow(); });
}

function walkEnd() {
  const card = $("tourcard");
  $("tourbox").style.display = "none";
  card.style.display = "none";
  card.className = "";
  CH.path = null; CH.pathEdges = null;
  if (typeof chainDraw === "function") chainDraw();
  fetch("/api/tutorial/seen", { method: "POST" }).catch(() => {});
}
window.walkStart = walkStart;

/* ======================================================================== */
/*  WINDROSE v4 — experience mode, personalisation, keyboard                */
/* ======================================================================== */

const SET = {
  mode: null, accent: "#e87a41", density: "comfortable", hidden: [], title: "",
};

const ACCENTS = [
  ["#e87a41", "ember"], ["#4f9ede", "signal"], ["#4fbf88", "moss"],
  ["#c77dd6", "orchid"], ["#e0b341", "brass"], ["#e0625f", "coral"],
  ["#7f8b9c", "slate"], ["#5ec5c0", "lagoon"],
];

const PANEL_LABELS = {
  holdings: "Holdings", risk: "Portfolio risk", benchmark: "vs SPY",
  chain: "Supply chain map", alerts: "Alerts", journal: "Decision journal",
  perholding: "Per-holding detail", workbench: "Workbench", sandbox: "What-if",
  chokepoints: "What your book rests on",
};

const ADV_PANELS = ["perholding", "workbench", "sandbox"];

async function checkForUpdate() {
  try {
    const d = await (await fetch("/api/update/check")).json();
    const pill = $("updpill");
    if (!pill || !d.update_available) return;
    pill.style.display = "";
    pill.href = d.url;
    pill.textContent = `↑ v${d.latest}`;
    pill.title = d.method === "git"
      ? `Version ${d.latest} is out (you have ${d.current}). Restart Windrose and it updates itself.`
      : `Version ${d.latest} is out (you have ${d.current}). Click to download the latest.`;
  } catch (e) {}
}

/* ======================================================================== */
/*  SOLO A PANEL — one panel, full window. Shrink the browser window after   */
/*  and you have a small always-visible tile to park in a corner.            */
/* ======================================================================== */

const SOLO_KEY = "windrose-solo";

function soloPanel(id) {
  const panel = document.querySelector(`[data-panel="${id}"]`);
  if (!panel) return;
  document.querySelectorAll(".panel.soloed").forEach(p => p.classList.remove("soloed"));
  panel.classList.add("soloed");
  document.body.classList.add("solo");
  const bar = $("solobar");
  if (bar) {
    bar.style.display = "";
    const label = (PANEL_LABELS && PANEL_LABELS[id]) || id;
    bar.querySelector(".solowhat").textContent = label;
  }
  try { localStorage.setItem(SOLO_KEY, id); } catch (e) {}
  window.scrollTo(0, 0);
  // canvases size themselves to their container, so nudge them after the reflow
  setTimeout(repaintPanels, 60);
}

function unsolo() {
  document.querySelectorAll(".panel.soloed").forEach(p => p.classList.remove("soloed"));
  document.body.classList.remove("solo");
  const bar = $("solobar");
  if (bar) bar.style.display = "none";
  try { localStorage.removeItem(SOLO_KEY); } catch (e) {}
  setTimeout(repaintPanels, 60);
}

function initSolo() {
  // a ⤢ on every panel header
  document.querySelectorAll(".panel[data-panel]").forEach(p => {
    const h = p.querySelector("h2");
    if (!h || h.querySelector(".solobtn")) return;
    const b = document.createElement("button");
    b.className = "solobtn";
    b.textContent = "⤢";
    b.title = "show only this panel (Esc to come back)";
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      p.classList.contains("soloed") ? unsolo() : soloPanel(p.dataset.panel);
    });
    h.appendChild(b);
  });

  const bar = $("solobar");
  if (bar) bar.querySelector(".soloback").addEventListener("click", unsolo);

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("solo")) unsolo();
  });

  // reopen where they left off — the point is parking it and leaving it
  try {
    const saved = localStorage.getItem(SOLO_KEY);
    if (saved && document.querySelector(`[data-panel="${saved}"]`)) soloPanel(saved);
  } catch (e) {}
}

async function loadSettings() {
  try {
    const s = await (await fetch("/api/settings")).json();
    Object.assign(SET, s);
  } catch (e) {}
  applySettings();
  return SET;
}

async function saveSettings(patch) {
  Object.assign(SET, patch);
  applySettings();
  try {
    await fetch("/api/settings", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
  } catch (e) {}
}

function applySettings() {
  const b = document.body;
  const wasDensity = b.dataset.density;
  document.documentElement.dataset.cbsafe = SET.cbsafe ? "1" : "0";
  b.dataset.mode = SET.mode || "advanced";
  b.dataset.density = SET.density || "comfortable";
  document.documentElement.style.setProperty("--accent", SET.accent);
  document.documentElement.style.setProperty("--accent-dim", SET.accent + "26");

  // panels the user switched off (advanced-only ones are handled by CSS)
  document.querySelectorAll(".panel[data-panel]").forEach(p => {
    p.style.display = (SET.hidden || []).includes(p.dataset.panel) ? "none" : "";
  });

  const sub = $("brandsub");
  if (sub) sub.textContent = SET.title ? SET.title : "V" + (window.APP_VERSION || "4.0");

  const pill = $("modepill");
  if (pill) {
    pill.textContent = SET.mode === "simple" ? "simple" : "advanced";
    pill.classList.toggle("simple", SET.mode === "simple");
  }
  // Sparklines and panel charts are sized in pixels, not ems, so a density
  // change has to redraw them — otherwise 11px rows sit in a 26px sparkline
  // and the row never gets shorter.
  if (wasDensity && wasDensity !== b.dataset.density) setTimeout(repaintPanels, 40);
  if (typeof chainDraw === "function" && CH && CH.nodes) chainDraw();
}

/* ---------- first run: pick how much machinery you want ------------------ */

let WIZ = { step: 1, mode: null, keys: {} };

function showWelcome() {
  WIZ = { step: 1, mode: null, keys: {} };
  $("welcome").style.display = "flex";
  wizRender();
}

function wizRender() {
  const el = $("welcome");
  const dots = [1, 2, 3, 4].map(n =>
    `<span class="wdot${n === WIZ.step ? " on" : ""}${n < WIZ.step ? " done" : ""}"></span>`).join("");

  if (WIZ.step === 1) {
    el.innerHTML = `<div class="sheet">
      <h3>Welcome to Windrose</h3>
      <p class="lede">A private investing console that runs on your own machine.
        Nothing you enter here leaves it. Four quick questions and you're set —
        every answer can be changed later.</p>
      <div class="modes">
        <div class="modecard" data-pick="simple">
          <div class="mt">Simple</div>
          <div class="md">The essentials, in plain language. Good if you're building
            a portfolio and want to understand it without a finance degree.</div>
          <ul><li>What you own and how it's doing</li>
              <li>Whether you're beating the index</li>
              <li>How concentrated you are, explained</li>
              <li>The supply-chain map, simplified</li></ul>
        </div>
        <div class="modecard" data-pick="advanced">
          <div class="mt">Advanced</div>
          <div class="md">Everything, unabridged. For people who already know what a
            drawdown is and want the assumptions exposed.</div>
          <ul><li>VaR, CVaR, beta, correlations, factors</li>
              <li>Reverse DCF, comps, LBO, M&amp;A, Monte Carlo</li>
              <li>Per-holding scoring and stress replays</li>
              <li>The full map: path tracer, ripple, labels</li></ul>
        </div>
      </div>
      <div class="wnav"><span class="wdots">${dots}</span></div>
    </div>`;
    el.querySelectorAll("[data-pick]").forEach(c =>
      c.addEventListener("click", async () => {
        WIZ.mode = c.dataset.pick;
        // Choosing Advanced on a wide monitor is itself the answer to the
        // density question, so don't ask it again — start dense. Only on first
        // run, and only above the three-column breakpoint; it stays one click
        // away in settings either way.
        const patch = { mode: WIZ.mode };
        if (WIZ.mode === "advanced" && window.innerWidth >= 1600) patch.density = "dense";
        await saveSettings(patch);
        WIZ.step = 2; wizRender();
      }));
    return;
  }

  if (WIZ.step === 2) {
    el.innerHTML = `<div class="sheet">
      <h3>Market data</h3>
      <p class="lede"><b>You don't need any keys.</b> Windrose already works —
        prices come from Yahoo, delayed about 15 minutes, and every panel
        functions. Add a free key only if you want more.</p>

      <div class="keyrow">
        <div class="keyhead"><b>Finnhub</b> — news headlines and analyst outlook
          <a href="https://finnhub.io/register" target="_blank" rel="noopener">get a free key ↗</a></div>
        <div class="keyfields">
          <input id="wz-fh" type="password" placeholder="paste your Finnhub key" spellcheck="false" autocomplete="off">
          <button class="wtest" data-test="finnhub">Test</button>
        </div>
        <div class="keyresult" id="wz-fh-r"></div>
      </div>

      <div class="keyrow">
        <div class="keyhead"><b>Alpaca</b> — live prices, about two seconds instead of fifteen minutes
          <a href="https://app.alpaca.markets" target="_blank" rel="noopener">get free paper keys ↗</a></div>
        <div class="keyfields">
          <input id="wz-ak" type="password" placeholder="API key ID" spellcheck="false" autocomplete="off">
          <input id="wz-as" type="password" placeholder="secret key" spellcheck="false" autocomplete="off">
          <button class="wtest" data-test="alpaca">Test</button>
        </div>
        <div class="keyresult" id="wz-ak-r"></div>
      </div>

      <p class="wfine">Keys are written to a file called <span class="mono">.env</span>
        beside the app, on this computer only. They are never sent anywhere except
        to the provider you got them from, and they can only be set from this machine.</p>

      <div class="wnav"><span class="wdots">${dots}</span>
        <button class="wghost" id="wz-skip">Skip — use delayed data</button>
        <button class="wnext" id="wz-next2">Continue</button></div>
    </div>`;

    el.querySelectorAll("[data-test]").forEach(b => b.addEventListener("click", async () => {
      const which = b.dataset.test;
      const out = $(which === "finnhub" ? "wz-fh-r" : "wz-ak-r");
      out.className = "keyresult testing";
      out.textContent = "checking…";
      const payload = which === "finnhub"
        ? { which, finnhub_key: $("wz-fh").value }
        : { which, alpaca_key: $("wz-ak").value, alpaca_secret: $("wz-as").value };
      try {
        const d = await (await fetch("/api/setup/testkeys", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload) })).json();
        out.className = "keyresult " + (d.ok ? "good" : "bad");
        out.textContent = (d.ok ? "\u2713 " : "\u2717 ") + (d.detail || "");
      } catch (e) {
        out.className = "keyresult bad";
        out.textContent = "\u2717 could not test right now";
      }
    }));

    const goOn = async (save) => {
      if (save) {
        const payload = {
          finnhub_key: $("wz-fh").value.trim(),
          alpaca_key: $("wz-ak").value.trim(),
          alpaca_secret: $("wz-as").value.trim(),
        };
        if (payload.finnhub_key || payload.alpaca_key) {
          try {
            await fetch("/api/setup/savekeys", { method: "POST",
              headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
          } catch (e) {}
        }
      }
      WIZ.step = 3; wizRender();
    };
    $("wz-next2").addEventListener("click", () => goOn(true));
    $("wz-skip").addEventListener("click", () => goOn(false));
    return;
  }

  if (WIZ.step === 3) {
    el.innerHTML = `<div class="sheet">
      <h3>Your portfolio</h3>
      <p class="lede">Windrose stores positions in a plain file on this computer.
        Nothing is connected to a broker, and nothing can place a trade.</p>
      <div class="modes">
        <div class="modecard" data-seed="own">
          <div class="mt">I'll add my own</div>
          <div class="md">Start empty. Add positions in the Holdings panel —
            ticker, share count, and what you paid.</div>
          <ul><li>Zero shares means watch-only</li>
              <li>An acquired date unlocks dividend-included returns</li></ul>
        </div>
        <div class="modecard" data-seed="examples">
          <div class="mt">Show me an example first</div>
          <div class="md">Five well-known companies across five sectors, so every
            panel has something to show while you look around.</div>
          <ul><li>Delete any row with the ✕</li>
              <li>Not recommendations — just furniture</li></ul>
        </div>
      </div>
      <div class="wnav"><span class="wdots">${dots}</span></div>
    </div>`;
    el.querySelectorAll("[data-seed]").forEach(c => c.addEventListener("click", async () => {
      try {
        await fetch("/api/setup/seed", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ examples: c.dataset.seed === "examples" }) });
      } catch (e) {}
      WIZ.step = 4; wizRender();
    }));
    return;
  }

  // step 4
  el.innerHTML = `<div class="sheet">
    <h3>You're set</h3>
    <p class="lede">Two things worth knowing before you start.</p>
    <ul class="wlist">
      <li><b>Alerts only fire while Windrose is running.</b> Close it and nothing is
        watching. Use <span class="mono">Run at Login</span> in the app folder to keep it up.</li>
      <li><b>Nothing here is advice.</b> Every model is an assumption engine — change
        an input and the answer changes. The numbers come from free public sources
        that are sometimes delayed or wrong.</li>
    </ul>
    <p class="lede">A short guided tour starts when you close this. The full written
      walkthrough lives behind <b>learn</b> in the top bar, and <b>?</b> shows the
      keyboard shortcuts.</p>
    <div class="wnav"><span class="wdots">${dots}</span>
      <button class="wnext" id="wz-done">Open the dashboard</button></div>
  </div>`;
  $("wz-done").addEventListener("click", async () => {
    $("welcome").style.display = "none";
    await loadHoldings();
    loadAnalysis(); loadSpark(); loadBenchmark(); loadChokepoints();
    pollStatus();
    setTimeout(tourStart, 600);
  });
}

function showSettings() {
  const el = $("settings");
  const panels = Object.keys(PANEL_LABELS);
  el.innerHTML = `
    <div class="sheet" style="position:relative">
      <span class="close" id="setclose">×</span>
      <h3>Settings</h3>
      <p class="lede">All of this is stored on this machine, in settings.json.</p>

      <div class="setrow col">
        <div class="lab"><b>Layout presets</b>
          <span>A starting arrangement for what you're doing right now. You can
                still drag panels afterwards.</span></div>
        <div class="presets">
          ${Object.entries(PRESETS).map(([k, p]) => `
            <button class="presetcard${SET.preset === k ? " on" : ""}" data-preset="${k}">
              <span class="pt">${p.label}</span>
              <span class="pb">${p.blurb}</span>
            </button>`).join("")}
        </div>
      </div>

      <div class="setrow">
        <div class="lab"><b>Colour-blind safe</b>
          <span>Gains and losses in blue and orange instead of green and red.
                Around one man in twelve cannot separate red from green reliably,
                and here that pairing carries the meaning.</span></div>
        <div class="seg" id="setcb">
          <button data-cb="0" class="${SET.cbsafe ? "" : "on"}">Green / red</button>
          <button data-cb="1" class="${SET.cbsafe ? "on" : ""}">Blue / orange</button>
        </div>
      </div>

      <div class="setrow">
        <div class="lab"><b>Something wrong?</b>
          <span>Opens a GitHub issue with your version and platform filled in —
                never your holdings, keys or notes.</span></div>
        <button class="segbtn" id="setreport">Report a problem</button>
      </div>

      <div class="setrow">
        <div class="lab"><b>Experience</b>
          <span>Simple keeps the essentials. Advanced shows every tool.</span></div>
        <div class="seg" id="setmode">
          <button data-m="simple">Simple</button>
          <button data-m="advanced">Advanced</button>
        </div>
      </div>

      <div class="setrow">
        <div class="lab"><b>Accent colour</b><span>Used for highlights and your holdings on the map.</span></div>
        <div class="swatches" id="setaccent">
          ${ACCENTS.map(([hex, name]) =>
            `<div class="sw" data-hex="${hex}" title="${name}" style="background:${hex}"></div>`).join("")}
        </div>
      </div>

      <div class="setrow">
        <div class="lab"><b>Density</b>
          <span>Compact fits more on screen. Dense fits a great deal more —
                11px rows, mono figures, almost no padding. It is meant for a
                large monitor; on a laptop it will feel tight.</span></div>
        <div class="seg" id="setdens">
          <button data-d="comfortable">Comfortable</button>
          <button data-d="compact">Compact</button>
          <button data-d="dense">Dense</button>
        </div>
      </div>

      <div class="setrow">
        <div class="lab"><b>Dashboard name</b><span>Shown in the top bar. Leave empty for the version.</span></div>
        <input type="text" id="settitle" maxlength="24" placeholder="e.g. The Long Game" value="${(SET.title || "").replace(/"/g, "&quot;")}">
      </div>

      <div class="setrow" style="display:block">
        <div class="lab" style="margin-bottom:10px"><b>Panels</b>
          <span>Uncheck anything you don't want to see. Greyed-out ones only appear in Advanced.</span></div>
        <div class="panelchecks" id="setpanels">
          ${panels.map(p => {
            const advOnly = ADV_PANELS.includes(p);
            const off = (SET.hidden || []).includes(p);
            const dim = advOnly && SET.mode === "simple";
            return `<label style="${dim ? "opacity:.45" : ""}">
              <input type="checkbox" data-panel-toggle="${p}" ${off ? "" : "checked"}>
              ${PANEL_LABELS[p]}${advOnly ? " <span style='color:var(--text-dim);font-size:11px'>· adv</span>" : ""}
            </label>`;
          }).join("")}
        </div>
      </div>

      <div class="setrow">
        <div class="lab"><b>Keyboard shortcuts</b><span>Press <span class="kbd">?</span> any time.</span></div>
        <button class="anlz" id="setshortcuts">View</button>
      </div>

      <div class="setrow">
        <div class="lab"><b>Replay the tour</b><span>The guided walkthrough of every panel.</span></div>
        <button class="anlz" id="setretour">Start</button>
      </div>

      <div class="setrow">
        <div class="lab"><b>Advanced walkthrough</b>
          <span>The longer one. Runs the models on your own book rather than
                describing them — reverse DCF, a traced route across the map,
                your chokepoints. Skippable at any step.</span></div>
        <button class="anlz" id="setwalk">Start</button>
      </div>
    </div>`;
  el.style.display = "flex";

  const mark = () => {
    el.querySelectorAll("#setmode button").forEach(b =>
      b.classList.toggle("on", b.dataset.m === (SET.mode || "advanced")));
    el.querySelectorAll("#setdens button").forEach(b =>
      b.classList.toggle("on", b.dataset.d === (SET.density || "comfortable")));
    el.querySelectorAll(".sw").forEach(s =>
      s.classList.toggle("on", s.dataset.hex === SET.accent));
  };
  mark();

  el.querySelectorAll("#setmode button").forEach(b => b.addEventListener("click", async () => {
    await saveSettings({ mode: b.dataset.m });
    mark(); showSettings(); loadAnalysis();
  }));
  el.querySelectorAll("#setdens button").forEach(b => b.addEventListener("click", async () => {
    await saveSettings({ density: b.dataset.d }); mark();
  }));
  el.querySelectorAll(".sw").forEach(s => s.addEventListener("click", async () => {
    await saveSettings({ accent: s.dataset.hex }); mark(); drawSparklines(); drawCharts();
  }));
  $("settitle").addEventListener("change", e => saveSettings({ title: e.target.value.trim() }));
  el.querySelectorAll("[data-panel-toggle]").forEach(cb => cb.addEventListener("change", () => {
    const p = cb.dataset.panelToggle;
    const hidden = new Set(SET.hidden || []);
    cb.checked ? hidden.delete(p) : hidden.add(p);
    saveSettings({ hidden: [...hidden] });
  }));
  el.querySelectorAll("[data-preset]").forEach(b =>
    b.addEventListener("click", () => applyPreset(b.dataset.preset)));
  el.querySelectorAll("[data-cb]").forEach(b =>
    b.addEventListener("click", async () => {
      SET.cbsafe = b.dataset.cb === "1";
      await saveSettings({ cbsafe: SET.cbsafe });
      applySettings();
      showSettings();
      drawSparklines(); drawCharts();
    }));
  const rep = $("setreport");
  if (rep) rep.addEventListener("click", reportProblem);
  $("setclose").addEventListener("click", () => { el.style.display = "none"; });
  el.addEventListener("click", e => { if (e.target === el) el.style.display = "none"; });
  $("setshortcuts").addEventListener("click", () => { el.style.display = "none"; showShortcuts(); });
  $("setretour").addEventListener("click", () => { el.style.display = "none"; tourStart(); });
  $("setwalk").addEventListener("click", () => { el.style.display = "none"; walkStart(); });

}

/* ---------- keyboard ------------------------------------------------------ */

const SHORTCUTS = [
  ["?", "this list"],
  ["s", "switch Simple / Advanced"],
  [",", "settings"],
  ["/", "search the supply-chain map"],
  ["g then h", "go to Holdings"],
  ["g then r", "go to Portfolio risk"],
  ["g then m", "go to the map"],
  ["g then w", "go to the Workbench"],
  ["Esc", "close anything open"],
];

function showShortcuts() {
  const el = $("shortcuts");
  el.innerHTML = `
    <div class="sheet" style="position:relative;width:min(430px,94vw)">
      <span class="close" id="scclose">×</span>
      <h3>Keyboard</h3>
      <div class="sclist">
        ${SHORTCUTS.map(([k, d]) => `<span class="kbd">${k}</span><span>${d}</span>`).join("")}
      </div>
    </div>`;
  el.style.display = "flex";
  $("scclose").addEventListener("click", () => { el.style.display = "none"; });
  el.addEventListener("click", e => { if (e.target === el) el.style.display = "none"; });
}

function initKeyboard() {
  let awaitingGo = false;
  document.addEventListener("keydown", (e) => {
    const t = e.target;
    if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA")) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;

    if (e.key === "Escape") {
      ["welcome", "settings", "shortcuts"].forEach(id => {
        const el = $(id);
        if (el && id !== "welcome") el.style.display = "none";
      });
      hideChainCard && hideChainCard();
      return;
    }
    if (awaitingGo) {
      const map = { h: "holdings", r: "risk", m: "chain", w: "workbench", j: "journal", a: "alerts" };
      const panel = map[e.key.toLowerCase()];
      awaitingGo = false;
      if (panel) {
        const p = document.querySelector(`[data-panel="${panel}"]`);
        if (p && p.style.display !== "none") {
          const head = document.querySelector(".stickyhead");
          const off = (head ? head.getBoundingClientRect().height : 0) + 10;
          window.scrollTo({ top: p.getBoundingClientRect().top + window.pageYOffset - off, behavior: "smooth" });
          p.classList.add("flash");
          setTimeout(() => p.classList.remove("flash"), 1200);
        }
      }
      return;
    }
    switch (e.key) {
      case "?": showShortcuts(); break;
      case ",": showSettings(); break;
      case "g": awaitingGo = true; setTimeout(() => { awaitingGo = false; }, 1400); break;
      case "s":
        saveSettings({ mode: SET.mode === "simple" ? "advanced" : "simple" }).then(loadAnalysis);
        break;
      case "/": {
        const cs = $("chainsearch");
        if (cs) {
          e.preventDefault();
          document.querySelector('[data-panel="chain"]').scrollIntoView({ behavior: "smooth", block: "center" });
          setTimeout(() => cs.focus(), 400);
        }
        break;
      }
    }
  });
}

function initChrome() {
  const sb = $("settingsbtn");
  if (sb) sb.addEventListener("click", showSettings);
  const pill = $("modepill");
  if (pill) pill.addEventListener("click", () =>
    saveSettings({ mode: SET.mode === "simple" ? "advanced" : "simple" }).then(loadAnalysis));
  initKeyboard();
}
