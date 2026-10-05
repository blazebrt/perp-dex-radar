/* Coin analyzer engine: reads candles (any timeframe, plus 4h and daily context) and returns the market
   structure, support and resistance zones, momentum, a long / short / wait verdict and a trade plan with entry,
   stop and three targets, written out in plain words. Pure functions, no page code, so the same file runs in the
   browser (window.TA) and in tests (node). The loader at the end fetches candles from public exchange APIs.
   Educational tool, not financial advice. */
(function (root) {
  "use strict";

  // ------------------------------------------------------------------ indicators
  function ema(xs, n) {
    const k = 2 / (n + 1), out = new Array(xs.length).fill(null);
    let y = null, cnt = 0;
    for (let i = 0; i < xs.length; i++) {
      const x = xs[i];
      if (x == null || !isFinite(x)) { out[i] = cnt >= n ? y : null; continue; }
      y = y == null ? x : y + k * (x - y);
      cnt++;
      out[i] = cnt >= n ? y : null;
    }
    return out;
  }
  function wilder(xs, n) {
    const out = new Array(xs.length).fill(null);
    let y = null, cnt = 0;
    for (let i = 0; i < xs.length; i++) {
      const x = xs[i];
      if (x == null || !isFinite(x)) { out[i] = cnt >= n ? y : null; continue; }
      y = y == null ? x : y + (x - y) / n;
      cnt++;
      out[i] = cnt >= n ? y : null;
    }
    return out;
  }
  function rsi(c, n) {
    n = n || 14;
    const up = [null], dn = [null];
    for (let i = 1; i < c.length; i++) {
      const d = c[i] - c[i - 1];
      up.push(d > 0 ? d : 0);
      dn.push(d < 0 ? -d : 0);
    }
    const au = wilder(up, n), ad = wilder(dn, n);
    return au.map((a, i) => (a == null || ad[i] == null) ? null : ad[i] === 0 ? (a > 0 ? 100 : 50) : 100 - 100 / (1 + a / ad[i]));
  }
  function atr(h, l, c, n) {
    n = n || 14;
    const tr = c.map((_, i) => i === 0 ? h[0] - l[0] : Math.max(h[i] - l[i], Math.abs(h[i] - c[i - 1]), Math.abs(l[i] - c[i - 1])));
    return wilder(tr, n);
  }
  function macd(c) {
    const e12 = ema(c, 12), e26 = ema(c, 26);
    const line = c.map((_, i) => (e12[i] == null || e26[i] == null) ? null : e12[i] - e26[i]);
    const sig = ema(line, 9);
    return {line, signal: sig, hist: line.map((x, i) => (x == null || sig[i] == null) ? null : x - sig[i])};
  }
  function bbWidth(c, n) {
    n = n || 20;
    return c.map((_, i) => {
      if (i < n - 1) return null;
      const w = c.slice(i - n + 1, i + 1), m = w.reduce((a, b) => a + b, 0) / n;
      const sd = Math.sqrt(w.reduce((a, b) => a + (b - m) * (b - m), 0) / (n - 1));
      return m ? 4 * sd / m : null;
    });
  }
  function pctRankLast(xs, n) {
    const w = xs.slice(-n).filter((x) => x != null);
    const x = xs[xs.length - 1];
    if (x == null || w.length < 20) return null;
    const below = w.filter((v) => v < x).length, same = w.filter((v) => v === x).length;
    return (below + (same + 1) / 2) / w.length;
  }
  const last = (a) => a[a.length - 1];
  const lastVal = (a) => { for (let i = a.length - 1; i >= 0; i--) if (a[i] != null) return a[i]; return null; };
  const sum = (a) => a.reduce((x, y) => x + y, 0);

  // ------------------------------------------------------------------ swings, structure, levels
  function pivots(h, l, k, from) {
    const out = [];
    for (let i = Math.max(k, from || 0); i < h.length - k; i++) {
      let isH = true, isL = true;
      for (let j = i - k; j <= i + k; j++) {
        if (j === i) continue;
        if (h[j] >= h[i]) isH = false;
        if (l[j] <= l[i]) isL = false;
      }
      if (isH) out.push({i, price: h[i], type: "H"});
      if (isL) out.push({i, price: l[i], type: "L"});
    }
    return out;
  }
  function structure(piv, close) {
    const H = piv.filter((p) => p.type === "H"), L = piv.filter((p) => p.type === "L");
    const h1 = H[H.length - 1], h0 = H[H.length - 2], l1 = L[L.length - 1], l0 = L[L.length - 2];
    let trend = "range";
    if (h0 && h1 && l0 && l1) {
      if (h1.price > h0.price && l1.price > l0.price) trend = "up";
      else if (h1.price < h0.price && l1.price < l0.price) trend = "down";
    }
    let bos = null;
    if (h1 && close > h1.price) bos = "up";
    else if (l1 && close < l1.price) bos = "down";
    return {trend, bos, lastHigh: h1 || null, lastLow: l1 || null, prevHigh: h0 || null, prevLow: l0 || null};
  }
  function trendOf(c, fast, slow, piv) {
    const ef = lastVal(ema(c, fast)), es = lastVal(ema(c, slow)), px = last(c);
    const st = structure(piv, px);
    let score = 0;
    if (ef != null && es != null) score += ef > es ? 1 : -1;
    if (es != null) score += px > es ? 1 : -1;
    score += st.trend === "up" ? 1 : st.trend === "down" ? -1 : 0;
    return {dir: score >= 2 ? "up" : score <= -2 ? "down" : "mixed", score, emaFast: ef, emaSlow: es, structure: st};
  }
  function volumeProfile(bars, nb) {
    nb = nb || 48;
    const lo = Math.min(...bars.map((b) => b.l)), hi = Math.max(...bars.map((b) => b.h));
    if (!(hi > lo)) return null;
    const step = (hi - lo) / nb, vol = new Array(nb).fill(0);
    for (const b of bars) {
      const a = Math.max(0, Math.floor((b.l - lo) / step)), z = Math.min(nb - 1, Math.floor((b.h - lo) / step));
      const share = b.v / (z - a + 1);
      for (let i = a; i <= z; i++) vol[i] += share;
    }
    let poc = 0;
    for (let i = 1; i < nb; i++) if (vol[i] > vol[poc]) poc = i;
    const total = sum(vol);
    let a = poc, z = poc, acc = vol[poc];
    while (acc < 0.7 * total && (a > 0 || z < nb - 1)) {
      const va = a > 0 ? vol[a - 1] : -1, vz = z < nb - 1 ? vol[z + 1] : -1;
      if (vz >= va) { z++; acc += vz; } else { a--; acc += va; }
    }
    return {poc: lo + (poc + 0.5) * step, vah: lo + (z + 1) * step, val: lo + a * step};
  }
  function buildZones(levels, tol, maxWidth) {
    const lv = levels.slice().sort((x, y) => x.price - y.price), out = [];
    const cap = maxWidth || 2 * tol;
    for (const p of lv) {
      const z = out[out.length - 1];
      if (z && p.price - z.hi <= tol && p.price - z.lo <= cap) {
        z.hi = Math.max(z.hi, p.price);
        z.lo = Math.min(z.lo, p.price);
        z.w += p.w;
        z.n += 1;
        z.src.add(p.src);
      } else {
        out.push({lo: p.price, hi: p.price, w: p.w, n: 1, src: new Set([p.src])});
      }
    }
    for (const z of out) {
      z.mid = (z.lo + z.hi) / 2;
      z.src = Array.from(z.src);
    }
    return out;
  }
  /* Higher-high / lower-low labels for the swing points (HH, HL, LH, LL). */
  function swingLabels(piv) {
    const out = [];
    let pH = null, pL = null;
    for (const p of piv) {
      if (p.type === "H") { if (pH) out.push({i: p.i, price: p.price, type: "H", label: p.price > pH.price ? "HH" : "LH"}); pH = p; }
      else { if (pL) out.push({i: p.i, price: p.price, type: "L", label: p.price > pL.price ? "HL" : "LL"}); pL = p; }
    }
    return out;
  }

  // ------------------------------------------------------------------ helpers for words
  function fmtPrice(x) {
    if (x == null || !isFinite(x)) return "–";
    const a = Math.abs(x);
    // five significant digits below 1 (0.58291, 0.0042866, 0.000004279), fewer decimals for big prices
    const d = a >= 1000 ? 1 : a >= 100 ? 2 : a >= 1 ? 4 : a > 0 ? Math.min(12, Math.ceil(-Math.log10(a)) + 4) : 2;
    return Number(x).toFixed(d).replace(/(\.\d*?[1-9])0+$/, "$1").replace(/\.0+$/, "");
  }
  const pctTxt = (x, d) => (x >= 0 ? "+" : "") + (x * 100).toFixed(d == null ? 1 : d) + "%";
  const TF_LABEL = {"15m": "15-minute", "1h": "1-hour", "4h": "4-hour", "1d": "daily"};
  const TF_HOURS = {"15m": 0.25, "1h": 1, "4h": 4, "1d": 24};
  const TF_SEC = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400};
  function durTxt(hours) {
    if (hours < 1.5) return Math.round(hours * 60) + " minutes";
    if (hours < 48) return Math.round(hours) + " hours";
    return Math.round(hours / 24) + " days";
  }

  // ------------------------------------------------------------------ the analysis
  /* input: {coin, tf, main: [{t,o,h,l,c,v}], h4: [...], d1: [...],
             deriv: {funding, oiChange24h, topLong, crowdLong, source},
             picks: {side, score, core, label, sentiment} | null   (the tested swing score from the scan),
             sentiment: {score, label, ...} | null                 (overrides picks.sentiment),
             market: {mood, fng: {value, label}} | null            (from the scan),
             account, risk,
             lean: true                                            (word the read as context, without a trade)} */
  function analyze(inp) {
    const tf = inp.tf || "1h", bars = inp.main, n = bars ? bars.length : 0;
    if (!bars || n < 120) throw new Error("not enough candles for the " + (TF_LABEL[tf] || tf) + " chart (" + n + ")");
    const h = bars.map((b) => b.h), l = bars.map((b) => b.l), c = bars.map((b) => b.c), v = bars.map((b) => b.v);
    const px = last(c), A = lastVal(atr(h, l, c, 14)) || px * 0.01;
    const perDay = Math.max(1, Math.round(24 / (TF_HOURS[tf] || 1)));
    const T = TF_LABEL[tf] || tf, coin = inp.coin || "This coin";
    const e20 = ema(c, 20), e50 = ema(c, 50), e200 = ema(c, 200);
    const R = rsi(c, 14), M = macd(c);
    const k = tf === "1d" ? 2 : 3;
    const piv = pivots(h, l, k, Math.max(0, n - 300));
    const st = structure(piv, px);
    // context timeframes
    const h4 = inp.h4 && inp.h4.length > 60 ? inp.h4 : null, d1 = inp.d1 && inp.d1.length > 60 ? inp.d1 : null;
    const piv4 = h4 ? pivots(h4.map((b) => b.h), h4.map((b) => b.l), 2, Math.max(0, h4.length - 200)) : [];
    const pivD = d1 ? pivots(d1.map((b) => b.h), d1.map((b) => b.l), 2, Math.max(0, d1.length - 150)) : [];
    const ctx4 = h4 ? trendOf(h4.map((b) => b.c), 20, 50, piv4) : null;
    const ctxD = d1 ? trendOf(d1.map((b) => b.c), 50, 200, pivD) : null;
    const A4 = (h4 && lastVal(atr(h4.map((b) => b.h), h4.map((b) => b.l), h4.map((b) => b.c), 14))) || A * 2;
    // levels: swing points of every timeframe, the volume profile, yesterday's and last week's range
    const levels = [];
    for (const p of piv) levels.push({price: p.price, w: 1 + (p.i > n - 100 ? 0.5 : 0), src: T + " swing"});
    for (const p of piv4) levels.push({price: p.price, w: 2, src: "4-hour swing"});
    for (const p of pivD) levels.push({price: p.price, w: 3, src: "daily swing"});
    const vpBars = Math.min(n, Math.max(perDay * 10, 60));
    const vp = volumeProfile(bars.slice(-vpBars));
    if (vp) levels.push({price: vp.poc, w: 2, src: "volume peak"});
    if (d1 && d1.length > 2) {
      const y = d1[d1.length - 2];
      levels.push({price: y.h, w: 1.5, src: "yesterday's high"});
      levels.push({price: y.l, w: 1.5, src: "yesterday's low"});
      const wk = (t) => Math.floor((t / 86400 + 3) / 7);   // weeks start on Monday (UTC)
      const cw = wk(last(d1).t), pw = d1.filter((b) => wk(b.t) === cw - 1);
      if (pw.length >= 3) {
        levels.push({price: Math.max(...pw.map((b) => b.h)), w: 2, src: "last week's high"});
        levels.push({price: Math.min(...pw.map((b) => b.l)), w: 2, src: "last week's low"});
      }
    }
    const tol = Math.max(0.35 * A4, px * 0.004);
    const zones = buildZones(levels.filter((p) => p.price > px * 0.4 && p.price < px * 2.2), tol).filter((z) => z.w >= 2);
    const sup = zones.filter((z) => z.hi < px - 0.15 * A).sort((x, y) => y.mid - x.mid);
    const res = zones.filter((z) => z.lo > px + 0.15 * A).sort((x, y) => x.mid - y.mid);
    const inside = zones.find((z) => z.lo - 0.15 * A <= px && px <= z.hi + 0.15 * A) || null;
    const strong = (z) => z && (z.w >= 4 || z.src.some((s) => /daily|4-hour|week/.test(s)));
    // momentum, volatility, volume
    const r = lastVal(R), rPrev = R[n - 4], mh = lastVal(M.hist), mhPrev = M.hist[n - 4];
    const sq = pctRankLast(bbWidth(c, 20), 120);
    const vNow = sum(v.slice(-perDay));
    const baseBars = Math.min(perDay * 7, n - perDay);
    const vBase = baseBars >= perDay ? sum(v.slice(n - perDay - baseBars, n - perDay)) / (baseBars / perDay) : 0;
    const relVol = vBase > 0 ? vNow / vBase : null;
    const chgDay = c[n - 1] / c[Math.max(0, n - 1 - perDay)] - 1;
    // divergence on the last two swing lows / highs
    const lows = piv.filter((p) => p.type === "L"), highs = piv.filter((p) => p.type === "H");
    let div = null;
    const L1 = lows[lows.length - 1], L0 = lows[lows.length - 2], H1 = highs[highs.length - 1], H0 = highs[highs.length - 2];
    if (L1 && L0 && n - L1.i < 30 && L1.price < L0.price && R[L1.i] != null && R[L0.i] != null && R[L1.i] > R[L0.i] + 2) div = "bull";
    if (H1 && H0 && n - H1.i < 30 && H1.price > H0.price && R[H1.i] != null && R[H0.i] != null && R[H1.i] < R[H0.i] - 2 && (!div || H1.i > L1.i)) div = "bear";
    // stop run: in the last 3 closed candles price poked through a real swing low (high) and closed back above
    // (below) it; the newest candle may still be forming, so it only has to stay on the right side
    let sweep = null;
    if (n > 40) {
      const a0 = n - 4, a1 = n - 2, cl = c[n - 2];
      let minI = a0, maxI = a0;
      for (let i = a0; i <= a1; i++) { if (l[i] < l[minI]) minI = i; if (h[i] > h[maxI]) maxI = i; }
      for (const p of lows.slice(-3).reverse()) {
        if (minI - p.i < k + 3) continue;
        if (p.price > Math.min(...l.slice(Math.max(0, p.i - 20), p.i + 1))) continue;
        const lowest = Math.min(...l.slice(p.i + 1, n - 1));
        if (lowest === l[minI] && l[minI] < p.price - 0.2 * A && l[minI] > p.price - 2 * A && cl > p.price && px > p.price) {
          sweep = {dir: "up", level: p.price, wick: l[minI], i: minI};
          break;
        }
      }
      if (!sweep) {
        for (const p of highs.slice(-3).reverse()) {
          if (maxI - p.i < k + 3) continue;
          if (p.price < Math.max(...h.slice(Math.max(0, p.i - 20), p.i + 1))) continue;
          const highest = Math.max(...h.slice(p.i + 1, n - 1));
          if (highest === h[maxI] && h[maxI] > p.price + 0.2 * A && h[maxI] < p.price + 2 * A && cl < p.price && px < p.price) {
            sweep = {dir: "down", level: p.price, wick: h[maxI], i: maxI};
            break;
          }
        }
      }
    }
    // ---- score: + favours a long, - a short
    const parts = [];
    const add = (name, pts, why) => { if (pts) parts.push({name, pts, why}); };
    if (ctxD) add("Daily trend", ctxD.dir === "up" ? 20 : ctxD.dir === "down" ? -20 : 0, "daily " + ctxD.dir);
    if (ctx4) add("4-hour trend", ctx4.dir === "up" ? 15 : ctx4.dir === "down" ? -15 : 0, "4-hour " + ctx4.dir);
    add(T + " structure", st.trend === "up" ? 15 : st.trend === "down" ? -15 : 0, st.trend);
    if (st.bos) add("Break of structure", st.bos === "up" ? 5 : -5, st.bos);
    if (sweep) add("Stop run", sweep.dir === "up" ? 8 : -8, sweep.dir === "up" ? "swept a low and reclaimed it" : "swept a high and lost it");
    const nearSup = sup[0] && px - sup[0].hi <= 1.2 * A, nearRes = res[0] && res[0].lo - px <= 1.2 * A;
    if (nearSup && !nearRes) add("Location", strong(sup[0]) ? 10 : 6, "just above support");
    if (nearRes && !nearSup) add("Location", strong(res[0]) ? -10 : -6, "just under resistance");
    if (r != null && rPrev != null) {
      if (r >= 55 && r > rPrev) add("Momentum (RSI)", 5, "rising");
      if (r <= 45 && r < rPrev) add("Momentum (RSI)", -5, "falling");
    }
    if (mh != null && mhPrev != null) {
      if (mh > 0 && mh > mhPrev) add("MACD", 3, "rising");
      if (mh < 0 && mh < mhPrev) add("MACD", -3, "falling");
    }
    if (div) add("RSI divergence", div === "bull" ? 8 : -8, div);
    if (relVol != null && relVol >= 1.3) add("Volume", chgDay > 0 ? 4 : -4, "heavy volume");
    const D = inp.deriv || {};
    if (D.oiChange24h != null && D.oiChange24h >= 0.05 && chgDay > 0) add("Leverage piling in", -4, "open interest up with price");
    if (D.funding != null && D.funding >= 0.0005) add("Funding", -3, "longs crowded");
    if (D.funding != null && D.funding <= -0.0003) add("Funding", 3, "shorts crowded");
    const P = inp.picks;
    if (P && P.core != null) {
      const s = P.side === "long" ? 1 : -1;
      if (P.core >= 80) add("Tested swing score", 10 * s, P.side + " " + Math.round(P.core));
      else if (P.core >= 70) add("Tested swing score", 5 * s, P.side + " " + Math.round(P.core));
    }
    const MK = inp.market || null;
    if (MK && MK.mood && coin !== "BTC") {
      if (/^Risk-on/i.test(MK.mood)) add("Market backdrop", 5, "risk-on");
      else if (/^Risk-off/i.test(MK.mood)) add("Market backdrop", -5, "risk-off");
    }
    const SEN = inp.sentiment || (P && P.sentiment) || null;
    if (SEN && SEN.score != null) {
      if (SEN.score >= 65) add("Social sentiment", 4, "bullish");
      else if (SEN.score <= 35) add("Social sentiment", -4, "bearish");
    }
    const bias = Math.max(-100, Math.min(100, sum(parts.map((p) => p.pts))));
    const side = bias >= 20 ? "long" : bias <= -20 ? "short" : null;
    const confidence = Math.min(100, Math.round(Math.abs(bias) * 1.3));

    // ---- trade plans
    const buf = Math.max(0.4 * A, 0.15 * A4);
    const zoneTxt = (z) => z.hi - z.lo < 0.001 * z.mid ? fmtPrice(z.mid) : fmtPrice(z.lo) + "–" + fmtPrice(z.hi);
    const acct = inp.account || 500, riskPct = inp.risk || 0.02;
    const hold = {"15m": 16, "1h": 24, "4h": 30, "1d": 20}[tf] || 24;
    function plan(dir) {
      const L = dir === "long", d = L ? 1 : -1;
      const near = L ? sup : res, far = L ? res : sup;
      let type, entry, entryNote, stop;
      const brokeAt = L ? (st.bos === "up" && st.lastHigh ? st.lastHigh.price : null) : (st.bos === "down" && st.lastLow ? st.lastLow.price : null);
      const z0 = near[0];
      if (sweep && sweep.dir === (L ? "up" : "down") && Math.abs(px - sweep.level) <= 2 * A) {
        type = L ? "Stop run and reclaim" : "Stop run and rejection";
        entry = px;
        entryNote = "near the current price, after the " + (L ? "sweep of the low at " : "sweep of the high at ") + fmtPrice(sweep.level);
        stop = sweep.wick - d * buf;
      } else if (brokeAt && Math.abs(px - brokeAt) <= 1.5 * A) {
        type = L ? "Breakout retest" : "Breakdown retest";
        entry = brokeAt + d * 0.1 * A;
        entryNote = "on a retest of the broken level " + fmtPrice(brokeAt);
        stop = brokeAt - d * Math.max(1.0 * A, 0.3 * A4);
      } else if (z0 && Math.abs(px - (L ? z0.hi : z0.lo)) <= 1.5 * A) {
        type = L ? "Pullback to support" : "Rally into resistance";
        entry = L ? Math.min(px, z0.hi) : Math.max(px, z0.lo);
        entryNote = (L ? "at the support zone " : "at the resistance zone ") + zoneTxt(z0);
        stop = L ? z0.lo - buf : z0.hi + buf;
      } else if (sq != null && sq <= 0.25 && far[0] && Math.abs((L ? far[0].hi : far[0].lo) - px) <= 1.5 * A) {
        type = L ? "Squeeze breakout" : "Squeeze breakdown";
        entry = L ? far[0].hi + 0.15 * A : far[0].lo - 0.15 * A;
        entryNote = (L ? "on a break above " : "on a break below ") + fmtPrice(L ? far[0].hi : far[0].lo);
        stop = entry - d * 1.5 * A;
      } else if (z0) {
        type = L ? "Buy the dip at support" : "Sell the rally at resistance";
        entry = L ? z0.hi : z0.lo;
        entryNote = (L ? "on a dip to " : "on a rally to ") + fmtPrice(entry) + " (" + (L ? "support " : "resistance ") + zoneTxt(z0) + ")";
        stop = L ? z0.lo - buf : z0.hi + buf;
      } else {
        type = L ? "Trend entry" : "Trend short";
        entry = px;
        entryNote = "near the current price";
        stop = px - d * 1.5 * A;
      }
      if (Math.abs(entry - px) <= 0.1 * A) entry = px;   // close enough: take it at the market
      // the stop must sit beyond the nearest swing and keep a sensible distance
      const swing = L ? st.lastLow : st.lastHigh;
      if (swing && (L ? swing.price < entry : swing.price > entry) && Math.abs(entry - swing.price) <= 2.5 * A) {
        stop = L ? Math.min(stop, swing.price - 0.3 * A) : Math.max(stop, swing.price + 0.3 * A);
      }
      let risk = Math.abs(entry - stop);
      const minRisk = Math.max(1.0 * A, 0.35 * A4, entry * 0.005);
      if (risk < minRisk) { stop = entry - d * minRisk; risk = minRisk; }
      const wide = risk > Math.max(4 * A, 1.5 * A4);
      // targets: the next zones beyond the entry (1R to 8R away), filled up with 1.5R / 3R / 5R
      const ahead = (L ? res : sup).filter((z) => L ? z.lo > entry : z.hi < entry)
        .map((z) => ({price: L ? z.lo : z.hi, why: z.src[0] || "level", rr: Math.abs((L ? z.lo : z.hi) - entry) / risk}))
        .filter((z) => z.rr >= 1.0 && z.rr <= 8);
      const tg = [];
      for (const z of ahead) {
        if (!tg.length && z.rr > 4) tg.push({price: entry + d * 1.5 * risk, why: "1.5x the risk (the next level is far)", rr: 1.5});
        if (tg.length && z.rr < tg[tg.length - 1].rr + 0.7) continue;
        tg.push(z);
        if (tg.length === 3) break;
      }
      for (const m of [1.5, 3, 5]) {
        if (tg.length >= 3) break;
        if (!tg.length || m > tg[tg.length - 1].rr + 0.7) tg.push({price: entry + d * m * risk, why: m + "x the risk", rr: m});
      }
      while (tg.length < 3) {
        const m = Math.round((tg[tg.length - 1].rr + 1.5) * 10) / 10;
        tg.push({price: entry + d * m * risk, why: m + "x the risk", rr: m});
      }
      const targets = tg.slice(0, 3).map((t) => ({price: t.price, why: t.why, rr: Math.abs(t.price - entry) / risk, pct: d * (t.price / entry - 1)}));
      const stopPct = risk / entry, size = acct * riskPct / stopPct;
      const away = Math.abs(entry / px - 1);
      const order = entry === px ? "market" : (L ? entry < px : entry > px) ? "limit" : "stop";
      return {
        side: dir, type, entry, entryNote, stop, stopPct, risk, wide, targets, size, lev: size / acct, zone: z0 ? {w: z0.w, n: z0.n, lo: z0.lo, hi: z0.hi} : null,
        riskUsd: acct * riskPct, market: order === "market", away, order,
        invalid: "A " + T + " close " + (L ? "below " : "above ") + fmtPrice(stop),
        manage: "Take a third off at T1 and move the stop to your entry. Take another third at T2. Let the rest run to T3, or close it on a " +
          T + " close " + (L ? "below" : "above") + " the 20 EMA.",
        timeStop: "If T1 is not reached within about " + durTxt(hold * (TF_HOURS[tf] || 1)) + " (" + hold + " candles), close the trade: the idea is not working.",
      };
    }
    const plans = side ? [plan(side)] : [plan("long"), plan("short")];
    const alt = side ? plan(side === "long" ? "short" : "long") : null;

    // ---- checklist
    const checks = [];
    const chk = (group, name, ok, detail) => checks.push({group, name, ok, detail});
    if (ctxD) chk("Trend", "Daily trend", ctxD.dir === "up" ? 1 : ctxD.dir === "down" ? -1 : 0,
      "Price " + (px > ctxD.emaSlow ? "above" : "below") + " the 200-day average; 50-day " + (ctxD.emaFast > ctxD.emaSlow ? "above" : "below") + " 200-day");
    if (ctx4) chk("Trend", "4-hour trend", ctx4.dir === "up" ? 1 : ctx4.dir === "down" ? -1 : 0,
      "EMA 20 " + (ctx4.emaFast > ctx4.emaSlow ? "above" : "below") + " EMA 50; structure " + ctx4.structure.trend);
    chk("Trend", T + " structure", st.trend === "up" ? 1 : st.trend === "down" ? -1 : 0,
      st.trend === "up" ? "Higher highs and higher lows" : st.trend === "down" ? "Lower highs and lower lows" : "No clear sequence: a range");
    chk("Trend", "Averages (" + T + ")", e20[n - 1] > e50[n - 1] && px > e20[n - 1] ? 1 : e20[n - 1] < e50[n - 1] && px < e20[n - 1] ? -1 : 0,
      "Price " + fmtPrice(px) + ", EMA 20 " + fmtPrice(e20[n - 1]) + ", EMA 50 " + fmtPrice(e50[n - 1]) + (e200[n - 1] ? ", EMA 200 " + fmtPrice(e200[n - 1]) : ""));
    chk("Trend", "Stop run", sweep ? (sweep.dir === "up" ? 1 : -1) : 0,
      sweep ? (sweep.dir === "up" ? "Price dipped under the swing low at " + fmtPrice(sweep.level) + " and closed back above it: sellers' stops were taken and buyers stepped in"
        : "Price poked above the swing high at " + fmtPrice(sweep.level) + " and fell back under it: buyers' stops were taken and sellers stepped in") : "None in the last 3 candles");
    if (MK && MK.mood) chk("Trend", "Market backdrop", /^Risk-on/i.test(MK.mood) ? 1 : /^Risk-off/i.test(MK.mood) ? -1 : 0, MK.mood);
    chk("Momentum", "RSI 14", r == null ? 0 : r >= 55 ? 1 : r <= 45 ? -1 : 0, r == null ? "–" : "RSI " + r.toFixed(0) + (r >= 70 ? " (overbought)" : r <= 30 ? " (oversold)" : ""));
    chk("Momentum", "MACD", mh == null ? 0 : mh > 0 ? 1 : -1, mh == null ? "–" : "Histogram " + (mh > 0 ? "above" : "below") + " zero and " + (mh > mhPrev ? "rising" : "falling"));
    chk("Momentum", "Divergence", div === "bull" ? 1 : div === "bear" ? -1 : 0,
      div === "bull" ? "Price made a lower low but RSI a higher low (selling is fading)" : div === "bear" ? "Price made a higher high but RSI a lower high (buying is fading)" : "None");
    chk("Volatility", "Squeeze", 0, sq == null ? "–" : sq <= 0.2 ? "Bollinger width in the lowest " + Math.max(1, Math.round(sq * 100)) + "%: a big move is building" : "Bollinger width at the " + Math.round(sq * 100) + "th percentile");
    chk("Volatility", "Average range", 0, "ATR " + fmtPrice(A) + " per " + T + " candle (" + (A / px * 100).toFixed(2) + "% of the price)");
    chk("Volume", "Volume", relVol == null ? 0 : relVol >= 1.3 ? (chgDay > 0 ? 1 : -1) : 0,
      relVol == null ? "–" : "Last 24 hours " + relVol.toFixed(1) + "x the daily average" + (relVol >= 1.3 ? (chgDay > 0 ? ", on rising prices" : ", on falling prices") : ""));
    if (D.funding != null) chk("Positioning", "Funding", D.funding >= 0.0005 ? -1 : D.funding <= -0.0003 ? 1 : 0, (D.funding * 100).toFixed(4) + "% per 8 hours" + (D.source ? " (" + D.source + ")" : ""));
    if (D.oiChange24h != null) chk("Positioning", "Open interest", D.oiChange24h >= 0.05 && chgDay > 0 ? -1 : 0, pctTxt(D.oiChange24h) + " in 24 hours, price " + pctTxt(chgDay));
    if (D.topLong != null) chk("Positioning", "Top traders", D.topLong >= 0.6 ? 1 : D.topLong <= 0.4 ? -1 : 0, Math.round(D.topLong * 100) + "% of top traders' positions are long" + (D.source ? " (" + D.source + ")" : ""));
    if (D.crowdLong != null) chk("Positioning", "The crowd", D.crowdLong >= 0.7 ? -1 : D.crowdLong <= 0.35 ? 1 : 0, Math.round(D.crowdLong * 100) + "% of all accounts are long" + (D.crowdLong >= 0.7 ? " (crowded)" : ""));
    if (P && P.core != null) chk("Tested score", "Swing score (3-year test)", P.core >= 80 ? (P.side === "long" ? 1 : -1) : 0, Math.round(P.core) + " " + P.side + " (" + P.label + ")");
    if (SEN && SEN.score != null) chk("Sentiment", "Social sentiment", SEN.score >= 65 ? 1 : SEN.score <= 35 ? -1 : 0, SEN.score + "/100 (" + (SEN.label || "") + ")" + (SEN.partial ? ", from fewer sources" : ""));
    if (MK && MK.fng && MK.fng.value != null) chk("Sentiment", "Fear & Greed (whole market)", 0, MK.fng.value + "/100, " + (MK.fng.label || "").toLowerCase());

    // ---- the write-up
    const big = [];
    if (ctxD) big.push("On the daily chart " + coin + " is " + (ctxD.dir === "up" ? "in an uptrend" : ctxD.dir === "down" ? "in a downtrend" : "without a clear trend") +
      " (price " + (px > ctxD.emaSlow ? "above" : "below") + " its 200-day average" + (ctxD.structure.trend !== "range" ? ", " + (ctxD.structure.trend === "up" ? "higher highs and lows" : "lower highs and lows") : "") + ").");
    if (ctx4) big.push("The 4-hour trend is " + (ctx4.dir === "mixed" ? "mixed" : ctx4.dir) + (ctx4.structure.bos ? ", with a recent break " + (ctx4.structure.bos === "up" ? "above the last swing high" : "below the last swing low") : "") + ".");
    if (MK && MK.mood && coin !== "BTC") big.push("Market backdrop: " + MK.mood.split(":")[0].toLowerCase() + ".");
    const strTxt = [];
    strTxt.push("The " + T + " chart shows " + (st.trend === "up" ? "higher highs and higher lows" : st.trend === "down" ? "lower highs and lower lows" : "a range with no clear sequence") +
      (st.lastHigh ? "; last swing high " + fmtPrice(st.lastHigh.price) : "") + (st.lastLow ? ", last swing low " + fmtPrice(st.lastLow.price) : "") + ".");
    if (st.bos) strTxt.push("Price just broke " + (st.bos === "up" ? "above the last swing high: buyers took control." : "below the last swing low: sellers took control."));
    if (sweep) strTxt.push(sweep.dir === "up" ? "Price just ran the stops under " + fmtPrice(sweep.level) + " (low " + fmtPrice(sweep.wick) + ") and closed back above: a classic trap for late sellers."
      : "Price just ran the stops above " + fmtPrice(sweep.level) + " (high " + fmtPrice(sweep.wick) + ") and closed back under: a classic trap for late buyers.");
    if (sq != null && sq <= 0.2) strTxt.push("Volatility is squeezed (the quietest " + Math.max(1, Math.round(sq * 100)) + "% of the last " + durTxt(120 * (TF_HOURS[tf] || 1)) + "): quiet spells usually end with a sharp move, so watch the edges of the range.");
    const levelsTxt = [];
    if (sup[0]) levelsTxt.push("Support " + zoneTxt(sup[0]) + " (" + sup[0].src.join(", ") + ")" + (sup[1] ? ", then " + zoneTxt(sup[1]) : "") + ".");
    if (res[0]) levelsTxt.push("Resistance " + zoneTxt(res[0]) + " (" + res[0].src.join(", ") + ")" + (res[1] ? ", then " + zoneTxt(res[1]) : "") + ".");
    if (vp) levelsTxt.push("Most trading of the last " + durTxt(vpBars * (TF_HOURS[tf] || 1)) + " happened around " + fmtPrice(vp.poc) + " (value area " + fmtPrice(vp.val) + "–" + fmtPrice(vp.vah) + ").");
    const momTxt = [];
    if (r != null) momTxt.push("RSI is " + r.toFixed(0) + (r >= 70 ? ", overbought" : r <= 30 ? ", oversold" : r >= 55 ? ", with buyers in charge" : r <= 45 ? ", with sellers in charge" : ", neutral") + "; MACD " + (mh > 0 ? "positive" : "negative") + " and " + (mh > mhPrev ? "improving" : "weakening") + ".");
    if (div) momTxt.push(div === "bull" ? "There is a bullish divergence: the last low was lower but momentum was stronger, a classic sign that selling is drying up." : "There is a bearish divergence: the last high was higher but momentum was weaker, a classic sign that buying is drying up.");
    if (relVol != null) momTxt.push("Volume over the last 24 hours is " + relVol.toFixed(1) + "x normal" + (relVol >= 1.3 ? ", so this move has participation." : relVol <= 0.7 ? ", so the move lacks conviction." : "."));
    const posTxt = [];
    if (D.funding != null) posTxt.push("Funding is " + (D.funding * 100).toFixed(4) + "% per 8 hours" + (D.funding >= 0.0005 ? ": longs are paying a lot, the long side is crowded." : D.funding <= -0.0003 ? ": shorts are paying, the short side is crowded (fuel for a squeeze up)." : ", nothing extreme."));
    if (D.oiChange24h != null) posTxt.push(Math.abs(D.oiChange24h) < 0.005 ? "Open interest was flat over 24 hours." :
      "Open interest " + (D.oiChange24h >= 0 ? "rose " : "fell ") + Math.abs(D.oiChange24h * 100).toFixed(1) + "% in 24 hours" + (D.oiChange24h >= 0.05 && chgDay > 0 ? " while the price rose: new leverage is chasing the move, which made longs worse in our tests." : "."));
    if (D.topLong != null) posTxt.push("Top traders are " + Math.round(D.topLong * 100) + "% long" + (D.crowdLong != null ? " and all accounts " + Math.round(D.crowdLong * 100) + "% long" : "") + ".");
    else if (D.crowdLong != null) posTxt.push("All accounts are " + Math.round(D.crowdLong * 100) + "% long.");
    if (SEN && SEN.score != null) posTxt.push("Social sentiment is " + SEN.score + "/100 (" + String(SEN.label || "").toLowerCase() + ").");
    if (MK && MK.fng && MK.fng.value != null) posTxt.push("The market-wide Fear & Greed index is " + MK.fng.value + " (" + String(MK.fng.label || "").toLowerCase() + ").");
    if (P && P.core != null) posTxt.push("Our tested swing score has it at " + Math.round(P.core) + " for a " + P.side + (P.core >= 80 ? ", a ready setup." : ", not a ready setup."));
    const verdict = side ? side.toUpperCase() : "WAIT";
    const top = parts.slice().sort((a, b) => Math.abs(b.pts) - Math.abs(a.pts));
    const pros = top.filter((p) => side ? Math.sign(p.pts) === (side === "long" ? 1 : -1) : false).slice(0, 3).map((p) => p.name.toLowerCase());
    const cons = top.filter((p) => side ? Math.sign(p.pts) === (side === "long" ? -1 : 1) : false).slice(0, 2).map((p) => p.name.toLowerCase());
    let summary;
    const sgn = (x) => (x > 0 ? "+" : "") + x;
    if (side && inp.lean) {
      // the page's context read: where the chart leans and why, without a trade (the call comes from tested signals)
      summary = coin + " on the " + T + " chart leans " + side + " (score " + sgn(bias) + " on a scale of -100 to +100). " +
        "For it: " + (pros.join(", ") || "the overall picture") + "." + (cons.length ? " Against it: " + cons.join(", ") + "." : "") +
        " The chart's own " + side + " setup would be a " + plans[0].type.toLowerCase() + ", " + plans[0].entryNote + ".";
    } else if (side) {
      const p = plans[0];
      summary = coin + " on the " + T + " chart: " + (side === "long" ? "a long" : "a short") + " setup (" + p.type.toLowerCase() + "), agreement " + confidence + "/100. " +
        "For it: " + (pros.join(", ") || "the overall picture") + "." + (cons.length ? " Against it: " + cons.join(", ") + "." : "") +
        " Plan: " + (side === "long" ? "buy " : "sell ") + p.entryNote + ", stop " + fmtPrice(p.stop) + " (" + (p.stopPct * 100).toFixed(1) + "% away), first target " + fmtPrice(p.targets[0].price) + " (" + p.targets[0].rr.toFixed(1) + " times the risk).";
    } else if (inp.lean) {
      summary = coin + " on the " + T + " chart has no lean (score " + sgn(bias) + " on a scale of -100 to +100): the timeframes disagree or price sits in the middle of its range.";
    } else {
      summary = coin + " on the " + T + " chart: no clear edge right now (score " + bias + " on a scale of -100 to +100), because the timeframes disagree or price sits in the middle of its range. " +
        "Long only " + plans[0].entryNote + "; short only " + plans[1].entryNote + ".";
    }
    const change = side === "long" ? ["A " + T + " close below " + fmtPrice(plans[0].stop) + " ends the long " + (inp.lean ? "lean." : "idea.")]
      : side === "short" ? ["A " + T + " close above " + fmtPrice(plans[0].stop) + " ends the short " + (inp.lean ? "lean." : "idea.")]
      : ["A clean break of " + (res[0] ? fmtPrice(res[0].hi) : "resistance") + " with volume would favour longs; a break of " + (sup[0] ? fmtPrice(sup[0].lo) : "support") + " would favour shorts."];
    if (!inp.lean && ctxD && side && ((side === "long" && ctxD.dir === "down") || (side === "short" && ctxD.dir === "up"))) change.push("This trade goes against the daily trend: take profits early and keep the size small.");
    const labels = swingLabels(piv).slice(-12).map((x) => Object.assign(x, {t: bars[x.i].t}));
    return {
      coin, tf, price: px, atr: A, atrPct: A / px, chgDay, verdict, side, bias, confidence, parts, plans, alt, checks,
      zones: {support: sup.slice(0, 3), resistance: res.slice(0, 3), inside},
      context: {daily: ctxD && {dir: ctxD.dir, ema50: ctxD.emaFast, ema200: ctxD.emaSlow}, h4: ctx4 && {dir: ctx4.dir}},
      structure: st, rsi: r, macdHist: mh, squeeze: sq, relVol, divergence: div, sweep, vp, labels,
      series: {ema20: e20, ema50: e50, ema200: e200, rsi: R},
      text: {summary, big: big.join(" "), structure: strTxt.join(" "), levels: levelsTxt.join(" "), momentum: momTxt.join(" "),
             positioning: posTxt.join(" "), change: change.join(" ")},
    };
  }

  /* Every timeframe at once (15m, 1h, 4h, daily): the page switches between them without reloading. */
  function analyzeAll(data, opts) {
    const out = {};
    for (const tf of ["15m", "1h", "4h", "1d"]) {
      const main = data.bars[tf];
      if (!main || main.length < 120) continue;
      try {
        out[tf] = analyze(Object.assign({}, opts, {coin: data.coin, tf, main, h4: data.bars["4h"], d1: data.bars["1d"], deriv: data.deriv}));
      } catch (e) { /* too few candles on this timeframe */ }
    }
    return out;
  }

  // ------------------------------------------------------------------ the call: tested signals only
  /* Only signals that held up in our tests make the call, and each one comes with the exits it was tested with:
       swing  the Coin picks swing score, ready at 80 (3-year test: in at the next daily open, stop 2 daily ATR kept
              between 5% and 25%, a trailing stop 3 ATR behind the best price, out after 30 days at the latest)
       quant  a position of the quant desk, whose live strategies passed a 3-year test: its own stop, trailing stop
              and time limit
       smart  2+ proven Hyperliquid traders shorting a coin together (promising in a 30-day test without
              hindsight): stop 1.5 times the typical daily move (1.5% at least), out 24 hours after the signal
     The plan joins the tested trade as it stands: same stop level, same trailing stop, same time limit, so the
     trade on the page is the one the records count. Proven signals are sized at the chosen risk, mixed and promising
     ones at half of it. Proven signals on both sides mean no trade. The chart read never confirms or blocks a call:
     in a 3-year test of 5,453 swing signals the trades did no better when the 4-hour or the daily read agreed
     (tools/research/analyzer_gate.py). */
  const DAY = 86400, HOUR = 3600;
  const SWING = {stopK: 2, trailK: 3, minStop: 0.05, maxStop: 0.25, days: 30, readyAt: 80};
  const SMART = {stopK: 1.5, minStop: 0.015, hours: 24, lateHours: 6};
  const RISK_SHARE = {Proven: 1, Mixed: 0.5, Promising: 0.5};
  const SOURCE = {swing: "Coin picks swing", quant: "Quant desk", smart: "Smart money"};
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const per100 = (r) => (r == null || !isFinite(r)) ? null : Math.round(r * 100);
  const monthYear = (t) => { const d = new Date(t * 1000); return MON[d.getUTCMonth()] + " " + d.getUTCFullYear(); };
  const dayTxt = (t) => { const d = new Date(t * 1000); return MON[d.getUTCMonth()] + " " + d.getUTCDate(); };
  const usd100 = (p) => p == null ? "–" : (p > 0 ? "+$" : p < 0 ? "−$" : "$") + Math.abs(p);

  /* Proven when it made money per dollar risked overall and in every test year, Mixed when only overall. */
  function tierOf(R, years) {
    if (!(R > 0)) return "No edge";
    return years.length && years.every((y) => y > 0) ? "Proven" : "Mixed";
  }
  /* The tested record of the swing band a chart score falls in (picks_research.json). */
  function swingRecord(research, side, core) {
    const t = research && research.swing ? research.swing[side] : null;
    const b = t && core != null ? (t.bands || []).find((x) => core >= x.lo && core < x.hi) : null;
    if (!b) return null;
    const years = Object.keys(b.years || {}).sort().map((y) => ({y, r: b.years[y].R, n: b.years[y].n}));
    return {n: b.n, win: b.win, R: b.R, per100: per100(b.R), ret: b.ret, years, up: years.filter((y) => y.r > 0).length,
            band: b.lo + "–" + Math.min(100, b.hi - 1), tier: tierOf(b.R, years.map((y) => y.r)), period: research.period || null};
  }
  /* The record of one quant desk strategy (quant_research.json); "live" strategies passed the desk's tests. */
  function quantRecord(research, sid) {
    const s = research && research.strategies ? research.strategies[sid] : null;
    const t = s ? (s.three_year || s.one_year) : null;
    if (!t || !t.n) return null;
    const years = (s.years || []).filter((y) => y && y.n).map((y) => ({y: monthYear(y.from) + " to " + monthYear(y.to), r: y.avg, n: y.n}));
    const w = research.window_3y || [];
    return {n: t.n, win: t.wr, R: t.avg, per100: per100(t.avg), years, up: years.filter((y) => y.r > 0).length,
            tier: s.verdict === "live" ? "Proven" : "No edge", period: w.length === 2 ? monthYear(w[0]) + " to " + monthYear(w[1]) : null};
  }
  /* The record of the smart-money rule (smart.json): the test sets the verdict until 40 live trades decide it. */
  function smartRecord(sm) {
    const a = sm && sm.accuracy, t = a && a.tested;
    if (!t || !t.n) return null;
    const v = a.verdict;
    return {n: t.n, win: t.win, R: t.r, per100: per100(t.r), period: t.period || null, note: t.note || null, live: a.live || null,
            tier: v === "Proven" ? "Proven" : (v === "Promising" || v === "Mixed") ? "Promising" : "No edge"};
  }
  /* The power-of-1000 factor between two quotes of the same coin (1000PEPE against PEPE), or null when they differ. */
  function scaleOf(a, b) {
    if (!(a > 0) || !(b > 0)) return null;
    for (const k of [1, 1000, 0.001, 1e6, 1e-6]) if (Math.abs(Math.log(a / (b * k))) < Math.log(1.3)) return k;
    return null;
  }
  /* A run of losses this long is normal over 20 trades at this win rate (the expected longest run, rounded). */
  function lossRun(win, trades) {
    const q = 1 - win;
    if (!(q > 0 && q < 1)) return null;
    return Math.max(2, Math.round(Math.log(trades || 20) / Math.log(1 / q)));
  }
  /* Mean absolute daily move over the last 7 completed days. */
  function dailyMove(d1, now) {
    const today = Math.floor(now / DAY) * DAY;
    const b = (d1 || []).filter((x) => x && x.c > 0 && x.t < today).slice(-8);
    if (b.length < 5) return null;
    let s = 0;
    for (let i = 1; i < b.length; i++) s += Math.abs(b[i].c / b[i - 1].c - 1);
    return s / (b.length - 1);
  }

  /* What the scans say about one coin: {signals (tested, long or short), notes (there, but not a signal), inScan}.
     src: {picks, picksResearch, quant, quantResearch, smart}, each optional. */
  function testedSignals(coin, src) {
    src = src || {};
    const signals = [], notes = [];
    const P = src.picks, sc = P && P.scores ? P.scores[coin] : null;
    if (sc && (sc.side === "long" || sc.side === "short") && sc.score != null) {
      const readyAt = (P.settings && P.settings.ready) || SWING.readyAt;
      const rec = swingRecord(src.picksResearch, sc.side, sc.core != null ? sc.core : sc.score);
      const text = "Swing score " + Math.round(sc.score) + " for a " + sc.side + (sc.label ? " (" + sc.label + ")" : "");
      if (sc.score >= readyAt && rec && rec.tier !== "No edge") {
        signals.push({src: "swing", name: SOURCE.swing, side: sc.side, tier: rec.tier, rec, text, score: sc.score, core: sc.core, day: P.day});
      } else {
        notes.push({src: "swing", side: sc.side, rec, score: sc.score, readyAt,
                    text: text + (sc.score >= readyAt ? ", but scores like it have no tested edge." : ". A trade starts at " + readyAt + "."),
                    want: "Coin picks swing: the score reaching " + readyAt + " (now " + Math.round(sc.score) + " for a " + sc.side + ")."});
      }
    }
    const Q = src.quant, strategies = (Q && Q.strategies) || {};
    for (const o of (Q && Q.open) || []) {
      if (o.c !== coin || !(o.d === 1 || o.d === -1)) continue;
      const rec = quantRecord(src.quantResearch, o.s), st = strategies[o.s] || {}, side = o.d > 0 ? "long" : "short";
      if (rec && rec.tier === "No edge") continue;
      signals.push({src: "quant", name: SOURCE.quant, side, tier: "Proven", rec, pos: o, sid: o.s, strategy: st.name || o.s, desc: st.desc || "",
                    text: (st.name || o.s) + " is " + side + (o.px == null ? ", in at the next open" : " since " + dayTxt(o.t_in))});
    }
    if (Q && !signals.some((s) => s.src === "quant")) {
      notes.push({src: "quant", text: "The quant desk has no position in " + coin + ".",
                  want: "Quant desk: one of its strategies opening a trade on " + coin + " (they check every 4 hours and at each daily close)."});
    }
    const S = src.smart;
    if (S) {
      const row = (S.coins || []).find((c) => c.coin === coin), rec = smartRecord(S);
      if (row && row.signal && (row.side === "long" || row.side === "short") && rec && (row.proven || rec.tier !== "No edge")) {
        const trade = (S.open || []).find((t) => t.coin === coin && (t.kind || "signal") === "signal") || null;
        signals.push({src: "smart", name: SOURCE.smart, side: row.side, tier: row.proven ? "Proven" : rec.tier, rec, row, trade, text: row.text,
                      t: trade ? trade.t_in : S.generated, cluster: (S.coins || []).filter((c) => c.signal).length});
      } else {
        const want = (now) => "Smart money: 2 or more proven traders opening shorts on " + coin + " within 24 hours (" + now + ").";
        if (row && row.signal) {
          notes.push({src: "smart", side: row.side, text: row.text + ", but the rule lost money in its live record, so it is not a signal."});
        } else if (row && row.info) {
          notes.push({src: "smart", side: row.side, text: row.text + ": information only. In the test, coins they bought together did no better than the market.",
                      want: want("now a long crowd, which is information only")});
        } else if (row && row.traders) {
          notes.push({src: "smart", text: row.traders + " proven trader" + (row.traders > 1 ? "s hold " : " holds ") + coin + " (" + row.n_long + " long, " + row.n_short + " short); no group of them opened a side together in the last 24 hours.",
                      want: want("now " + row.traders + " of them hold it: " + row.n_long + " long, " + row.n_short + " short")});
        } else {
          notes.push({src: "smart", text: "None of the " + (S.traders_n || 200) + " proven Hyperliquid traders holds " + coin + ".", want: want("none of them holds it now")});
        }
      }
    }
    return {signals, notes, inScan: !!sc};
  }

  /* Swing: join the trade the test took, in at the open after the signal day. */
  function swingPlan(sig, ctx) {
    const d = sig.side === "long" ? 1 : -1, px = ctx.price;
    const entryDay = sig.day != null ? sig.day + DAY : Math.floor(ctx.now / DAY) * DAY;
    const bars = (ctx.d1 || []).filter((b) => b && b.c > 0);
    const before = bars.filter((b) => b.t < entryDay);
    const A = before.length >= 20 ? lastVal(atr(before.map((b) => b.h), before.map((b) => b.l), before.map((b) => b.c), 14)) : null;
    const close = before.length ? last(before).c : null;
    if (!(A > 0) || !(close > 0)) return {error: "Not enough daily candles on this exchange to set the tested stop."};
    const sd = Math.min(SWING.maxStop, Math.max(SWING.minStop, SWING.stopK * A / close)), aShare = A / close;
    const since = bars.filter((b) => b.t >= entryDay);
    const e = since.length ? since[0].o : close, trail = SWING.trailK * aShare * e;
    const stop0 = e * (1 - d * sd);
    let stop = stop0, best = e;
    for (const b of since) {
      if (d > 0 ? b.l <= stop : b.h >= stop) {
        return {expired: true, error: "The tested trade from the " + dayTxt(entryDay) + " open (" + fmtPrice(e) + ") already hit its stop at " + fmtPrice(stop) +
                ". The next chance is at the next daily open, if the score is still 80 or more."};
      }
      best = d > 0 ? Math.max(best, b.h) : Math.min(best, b.l);
      stop = d > 0 ? Math.max(stop, best - trail) : Math.min(stop, best + trail);
    }
    if (d > 0 ? px <= stop : px >= stop) return {expired: true, error: "The price is through the tested stop (" + fmtPrice(stop) + ")."};
    return {kind: "swing", side: sig.side, entry: px, stop, stopPct: Math.abs(px - stop) / px, trail, trailPct: trail / px, trailBy: "high",
            exitBy: entryDay + SWING.days * DAY, raised: stop !== stop0,
            tested: {entry: e, t: entryDay, stop: stop0, stopPct: sd, atrPct: aShare, move: d * (px / e - 1)}};
  }
  /* Quant desk: join its position with its current stop, trailing stop and time limit. */
  function quantPlan(sig, ctx) {
    const o = sig.pos, res = o.res || {}, d = o.d > 0 ? 1 : -1, px = ctx.price;
    const exitBy = o.t_in + (o.hold_h || 0) * HOUR;
    if (ctx.now >= exitBy) return {expired: true, error: "The desk's time limit for this trade has passed; it closes at the next scan."};
    const pending = o.px == null;
    const k = pending ? 1 : scaleOf(px, res.last_px || o.px);
    if (!k) return {error: "The desk prices " + ctx.coin + " on another market and its price does not match this chart, so its stop cannot be placed here. Use the levels on the Quant desk page."};
    const stop = pending ? px * (1 - d * o.stop_pct) : (res.stop_now != null ? res.stop_now : o.stop) * k;
    if (!(stop > 0) || (d > 0 ? px <= stop : px >= stop)) return {expired: true, error: "The price is through the desk's stop (" + fmtPrice(stop) + "): the trade is closing."};
    const trail = o.trail_pct ? (pending ? px : o.px * k) * o.trail_pct : 0;
    return {kind: "quant", side: sig.side, entry: px, stop, stopPct: Math.abs(px - stop) / px, trail, trailPct: trail / px, trailBy: "close", exitBy,
            raised: !pending && res.stop_now != null && Math.abs(res.stop_now - o.px * (1 - d * o.stop_pct)) > 1e-9 * o.px,
            desk: {entry: pending ? null : o.px * k, t: o.t_in, pending, stopPct: o.stop_pct, holdDays: Math.round((o.hold_h || 0) / 24), move: pending ? null : d * (px / (o.px * k) - 1)}};
  }
  /* Smart money: join the paper trade of the signal (same stop level, out 24 hours after the signal). */
  function smartPlan(sig, ctx) {
    const d = sig.side === "long" ? 1 : -1, px = ctx.price, tr = sig.trade;
    let sp = tr && tr.stop_pct > 0 ? tr.stop_pct : null;
    if (!sp) {
      const m = dailyMove(ctx.d1, ctx.now);
      sp = m != null ? Math.max(SMART.minStop, SMART.stopK * m) : 2 * SMART.minStop;
    }
    const t0 = tr ? tr.t_in : (sig.t || ctx.now);
    const exitBy = tr && tr.t_out_by ? tr.t_out_by : t0 + SMART.hours * HOUR;
    const left = exitBy - ctx.now;
    if (left <= SMART.lateHours * HOUR) {
      return {expired: true, error: left <= 0 ? "Its 24-hour window has ended." : "Only " + Math.max(1, Math.round(left / HOUR)) + " of its 24 tested hours are left: too late to join."};
    }
    const k = tr && tr.px ? scaleOf(px, tr.last_px || tr.px) : null;
    const stop = k ? tr.px * k * (1 - d * sp) : px * (1 - d * sp);
    if (d > 0 ? px <= stop : px >= stop) return {expired: true, error: "The price is through the signal's stop (" + fmtPrice(stop) + ")."};
    return {kind: "smart", side: sig.side, entry: px, stop, stopPct: Math.abs(px - stop) / px, trail: 0, trailPct: 0, exitBy,
            signal: {t: t0, entry: k ? tr.px * k : null, stopPct: sp, move: k ? d * (px / (tr.px * k) - 1) : null}};
  }
  function sized(plan, tier, ctx) {
    plan.riskShare = RISK_SHARE[tier] || 0.5;
    plan.riskUsd = ctx.account * ctx.risk * plan.riskShare;
    plan.size = plan.riskUsd / plan.stopPct;
    plan.lev = plan.size / ctx.account;
    return plan;
  }
  function recordTxt(rec) {
    if (!rec) return "";
    return usd100(rec.per100) + " per $100 risked over " + rec.n.toLocaleString("en-US") + " trades, " + Math.round(rec.win * 100) + "% winners";
  }

  /* The call for one coin. inp: {coin, price (on the chart's scale), d1 (daily candles, oldest first; the last may
     still be forming), now (seconds), account, risk, src}. Returns {verdict: LONG | SHORT | WAIT, side, tier, lead
     (the signal whose plan is used: the strongest tested record), plan, signals, agree, against, expired, notes,
     conflict, inScan, headline}. */
  function decide(inp) {
    const ctx = {coin: inp.coin, price: inp.price, now: inp.now || Math.floor(Date.now() / 1000), d1: inp.d1 || [],
                 account: inp.account > 0 ? inp.account : 500, risk: inp.risk > 0 ? inp.risk : 0.02};
    const T = testedSignals(inp.coin, inp.src);
    const live = [], expired = [];
    for (const s of T.signals) {
      const p = s.src === "swing" ? swingPlan(s, ctx) : s.src === "quant" ? quantPlan(s, ctx) : smartPlan(s, ctx);
      if (p.expired) { s.why = p.error; expired.push(s); continue; }
      s.plan = p.error ? null : sized(p, s.tier, ctx);
      s.planError = p.error || null;
      live.push(s);
    }
    const proven = live.filter((s) => s.tier === "Proven");
    const pool = proven.length ? proven : live;
    const sides = Array.from(new Set(pool.map((s) => s.side)));
    const side = sides.length === 1 ? sides[0] : null;
    const rank = (s) => (s.plan ? 1000 : 0) + (s.rec && s.rec.per100 != null ? s.rec.per100 : 0);
    const lead = side ? pool.filter((s) => s.side === side).sort((a, b) => rank(b) - rank(a))[0] : null;
    const out = {coin: inp.coin, verdict: side ? side.toUpperCase() : "WAIT", side, tier: lead ? lead.tier : null, lead,
                 plan: lead ? lead.plan : null, signals: live, expired, notes: T.notes, inScan: T.inScan,
                 agree: side ? live.filter((s) => s !== lead && s.side === side) : [],
                 against: side ? live.filter((s) => s.side !== side) : [], conflict: sides.length > 1,
                 lossRun: lead && lead.rec ? lossRun(lead.rec.win, 20) : null};
    const nm = (s) => s.name + " " + s.side + (s.src === "quant" ? " (" + s.strategy + ")" : s.src === "swing" ? " " + Math.round(s.score) : "");
    if (out.conflict) {
      out.headline = "Tested signals disagree: " + pool.map(nm).join(" against ") + ". With " + (proven.length ? "proven" : "tested") + " signals on both sides there is no trade.";
    } else if (lead) {
      out.headline = lead.name + ": " + lead.text + ". " + (lead.rec ? "Tested: " + recordTxt(lead.rec) + "." : "") +
        (lead.tier !== "Proven" ? " " + lead.tier + " record, so half size." : "");
    } else if (expired.length) {
      out.headline = "The tested signal has run its course: " + expired[0].why;
    } else {
      out.headline = "No tested signal on " + inp.coin + " right now. Nothing that held up in our tests points either way, so the answer is to wait.";
    }
    return out;
  }
  /* Coins with a call from tested signals right now, strongest first: [{coin, side, tier, srcs}]. Needs no candles,
     so only the time limits are checked here; the page checks the stops when a coin is opened. */
  function signalCoins(src, now) {
    src = src || {};
    now = now || Math.floor(Date.now() / 1000);
    const timely = (s) => s.src === "quant" ? now < s.pos.t_in + (s.pos.hold_h || 0) * HOUR
      : s.src === "smart" ? ((s.trade && s.trade.t_out_by) || (s.t || now) + SMART.hours * HOUR) - now > SMART.lateHours * HOUR : true;
    const coins = new Set(), P = src.picks, readyAt = (P && P.settings && P.settings.ready) || SWING.readyAt;
    for (const [c, x] of Object.entries((P && P.scores) || {})) if (x && x.score >= readyAt) coins.add(c);
    for (const o of (src.quant && src.quant.open) || []) coins.add(o.c);
    for (const r of (src.smart && src.smart.coins) || []) if (r.signal) coins.add(r.coin);
    const out = [];
    for (const c of coins) {
      const sig = testedSignals(c, src).signals.filter(timely), proven = sig.filter((s) => s.tier === "Proven"), pool = proven.length ? proven : sig;
      if (!pool.length) continue;
      const sides = new Set(pool.map((s) => s.side));
      if (sides.size !== 1) continue;
      const side = pool[0].side;
      out.push({coin: c, side, tier: proven.length ? "Proven" : pool[0].tier, srcs: Array.from(new Set(pool.filter((s) => s.side === side).map((s) => s.src)))});
    }
    return out.sort((a, b) => (a.tier === "Proven" ? 0 : 1) - (b.tier === "Proven" ? 0 : 1) || b.srcs.length - a.srcs.length || (a.coin < b.coin ? -1 : 1));
  }

  // ------------------------------------------------------------------ candles from the exchanges (browser only)
  const IV = {
    binance: {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"},
    bybit: {"15m": "15", "1h": "60", "4h": "240", "1d": "D"},
    gate: {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"},
    hl: {"15m": "15m", "1h": "1h", "4h": "4h", "1d": "1d"},
  };
  const num = (x) => +x;
  async function getJSON(url, opt) {
    const r = await fetch(url, opt);
    if (!r.ok) throw new Error(url.split("/")[2] + " " + r.status);
    return r.json();
  }
  const ratioShare = (x) => (x == null || !isFinite(x) || x <= 0) ? null : x / (1 + x);
  const SOURCES = {
    binance: {
      name: "Binance futures",
      syms: (s) => [s + "USDT", "1000" + s + "USDT"],
      candles: async (sym, tf, limit) => (await getJSON("https://fapi.binance.com/fapi/v1/klines?symbol=" + sym + "&interval=" + IV.binance[tf] + "&limit=" + limit))
        .map((k) => ({t: Math.floor(k[0] / 1000), o: num(k[1]), h: num(k[2]), l: num(k[3]), c: num(k[4]), v: num(k[7])})),
      deriv: async (sym) => {
        const out = {source: "Binance"};
        const jobs = [
          getJSON("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=" + sym).then((p) => { out.funding = num(p.lastFundingRate); }),
          getJSON("https://fapi.binance.com/futures/data/openInterestHist?symbol=" + sym + "&period=1h&limit=25").then((oi) => {
            if (oi.length > 2) out.oiChange24h = num(oi[oi.length - 1].sumOpenInterestValue) / num(oi[0].sumOpenInterestValue) - 1;
          }),
          getJSON("https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol=" + sym + "&period=1h&limit=1").then((tp) => { if (tp[0]) out.topLong = num(tp[0].longAccount); }),
          getJSON("https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=" + sym + "&period=1h&limit=1").then((g) => { if (g[0]) out.crowdLong = num(g[0].longAccount); }),
        ];
        await Promise.all(jobs.map((j) => j.catch(() => null)));
        return out;
      },
    },
    bybit: {
      name: "Bybit",
      syms: (s) => [s + "USDT", "1000" + s + "USDT"],
      candles: async (sym, tf, limit) => {
        const d = await getJSON("https://api.bybit.com/v5/market/kline?category=linear&symbol=" + sym + "&interval=" + IV.bybit[tf] + "&limit=" + Math.min(limit, 1000));
        const rows = (d.result && d.result.list) || [];
        if (!rows.length) throw new Error("no candles");
        return rows.map((k) => ({t: Math.floor(+k[0] / 1000), o: num(k[1]), h: num(k[2]), l: num(k[3]), c: num(k[4]), v: num(k[6])})).reverse();
      },
      deriv: async (sym) => {
        const out = {source: "Bybit"};
        const jobs = [
          getJSON("https://api.bybit.com/v5/market/tickers?category=linear&symbol=" + sym).then((t) => { out.funding = num(t.result.list[0].fundingRate); }),
          getJSON("https://api.bybit.com/v5/market/open-interest?category=linear&symbol=" + sym + "&intervalTime=1h&limit=25").then((oi) => {
            const L = oi.result.list; if (L.length > 2) out.oiChange24h = num(L[0].openInterest) / num(L[L.length - 1].openInterest) - 1;
          }),
          getJSON("https://api.bybit.com/v5/market/account-ratio?category=linear&symbol=" + sym + "&period=1h&limit=1").then((ar) => { out.crowdLong = num(ar.result.list[0].buyRatio); }),
        ];
        await Promise.all(jobs.map((j) => j.catch(() => null)));
        return out;
      },
    },
    gate: {
      name: "Gate.io futures",
      syms: (s) => [s + "_USDT"],
      candles: async (sym, tf, limit) => (await getJSON("https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract=" + sym + "&interval=" + IV.gate[tf] + "&limit=" + Math.min(limit, 1999)))
        .map((k) => ({t: +k.t, o: num(k.o), h: num(k.h), l: num(k.l), c: num(k.c), v: num(k.sum || k.v)})),
      deriv: async (sym) => {
        const out = {source: "Gate.io"};
        const jobs = [
          getJSON("https://api.gateio.ws/api/v4/futures/usdt/contracts/" + sym).then((x) => { out.funding = num(x.funding_rate); }),
          getJSON("https://api.gateio.ws/api/v4/futures/usdt/contract_stats?contract=" + sym + "&interval=1h&limit=25").then((s) => {
            if (s.length > 2) {
              const a = num(s[0].open_interest_usd), b = num(s[s.length - 1].open_interest_usd);
              if (a > 0) out.oiChange24h = b / a - 1;
              out.topLong = ratioShare(num(s[s.length - 1].top_lsr_size));
              out.crowdLong = ratioShare(num(s[s.length - 1].lsr_account));
            }
          }),
        ];
        await Promise.all(jobs.map((j) => j.catch(() => null)));
        return out;
      },
    },
    hl: {
      name: "Hyperliquid",
      syms: (s) => [s, "k" + s],
      candles: async (sym, tf, limit) => {
        const ms = TF_SEC[tf] * 1000, end = Date.now();
        const d = await getJSON("https://api.hyperliquid.xyz/info", {method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({type: "candleSnapshot", req: {coin: sym, interval: IV.hl[tf], startTime: end - ms * limit, endTime: end}})});
        if (!Array.isArray(d) || !d.length) throw new Error("no candles");
        return d.map((k) => ({t: Math.floor(k.t / 1000), o: num(k.o), h: num(k.h), l: num(k.l), c: num(k.c), v: num(k.v) * num(k.c)}));
      },
      deriv: async (sym) => {
        const out = {source: "Hyperliquid"};
        try {
          const d = await getJSON("https://api.hyperliquid.xyz/info", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({type: "metaAndAssetCtxs"})});
          const i = d[0].universe.findIndex((u) => u.name === sym);
          if (i >= 0) out.funding = num(d[1][i].funding) * 8;
        } catch (e) { /* optional */ }
        return out;
      },
    },
  };
  /* Find the coin on the first exchange that lists it with fresh candles and load all four timeframes. */
  async function load(coin) {
    const s = String(coin || "").toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (!s) throw new Error("Type a coin, for example XPL, SOL or PEPE.");
    const errors = [];
    for (const key of ["binance", "bybit", "gate", "hl"]) {
      const src = SOURCES[key];
      for (const sym of src.syms(s)) {
        try {
          const h1 = await src.candles(sym, "1h", 500);
          if (h1.length < 120) { errors.push(src.name + ": only " + h1.length + " candles"); continue; }
          if (Date.now() / 1000 - last(h1).t > 3 * 3600) { errors.push(src.name + " " + sym + ": no recent trading"); continue; }
          const [m15, h4, d1, deriv] = await Promise.all([
            src.candles(sym, "15m", 500).catch(() => null),
            src.candles(sym, "4h", 500).catch(() => null),
            src.candles(sym, "1d", 500).catch(() => null),
            src.deriv(sym).catch(() => ({})),
          ]);
          const mult = sym.startsWith("1000") ? 1000 : (sym.startsWith("k") && sym !== s) ? 1000 : 1;
          return {coin: s, symbol: sym, source: key, exchange: src.name, bars: {"15m": m15, "1h": h1, "4h": h4, "1d": d1}, deriv, multiplier: mult, loaded: Date.now()};
        } catch (e) {
          errors.push(src.name + " " + sym + ": " + e.message);
        }
      }
    }
    const err = new Error("No exchange returned candles for " + s + ". Check the ticker (for example XPL, SOL, PEPE).");
    err.details = errors;
    throw err;
  }
  /* Pull the newest candles of every timeframe into a loaded coin (for the live price). Returns true when a
     candle closed on any timeframe. */
  async function update(data) {
    const src = SOURCES[data.source];
    let closed = false;
    await Promise.all(Object.keys(data.bars).map(async (tf) => {
      const old = data.bars[tf];
      if (!old || !old.length) return;
      const fresh = await src.candles(data.symbol, tf, 3).catch(() => null);
      if (!fresh) return;
      for (const b of fresh) {
        let j = old.length - 1;
        while (j >= 0 && old[j].t > b.t) j--;
        if (j >= 0 && old[j].t === b.t) old[j] = b;
        else if (j === old.length - 1) { old.push(b); old.shift(); closed = true; }
      }
    }));
    data.updated = Date.now();
    return closed;
  }

  const TA = {analyze, analyzeAll, load, update, SOURCES, ema, rsi, atr, macd, bbWidth, pivots, structure, swingLabels, buildZones, volumeProfile, fmtPrice, TF_LABEL, TF_SEC,
              decide, testedSignals, signalCoins, swingRecord, quantRecord, smartRecord, scaleOf, lossRun, recordTxt, usd100, dayTxt, SWING, SMART};
  if (typeof module !== "undefined" && module.exports) module.exports = TA;
  else root.TA = TA;
})(typeof window !== "undefined" ? window : this);
