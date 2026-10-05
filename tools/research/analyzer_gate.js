/* The coin analyzer's chart read at the moment of every tested signal, for analyzer_gate.py.

     node tools/research/analyzer_gate.js <market-data folder> <signals.json> <out.json>

   signals.json: [{coin, t, side}], t = the start (00:00 UTC) of the day the signal was given; the trade enters at
   the next daily open. The analyzer sees only what was known at that day's close: the 4-hour candles of that day
   and before, and daily candles built from them. It is run as the page runs it (on the 4-hour and the daily
   chart), without the tested score, sentiment or market mood, so only the chart read itself is measured.
   Writes [{i, h4: {side, bias}, d1: {side, bias}}] in the order of the signals. */
"use strict";
const path = require("path");
const fs = require("fs"), zlib = require("zlib");
const TA = require(path.join(__dirname, "..", "..", "analyze.js"));
const [MD, SIG, OUT] = process.argv.slice(2);
if (!MD || !SIG || !OUT) { console.error("usage: node analyzer_gate.js <market-data> <signals.json> <out.json>"); process.exit(1); }
const DAY = 86400;

function load(file) {
  const rows = zlib.gunzipSync(fs.readFileSync(file)).toString().trim().split("\n");
  return rows.slice(1).map((r) => { const a = r.split(","); return {t: +a[0], o: +a[1], h: +a[2], l: +a[3], c: +a[4], v: +a[5]}; })
    .filter((b) => isFinite(b.c) && b.c > 0);
}
function daily(bars) {
  const out = [];
  for (const b of bars) {
    const s = Math.floor(b.t / DAY) * DAY, z = out[out.length - 1];
    if (z && z.t === s) { z.h = Math.max(z.h, b.h); z.l = Math.min(z.l, b.l); z.c = b.c; z.v += b.v; z.n++; }
    else out.push({t: s, o: b.o, h: b.h, l: b.l, c: b.c, v: b.v, n: 1});
  }
  return out;
}
function upto(arr, tEnd) {            // index after the last bar with t < tEnd (binary search)
  let lo = 0, hi = arr.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (arr[m].t < tEnd) lo = m + 1; else hi = m; }
  return lo;
}
function read(res) {
  return {side: res.side || null, bias: res.bias, parts: res.parts.map((p) => [p.name, p.pts])};
}

const sigs = JSON.parse(fs.readFileSync(SIG, "utf8"));
const byCoin = new Map();
sigs.forEach((s, i) => { if (!byCoin.has(s.coin)) byCoin.set(s.coin, []); byCoin.get(s.coin).push(i); });
const out = new Array(sigs.length).fill(null);
let done = 0, failed = 0;
for (const [coin, idx] of byCoin) {
  const file = path.join(MD, "h4", coin + ".csv.gz");
  if (!fs.existsSync(file)) { failed += idx.length; continue; }
  const h4 = load(file), d1 = daily(h4).filter((d) => d.n === 6);
  for (const i of idx) {
    const s = sigs[i], tEnd = s.t + DAY;
    const a = upto(h4, tEnd), b = upto(d1, tEnd);
    const main = h4.slice(Math.max(0, a - 500), a), dd = d1.slice(Math.max(0, b - 400), b);
    const r = {i};
    try { r.h4 = read(TA.analyze({coin, tf: "4h", main, h4: main, d1: dd})); } catch (e) { r.h4 = null; }
    try { r.d1 = dd.length >= 130 ? read(TA.analyze({coin, tf: "1d", main: dd, h4: main, d1: dd})) : null; } catch (e) { r.d1 = null; }
    out[i] = r;
    done++;
  }
}
fs.writeFileSync(OUT, JSON.stringify(out));
console.error(`chart reads: ${done} signals, ${failed} without candles`);
