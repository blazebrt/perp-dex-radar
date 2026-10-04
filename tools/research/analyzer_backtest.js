/* Walk-forward test of the coin analyzer (analyze.js) on the market-data branch's hourly candles.

     node tools/research/analyzer_backtest.js <market-data folder with h1/> [1h|4h]

   At every step (every 2 hours on the 1-hour chart, every 4-hour bar on the 4-hour chart) the analyzer sees only
   the candles known at that moment: the 4-hour and daily context are built from the hourly candles, including the
   unfinished current bar, as on the live page. When it calls LONG or SHORT, its plan is traded as the page says:
   market, limit (12 bars to fill) or stop order; a third off at T1 with the stop moved to the entry, a third at T2,
   the rest at T3; out if T1 is not reached within the time stop; when a candle touches the stop and a target, the
   stop counts first. Costs 0.06% per side. One trade at a time per coin. Prints the average result per trade in R
   (multiples of the risk) and in percent, by side, setup and agreement. Results of the October 2026 run are in
   README.md (Coin analyzer). */
"use strict";
const path = require("path");
const fs = require("fs"), zlib = require("zlib");
const TA = require(path.join(__dirname, "..", "..", "analyze.js"));
const MD = process.argv[2], TF = process.argv[3] || "1h";
if (!MD) { console.error("usage: node analyzer_backtest.js <market-data folder> [1h|4h]"); process.exit(1); }
const COST = 0.0006, H = 3600, STEP_1H = 2;
const HOLD = {"1h": 24, "4h": 30}[TF], MAXB = {"1h": 96, "4h": 90}[TF];

function load(file) {
  const rows = zlib.gunzipSync(fs.readFileSync(file)).toString().trim().split("\n");
  return rows.slice(1).map((r) => { const a = r.split(","); return {t: +a[0], o: +a[1], h: +a[2], l: +a[3], c: +a[4], v: +a[5]}; })
    .filter((b) => isFinite(b.c) && b.c > 0);
}
function bucketize(h1, sec) {
  const out = [];
  for (let i = 0; i < h1.length; i++) {
    const b = h1[i], s = Math.floor(b.t / sec) * sec, z = out[out.length - 1];
    if (z && z.t === s) { z.h = Math.max(z.h, b.h); z.l = Math.min(z.l, b.l); z.c = b.c; z.v += b.v; z.end = i; }
    else out.push({t: s, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v, start: i, end: i});
  }
  out.sec = sec;
  return out;
}
/* bars of `buckets` known at the close of hourly bar i: the finished ones plus the unfinished current one */
function known(buckets, h1, i, k, keep) {
  const cur = Math.floor(h1[i].t / buckets.sec) * buckets.sec;
  while (k.p < buckets.length - 1 && buckets[k.p + 1].t <= cur) k.p++;
  const b = buckets[k.p], part = {t: b.t, o: b.o, h: -Infinity, l: Infinity, c: h1[i].c, v: 0};
  for (let j = b.start; j <= i; j++) { part.h = Math.max(part.h, h1[j].h); part.l = Math.min(part.l, h1[j].l); part.v += h1[j].v; }
  const done = buckets.slice(Math.max(0, k.p - keep), k.p);
  done.push(part);
  return done;
}
function simulate(bars, i, p) {
  const L = p.side === "long", d = L ? 1 : -1, wait = p.order === "market" ? 1 : 12;
  let f = -1, fill = null;
  for (let j = i + 1; j <= Math.min(bars.length - 1, i + wait); j++) {
    const b = bars[j];
    if (p.order === "market") { f = j; fill = b.o; break; }
    if (p.order === "limit") { if (L ? b.l <= p.entry : b.h >= p.entry) { f = j; fill = L ? Math.min(b.o, p.entry) : Math.max(b.o, p.entry); break; } }
    else if (L ? b.h >= p.entry : b.l <= p.entry) { f = j; fill = L ? Math.max(b.o, p.entry) : Math.min(b.o, p.entry); break; }
    if (L ? b.l <= p.stop : b.h >= p.stop) break;   // proven wrong before the entry: cancel the order
  }
  if (f < 0) return {filled: false, end: Math.min(bars.length - 1, i + wait)};
  const risk = Math.abs(fill - p.stop);
  if (!(risk > 0) || (L ? fill <= p.stop : fill >= p.stop)) return {filled: false, end: f};
  const T = p.targets.map((t) => t.price);
  let stop = p.stop, rem = 1, pnl = 0, t1 = false, t2 = false, j = f;
  for (; j < Math.min(bars.length, f + MAXB); j++) {
    const b = bars[j];
    if (L ? b.l <= stop : b.h >= stop) { const px = j === f ? stop : (L ? Math.min(b.o, stop) : Math.max(b.o, stop)); pnl += rem * d * (px - fill); rem = 0; break; }
    if (j === f && p.order !== "market") continue;   // the order inside the fill candle is unknown: no targets on it
    if (!t1 && (L ? b.h >= T[0] : b.l <= T[0])) { pnl += d * (T[0] - fill) / 3; rem -= 1 / 3; t1 = true; stop = fill; }
    if (t1 && !t2 && (L ? b.h >= T[1] : b.l <= T[1])) { pnl += d * (T[1] - fill) / 3; rem -= 1 / 3; t2 = true; }
    if (t2 && (L ? b.h >= T[2] : b.l <= T[2])) { pnl += rem * d * (T[2] - fill); rem = 0; break; }
    if (!t1 && j - f + 1 >= HOLD) { pnl += rem * d * (b.c - fill); rem = 0; break; }
  }
  if (rem > 0) pnl += rem * d * (bars[Math.min(bars.length - 1, j)].c - fill);
  const net = pnl - 2 * COST * fill;
  return {filled: true, R: net / risk, ret: net / fill, gross: pnl / fill, t1, end: Math.min(bars.length - 1, j)};
}

const dir = path.join(MD, "h1");
const trades = [];
for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".csv.gz")).sort()) {
  const coin = file.replace(".csv.gz", ""), h1 = load(path.join(dir, file));
  if (h1.length < 1500) continue;
  const b4 = bucketize(h1, 4 * H), bd = bucketize(h1, 24 * H), k4 = {p: 0}, kd = {p: 0};
  const take = (bars, i, a, t) => {
    const r = simulate(bars, i, a.plans[0]);
    if (r.filled) trades.push({coin, t, side: a.side, conf: a.confidence, type: a.plans[0].type, R: r.R, ret: r.ret, gross: r.gross, t1: r.t1});
    return r.end;
  };
  if (TF === "1h") {
    let next = 700;
    for (let i = 700; i < h1.length - 2; i += STEP_1H) {
      const h4 = known(b4, h1, i, k4, 299), d1 = known(bd, h1, i, kd, 299);
      if (i < next) continue;
      let a;
      try { a = TA.analyze({coin, tf: "1h", main: h1.slice(i - 499, i + 1), h4, d1, deriv: {}, account: 1000, risk: 0.01}); } catch (e) { continue; }
      if (a.side) next = take(h1, i, a, h1[i].t) + 1;
    }
  } else {
    let next = 0;
    for (let q = 400; q < b4.length - 2; q++) {
      const i = b4[q].end;
      if (h1[i].t !== b4[q].t + 3 * H) continue;   // the 4-hour bar is complete
      const d1 = known(bd, h1, i, kd, 299);
      if (q < next) continue;
      const main = b4.slice(Math.max(0, q - 499), q + 1).map((b) => ({t: b.t, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v}));
      let a;
      try { a = TA.analyze({coin, tf: "4h", main, h4: main, d1, deriv: {}, account: 1000, risk: 0.01}); } catch (e) { continue; }
      if (a.side) next = take(b4, q, a, b4[q].t) + 1;
    }
  }
}
const avg = (xs) => xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length);
const line = (name, xs) => console.log(name.padEnd(34) + " trades " + String(xs.length).padStart(6) + "   R " + (avg(xs.map((x) => x.R)) >= 0 ? "+" : "") + avg(xs.map((x) => x.R)).toFixed(3) +
  "   per trade " + (avg(xs.map((x) => x.ret)) * 100).toFixed(3) + "% (before costs " + (avg(xs.map((x) => x.gross)) * 100).toFixed(3) + "%)   winners " + Math.round(avg(xs.map((x) => (x.R > 0 ? 1 : 0))) * 100) + "%");
console.log(TF + " chart, " + new Set(trades.map((x) => x.coin)).size + " coins, " +
  new Date(Math.min(...trades.map((x) => x.t)) * 1000).toISOString().slice(0, 10) + " to " + new Date(Math.max(...trades.map((x) => x.t)) * 1000).toISOString().slice(0, 10));
line("all", trades);
for (const s of ["long", "short"]) line("  " + s, trades.filter((x) => x.side === s));
for (const [lo, hi] of [[0, 40], [40, 60], [60, 101]]) line("  agreement " + lo + "-" + (hi - 1), trades.filter((x) => x.conf >= lo && x.conf < hi));
const types = [...new Set(trades.map((x) => x.type))].sort();
for (const t of types) { const g = trades.filter((x) => x.type === t); if (g.length >= 100) line("  " + t, g); }
const mid = trades.map((x) => x.t).sort((a, b) => a - b)[Math.floor(trades.length / 2)];
line("  first half", trades.filter((x) => x.t < mid));
line("  second half", trades.filter((x) => x.t >= mid));
