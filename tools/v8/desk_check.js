#!/usr/bin/env node
/* v8 Phase 12: render one published decision (data/v8/decision.json) through the desk's shared core (desk.js) exactly
   as the pages do, and check the screen against the file: every card shows its candidate's own state, Best trades
   now holds TRADE only and at most five, a zero-TRADE decision shows the empty state and no fallback card, funding
   cards have two healthy legs, the portfolio chip is the Phase 10 state, every Decision Trace has one row per trace
   entry, and the Analyzer panel of every asset agrees with Today. Read-only; nothing is published.

     node tools/v8/desk_check.js out/data/v8/decision.json [summary.json]

   Exit 0 when the screen agrees with the file, 1 otherwise. */
"use strict";
const fs = require("fs"), path = require("path");
const D = require(path.join(__dirname, "..", "..", "desk.js"));

const file = process.argv[2], out = process.argv[3];
const doc = JSON.parse(fs.readFileSync(file, "utf8"));
const now = doc.as_of + 60;                                  // a reader one minute after the scan
const problems = [];
const bad = (m) => problems.push(m);
const CARD = /<article class="opp([^"]*)" data-cand="([^"]*)" data-state="([^"]*)"/g;
const unesc = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
const cards = (h) => Array.from(String(h || "").matchAll(CARD)).map((m) => ({cls: m[1].trim(), id: unesc(m[2]), state: m[3]}));
const byId = new Map(doc.candidates.map((c) => [c.id, c]));
const CLS = {TRADE: "is-trade", WATCH: "is-watch", AVOID: "is-avoid"};
function truthful(where, list) {
  for (const c of list) {
    const cand = byId.get(c.id);
    if (!cand) { bad(where + ": a card for an unknown candidate " + c.id); continue; }
    if (c.state !== cand.state || c.cls !== CLS[cand.state]) bad(where + ": " + c.id + " shown as " + c.state + "/" + c.cls + ", engine " + cand.state);
  }
  return list;
}

const A = D.authority(doc, now);
if (A.status !== "AVAILABLE") bad("the decision is not available one minute after its scan: " + A.status + " " + A.reason);
const T = D.views.today(doc, now), F = D.views.funding(doc, now), P = D.views.portfolio(doc, now, null, "unavailable");
const best = truthful("Best trades now", cards(T.best)), emerging = truthful("Emerging", cards(T.emerging));
const funding = truthful("Funding", cards(F.qualified));
const placed = (name) => (doc[name].items || []).map((i) => i.id);
if (best.length > 5 || best.some((c) => c.state !== "TRADE")) bad("Best trades now shows " + best.map((c) => c.state).join(","));
if (JSON.stringify(best.map((c) => c.id)) !== JSON.stringify(placed("best_trades_now").slice(0, 5))) bad("Best trades now differs from the file's section");
if (JSON.stringify(emerging.map((c) => c.id)) !== JSON.stringify(placed("emerging_opportunities").slice(0, 5))) bad("Emerging differs from the file's section");
if (JSON.stringify(funding.map((c) => c.id)) !== JSON.stringify(placed("funding_opportunities").slice(0, 5))) bad("Funding differs from the file's section");
const zero = doc.best_trades_now.count === 0;
const zeroMsg = T.best.includes("No trade currently clears every desk gate.");
if (zero !== zeroMsg || (zero && best.length)) bad("zero-TRADE state shown wrongly (count " + doc.best_trades_now.count + ")");
for (const c of funding) {
  const L = byId.get(c.id).legs || {};
  if (!(L.long && L.short && L.long.health === "HEALTHY" && L.short.health === "HEALTHY")) bad("funding card " + c.id + " has a leg that is not HEALTHY");
}
const p10 = (doc.portfolio || {}).phase10 || {}, pfLabel = (D.PF_VIEW[p10.state] || D.PF_VIEW.UNEVALUABLE).label;
if (!T.pf.includes(pfLabel) || !P.body.includes(pfLabel)) bad("the portfolio chip is not the Phase 10 state " + p10.state);
// every Decision Trace: one row per entry, rules and effects as published
let traced = 0;
for (const c of doc.candidates) {
  const h = D.html.traceTable(c, doc), rows = (h.match(/<div class="trow r-/g) || []).length;
  const want = (c.trace || []).length + (((c.placement || {}).trace) || []).length;
  if (rows !== want) bad("trace of " + c.id + ": " + rows + " rows for " + want + " entries");
  traced++;
}
// the Analyzer panel of every asset agrees with the file and with Today
const today = new Map(best.concat(emerging, funding).map((c) => [c.id, c.state]));
let panels = 0;
for (const a of doc.assets) {
  const v = D.views.assetPanel(doc, a.asset, now, null);
  if (v.state !== a.state && v.status === "AVAILABLE") bad("Analyzer " + a.asset + " shows " + v.state + ", file " + a.state);
  for (const c of truthful("Analyzer " + a.asset, cards(v.html))) if (today.has(c.id) && today.get(c.id) !== c.state) bad("Analyzer and Today disagree on " + c.id);
  panels++;
}
const st = (doc.market_summary || {}).opportunity_states || {};
const summary = {schema: "v8.desk-check/1", decision_as_of: doc.as_of, valid_until: doc.valid_until, authority: A.status,
  opportunity_states: st, best_trades_now: {file: doc.best_trades_now.count, shown: best.length},
  emerging: {file: doc.emerging_opportunities.count, shown: emerging.length}, funding: {file: doc.funding_opportunities.count, shown: funding.length},
  zero_trade: zero, zero_trade_message_shown: zeroMsg, portfolio_state: p10.state || null, traces_checked: traced, analyzer_panels_checked: panels,
  problems};
if (out) fs.writeFileSync(out, JSON.stringify(summary, null, 1) + "\n");
console.log(JSON.stringify(Object.assign({}, summary, {problems: problems.length})));
for (const p of problems.slice(0, 40)) console.log("PROBLEM " + p);
process.exit(problems.length ? 1 : 0);
