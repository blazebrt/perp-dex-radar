/* Perp Decision Desk: the shared presentation core of every desk page (Today, Analyzer, Funding, Portfolio, Research).

   It reads the governed Phase 11 decision (data/v8/decision.json, v8.decision/1) and presents it. It decides nothing:
   every state, gate result, blocker, rank, section, effect and rule comes from the artifact, and this file only
   validates the shape it reads, labels it in plain words and renders it. In particular it never infers TRADE, WATCH or
   AVOID, a ranking, section membership, strategy authority, identity, execution readiness, funding authority or a
   portfolio pass/fail, and it builds no score.

     authority(doc, now)        the document as an authority: AVAILABLE, or MISSING / MALFORMED / STALE (fail closed;
                                stale means past the document's own valid_until, never a locally computed TTL)
     assetDecision(doc, a, now) the Phase 11 decision on one asset (the Analyzer's authority; the same object TODAY shows)
     cardModel / traceRows / rankInfo / ...   extraction and wording for the pages, from the artifact only
     html.*                     escaped HTML strings for the shared components (state chip, gate strip, trace, ...)

   One file for every page so TODAY, the Analyzer, Funding and Portfolio cannot read the same object differently. Runs in
   the browser (window.DESK) and under node (require) for the tests. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.DESK = factory();
})(typeof window !== "undefined" ? window : this, function () {
  "use strict";

  // ------------------------------------------------------------------ the contract
  const DECISION = {schema: "v8.decision/1", file: "data/v8/decision.json", directional: "DIRECTIONAL_STRATEGY",
                    emerging: "EMERGING_OBSERVATION", funding: "FUNDING_SPREAD", policyStatus: "POLICY_REVIEWED_V2_PROBATION"};
  const SECTIONS = ["best_trades_now", "emerging_opportunities", "funding_opportunities"];
  const UI_MAX = 5;                         // a desk section shows at most five, never a minimum (Phase 11 sections)
  const STATE_ORDER = {TRADE: 0, WATCH: 1, AVOID: 2};
  const AUDIT_FILE = "data/v8/audit_latest.json";
  const RESEARCH_DIR = "data/v8/research/";

  // ------------------------------------------------------------------ small helpers
  const isInt = (x) => Number.isInteger(x);
  const isNum = (x) => typeof x === "number" && isFinite(x);
  const sideOf = (d) => d === 1 ? "long" : d === -1 ? "short" : null;
  const ESC = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"};
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ESC[c]);
  const utcTxt = (t) => new Date(t * 1000).toISOString().slice(0, 16).replace("T", " ") + " UTC";
  const timeTxt = (t) => new Date(t * 1000).toISOString().slice(11, 16) + " UTC";
  function durTxt(s) {
    s = Math.max(0, Math.round(s));
    if (s < 90) return s + " s";
    if (s < 5400) return Math.round(s / 60) + " min";
    if (s < 172800) return Math.round(s / 3600) + " h";
    return Math.round(s / 86400) + " days";
  }
  const agoTxt = (t, now) => durTxt(now - t) + " ago";
  function pct(x, d) {
    if (!isNum(x)) return "–";
    const v = x * 100, dd = d != null ? d : Math.abs(v) < 0.1 ? 3 : Math.abs(v) < 10 ? 2 : 1;
    return v.toFixed(dd) + "%";
  }
  const lev = (x) => isNum(x) ? x.toFixed(2) + "x" : "–";
  function usd(x) {
    if (!isNum(x)) return "–";
    const a = Math.abs(x), s = x < 0 ? "−$" : "$";
    return a >= 1e9 ? s + (a / 1e9).toFixed(1) + "B" : a >= 1e6 ? s + (a / 1e6).toFixed(1) + "M" : a >= 1e3 ? s + (a / 1e3).toFixed(1) + "K" : s + a.toFixed(a >= 100 ? 0 : 2);
  }
  function price(x) {
    if (!isNum(x)) return "–";
    const a = Math.abs(x), d = a >= 1000 ? 1 : a >= 100 ? 2 : a >= 1 ? 4 : a > 0 ? Math.min(12, Math.ceil(-Math.log10(a)) + 4) : 2;
    return Number(x).toFixed(d).replace(/(\.\d*?[1-9])0+$/, "$1").replace(/\.0+$/, "");
  }
  const rate8h = (x) => isNum(x) ? (x * 100).toFixed(4) + "% / 8h" : "–";
  const titleCase = (s) => String(s || "").toLowerCase().replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

  // ------------------------------------------------------------------ wording (labels only, never a decision)
  const STEP_LABEL = {
    DISCOVERY: "Discovery", IDENTITY: "Identity", ECONOMIC_EXPOSURE: "Economic exposure", VENUE_HEALTH: "Venue health",
    SIGNAL: "Signal", STRATEGY_AUTHORITY: "Strategy authority", EXECUTION_LIQUIDITY: "Execution liquidity", FUNDING: "Funding",
    PORTFOLIO_BEFORE: "Portfolio before", PROPOSED_TRADE: "Proposed trade", PORTFOLIO_AFTER: "Portfolio after",
    RISK_LIMITS: "Risk limits", DECISION_STATE: "Decision", RANKING: "Ranking", SECTION_PLACEMENT: "Placement",
  };
  const RESULT_VIEW = {
    PASS: {label: "Pass", cls: "r-pass", mark: "✓"}, CAP: {label: "Watch cap", cls: "r-cap", mark: "◐"},
    MISSING: {label: "Missing", cls: "r-miss", mark: "?"}, FAIL: {label: "Fail", cls: "r-fail", mark: "✕"},
    INFO: {label: "Info", cls: "r-info", mark: "·"}, NOT_APPLICABLE: {label: "Not applicable", cls: "r-na", mark: "–"},
  };
  const STATE_VIEW = {
    TRADE: {label: "Trade", cls: "st-trade", mark: "●", line: "All required desk gates currently pass."},
    WATCH: {label: "Watch", cls: "st-watch", mark: "◐", line: "Worth monitoring; not trade-ready."},
    AVOID: {label: "Avoid", cls: "st-avoid", mark: "✕", line: "Not to be taken now under the governed rules. A current decision, not a verdict on the asset."},
    NONE: {label: "No decision", cls: "st-none", mark: "○", line: "Phase 11 has no decision on this asset."},
    UNAVAILABLE: {label: "No authority", cls: "st-unavail", mark: "◌", line: "The decision cannot be evaluated reliably right now."},
  };
  const SECTION_LABEL = {best_trades_now: "Best trades now", emerging_opportunities: "Emerging opportunities",
                         funding_opportunities: "Funding opportunities"};
  const TYPE_LABEL = {DIRECTIONAL_STRATEGY: "Strategy signal", EMERGING_OBSERVATION: "Emerging observation",
                      FUNDING_SPREAD: "Funding spread"};
  const EVIDENCE_LABEL = {RECENTLY_OBSERVED_BY_DESK: "First seen by this desk recently (not a listing date)",
                          LARGE_24H_MOVE: "Large 24-hour move", MULTI_VENUE_PRESENCE: "Trades on several venues",
                          CURRENT_STRATEGY_SIGNAL: "Current strategy signal", FUNDING_SPREAD: "Funding differential"};
  /* Plain words for the engine's codes. Wording only: the code itself stays visible next to it. */
  const CODE_TXT = {
    STRATEGY_RESEARCH_AUTHORITY_INSUFFICIENT: "strategy authority insufficient (not requalified by Phase 9)",
    STRATEGY_DISABLED: "strategy disabled", STRATEGY_UNGOVERNED: "strategy not governed by the Phase 9 policy",
    STRATEGY_RESEARCH_REJECTED: "strategy research rejected", STRATEGY_RESEARCH_INVALIDATED: "strategy research invalidated",
    FUNDING_UNKNOWN: "funding missing", PORTFOLIO_APPROACHING_LIMITS: "portfolio approaching its risk limits",
    PORTFOLIO_LIMIT_BREACHED: "the position would breach the portfolio risk limits", PORTFOLIO_UNEVALUABLE: "portfolio risk unevaluable",
    PORTFOLIO_INPUT_MISSING: "no portfolio input", PROPOSAL_UNQUANTIFIABLE: "the position cannot be quantified", COST_UNKNOWN: "costs unknown",
    EXECUTION_LIQUIDITY_BELOW_GATE: "liquidity below the execution gate", EXECUTION_LIQUIDITY_UNKNOWN: "liquidity unknown",
    NOT_ON_TRADE_DEX: "not on a trade DEX", IDENTITY_NOT_VERIFIED: "identity not verified as crypto", IDENTITY_NON_CRYPTO: "not a crypto asset",
    ECONOMIC_EXPOSURE_CONFLICT: "conflicting economic exposure", EXPOSURE_METADATA_DEGRADED: "exposure checks degraded",
    VENUE_DATA_DEGRADED: "venue data degraded", DISCOVERY_DEGRADED: "discovery degraded", INPUT_STALE: "an input of the scan is stale",
    NOT_IN_DISCOVERY: "not in discovery", UNSUPPORTED_OR_INACTIVE_MARKET: "no active supported perp",
    SIGNAL_STALE: "signal stale", SIGNAL_INVALID: "signal invalid", SIGNAL_TIMEFRAME_UNKNOWN: "signal timeframe unknown",
    POSITION_ALREADY_OPEN: "the book already holds this position",
    NO_GOVERNED_STRATEGY_AUTHORITY: "an observation, not a governed strategy signal",
    FUNDING_SPREAD_RESEARCH_AUTHORITY_MISSING: "no research authority for funding-spread persistence",
    PORTFOLIO_HEDGE_MODEL_UNAVAILABLE: "no portfolio hedge model for a two-leg position",
    NO_FUNDING_SPREAD: "no positive funding spread", LEG_LIQUIDITY_BELOW_GATE: "a leg's venue volume is below the gate",
    LEG_LIQUIDITY_UNKNOWN: "a leg's venue volume is unknown", CARRY_NOT_POSITIVE_AFTER_COSTS: "carry is not positive after costs",
    BASIS_TOO_WIDE: "the legs' prices are too far apart", BASIS_UNKNOWN: "basis unknown", NOT_RISK_FREE: "not risk-free",
    STRATEGY_SIDE_NOT_CONFIRMED: "this side of the strategy is not confirmed by the archive (probation covers the confirmed side only)",
    PROBATION_FORWARD_TEST_FAILED: "the live forward test fell below the archive's demotion band",
    PROBATION_NOT_YET_EFFECTIVE: "before the registered start of the probation forward test",
    PROBATION_ENTRY_WINDOW_PASSED: "past the confirmed entry window for this signal",
    PROBATION_TERMS_MISSING: "probation terms missing", FORWARD_TEST_RECORD_MISSING: "the forward test's live record is missing",
  };
  const TIER_VIEW = {
    FULL: {label: "Requalified", line: "Requalified under the full Phase 9 gate; page sizing."},
    PROBATION: {label: "Probation · reduced size", line: "An archive-confirmed strategy side (survivorship-free, out of sample) at a reduced size, inside its confirmed entry window, with a forward test registered before its first trade. Not requalified: it is demoted automatically if its live record falls below the archive's band."},
  };
  const codeLabel = (c) => CODE_TXT[c] || String(c).toLowerCase().replace(/_/g, " ");
  const codeTxt = (c) => codeLabel(c) + " (" + c + ")";
  const LIMIT_LABEL = {
    max_executable_risk: "Executable risk", max_stressed_loss: "Worst stressed loss", max_side_stop_risk: "One-side stop risk",
    max_cluster_stop_risk: "Correlated-cluster stop risk", max_strategy_stop_risk: "Single-strategy stop risk",
    max_asset_stop_risk: "Single-asset stop risk", max_gross_leverage: "Gross leverage", max_net_leverage: "Net leverage",
    max_position_leverage: "Largest position leverage",
  };
  const LIMIT_ORDER = Object.keys(LIMIT_LABEL);
  const isLeverageLimit = (k) => /leverage/.test(k);
  const limitValue = (k, v) => isLeverageLimit(k) ? lev(v) : pct(v);
  const STRESS_LABEL = {CORRELATED_MARKET_MOVE: "Correlated market move", DIVERSIFICATION_FAILURE: "Diversification failure",
                        EXECUTION_COST: "Execution cost", FUNDING_DETERIORATION: "Funding deterioration",
                        LIQUIDITY_DEGRADATION: "Liquidity degradation", STOP_SLIPPAGE: "Stop slippage"};
  const PF_VIEW = {
    WITHIN_LIMITS: {label: "Within limits", cls: "pf-ok", mark: "●", line: "Every governed portfolio limit holds."},
    APPROACHING_LIMITS: {label: "Approaching limits", cls: "pf-near", mark: "◐", line: "At least one governed limit is close to its threshold."},
    LIMIT_BREACHED: {label: "Limits breached", cls: "pf-breach", mark: "✕", line: "Portfolio limits exceeded."},
    UNEVALUABLE: {label: "Cannot evaluate", cls: "pf-unknown", mark: "◌", line: "Required risk authority is missing, so the portfolio cannot be evaluated."},
  };
  const RANK_FIELD_TXT = {signal_kind_order: "a new signal before an active one", signal_age_s: "a fresher signal",
                          slippage_rate: "a cheaper execution tier", after_executable_risk: "less portfolio risk after the trade",
                          primary_evidence_count: "more primary evidence", evidence_count: "more evidence",
                          outstanding_blockers: "fewer outstanding blockers", net_carry: "a larger net carry", basis_abs: "a smaller basis"};
  const TIE_FIELDS = {asset: 1, strategy: 1, direction: 1, id: 1};   // the policy's deterministic name tie-breaks

  // ------------------------------------------------------------------ the authority (read only)
  /* The decision document as an authority: {status: AVAILABLE | MISSING | MALFORMED | STALE, doc, reason}. Only the
     shape the desk reads is checked; nothing in it is recomputed. Stale: past the document's own valid_until. */
  function authority(doc, now) {
    if (doc == null) return {status: "MISSING", doc: null, reason: "the Phase 11 decision (" + DECISION.file + ") is not loaded"};
    if (typeof doc !== "object" || doc.schema !== DECISION.schema || !isInt(doc.as_of) || !isInt(doc.valid_until) ||
        !Array.isArray(doc.candidates) || !Array.isArray(doc.assets) || !doc.authority || typeof doc.authority !== "object") {
      return {status: "MALFORMED", doc: null, reason: "the Phase 11 decision is not a valid " + DECISION.schema + " document"};
    }
    if (!isNum(now) || doc.valid_until < doc.as_of || now < doc.as_of) {
      return {status: "MALFORMED", doc: null, as_of: doc.as_of, valid_until: doc.valid_until,
              reason: "the Phase 11 decision has an invalid or future validity window"};
    }
    if (doc.candidates.some((c) => c && c.type === DECISION.directional && !candidateWindow(c, doc, now))) {
      return {status: "MALFORMED", doc: null, reason: "a directional decision has an invalid or future validity window"};
    }
    if (!(now <= doc.valid_until)) {
      return {status: "STALE", doc: null, as_of: doc.as_of, valid_until: doc.valid_until,
              reason: "the Phase 11 decision of " + utcTxt(doc.as_of) + " is stale (valid until " + utcTxt(doc.valid_until) + ")"};
    }
    return {status: "AVAILABLE", doc, as_of: doc.as_of, valid_until: doc.valid_until, reason: null};
  }
  function candidateWindow(c, doc, now) {
    // Candidate expiry can be earlier than the document, never later. Optional start authority is strict too.
    const start = c.valid_from == null ? (c.as_of == null ? doc.as_of : c.as_of) : c.valid_from;
    const starts = [start];
    if (c.as_of != null) starts.push(c.as_of);
    if (c.valid_from != null) starts.push(c.valid_from);
    return starts.every((t) => isInt(t) && doc.as_of <= t && t <= now && t <= c.valid_until) && isInt(c.valid_until) && doc.as_of <= start && start <= now &&
      start <= c.valid_until && c.valid_until <= doc.valid_until;
  }
  function candidateOk(c) {
    return !!c && typeof c === "object" && typeof c.id === "string" && STATE_ORDER[c.state] != null && !!sideOf(c.direction) &&
      typeof c.strategy === "string" && Array.isArray(c.blockers) && Array.isArray(c.caps) && Array.isArray(c.missing_authorities) &&
      isInt(c.valid_until) && !!c.explanation && typeof c.explanation === "object";
  }
  function briefOf(c, now) {
    const codes = c.state === "WATCH" ? c.caps.concat(c.missing_authorities) : c.state === "AVOID" ? c.blockers.slice() : [];
    const pl = c.placement && typeof c.placement === "object" ? c.placement : {};
    return {id: c.id, strategy: c.strategy, side: sideOf(c.direction), state: c.state, blocking_step: c.blocking_step || null,
            blockers: c.blockers.slice(), caps: c.caps.slice(), missing: c.missing_authorities.slice(), codes, reasons: codes.map(codeTxt),
            to_become_trade: (c.explanation.to_become_trade || []).filter((x) => x && x.code).map((x) => ({step: x.step, code: x.code})),
            proposal: c.proposal || null, valid_until: c.valid_until, expired: !(now <= c.valid_until), section: pl.section || null, rank: pl.section ? pl.rank : null};
  }
  /* The Phase 11 decision on one asset: {status, state (TRADE | WATCH | AVOID | NONE; null without an available
     decision), trade (the one current TRADE when there is one and it agrees with every other TRADE), candidates (every
     directional decision on the asset, best state first), conflict, asset, reason, as_of, valid_until, hashes}.
     Nothing is decided here: the states, codes and reasons are the engine's. */
  function assetDecision(doc, coin, now) {
    const A = authority(doc, now);
    const out = {status: A.status, state: null, trade: null, candidates: [], conflict: false, asset: null, reason: A.reason,
                 as_of: A.as_of || null, valid_until: A.valid_until || null, policy_hash: null, authority_hash: null};
    if (A.status !== "AVAILABLE") return out;
    out.policy_hash = A.doc.policy_hash || null;
    out.authority_hash = A.doc.authority.authority_hash || null;
    const mine = A.doc.candidates.filter((c) => c && c.type === DECISION.directional && c.asset === coin);
    if (!mine.every(candidateOk)) {
      return Object.assign(out, {status: "MALFORMED", reason: "a Phase 11 decision on " + coin + " is malformed"});
    }
    const a = A.doc.assets.find((x) => x && x.asset === coin) || null;
    out.asset = a ? {state: a.state, identity: a.identity, blockers: Array.isArray(a.blockers) ? a.blockers.slice() : []} : null;
    out.candidates = mine.map((c) => briefOf(c, now)).sort((x, y) => STATE_ORDER[x.state] - STATE_ORDER[y.state] || (x.id < y.id ? -1 : 1));
    if (!mine.length) {
      return Object.assign(out, {state: "NONE", reason: "Phase 11 has no directional decision on " + coin +
        (a ? " (asset state " + a.state + ")" : " (not in this scan's discovery)")});
    }
    const trades = out.candidates.filter((c) => c.state === "TRADE");
    if (trades.some((c) => c.expired)) {
      return Object.assign(out, {status: "STALE", reason: "the Phase 11 TRADE " + trades.find((c) => c.expired).id + " is past its valid_until"});
    }
    if (new Set(trades.map((c) => c.side)).size > 1) {
      return Object.assign(out, {state: "TRADE", conflict: true, reason: "Phase 11 TRADE decisions on " + coin + " disagree in direction"});
    }
    out.state = out.candidates[0].state;
    if (trades.length) out.trade = trades.slice().sort((x, y) => (x.rank == null ? 1e9 : x.rank) - (y.rank == null ? 1e9 : y.rank) || (x.id < y.id ? -1 : 1))[0];
    return out;
  }

  /* One plain sentence for an asset's decision (the Analyzer's headline), worded from the same objects as the cards. */
  function assetLine(doc, coin, now) {
    const A = authority(doc, now);
    if (A.status !== "AVAILABLE") return "No call: " + A.reason + ".";
    const I = index(A.doc), rec = I.assets.get(coin) || null, cands = I.byAsset.get(coin) || [];
    if (!rec && !cands.length) return coin + " is outside the desk's governed discovery: there is no decision, and nothing here is a trade.";
    const ad = assetDecision(A.doc, coin, now);
    if (ad.status !== "AVAILABLE" || ad.conflict) return "No call: " + ad.reason + ".";
    if (ad.trade) return "Trade-ready: every required desk gate passes for " + ad.trade.strategy + " " + ad.trade.side + ".";
    const uniq = (xs) => Array.from(new Set(xs));
    const dir = cands.filter((c) => c.type === DECISION.directional);
    if (dir.length && ad.state === "WATCH") {
      return "Watch, not a trade: " + uniq(dir.filter((c) => c.state === "WATCH").reduce((o, c) => o.concat(c.caps || [], c.missing_authorities || []), []).map(codeLabel)).join("; ") + ".";
    }
    if (dir.length) return "Avoid now. " + uniq(dir.map((c) => (STEP_LABEL[c.blocking_step] || c.blocking_step) + ": " + codeLabel((c.blockers || [])[0] || ""))).join("; ") + ".";
    const other = cands.filter((c) => c.type !== DECISION.directional);
    if (!other.length) return "No current opportunity on " + coin + ((rec && rec.blockers || []).length ? ": " + rec.blockers.map(codeLabel).join(", ") : "") + ".";
    return "No directional call: no governed strategy has a current signal on " + coin + ". " +
      other.map((c) => (TYPE_LABEL[c.type] || c.type) + ": " + (STATE_VIEW[c.state] || {label: c.state}).label.toLowerCase()).join("; ") + ".";
  }

  // ------------------------------------------------------------------ reading the document (extraction only)
  const IDX = typeof WeakMap === "function" ? new WeakMap() : null;
  /* Lookups over one document: candidates by id and by asset, asset records by name. */
  function index(doc) {
    if (IDX && IDX.has(doc)) return IDX.get(doc);
    const byId = new Map(), byAsset = new Map(), assets = new Map();
    for (const c of (doc && doc.candidates) || []) {
      if (!c || typeof c.id !== "string") continue;
      byId.set(c.id, c);
      if (!byAsset.has(c.asset)) byAsset.set(c.asset, []);
      byAsset.get(c.asset).push(c);
    }
    for (const a of (doc && doc.assets) || []) if (a && typeof a.asset === "string") assets.set(a.asset, a);
    const out = {byId, byAsset, assets};
    if (IDX && doc && typeof doc === "object") IDX.set(doc, out);
    return out;
  }
  function gate(c, step, has) {
    return ((c && c.trace) || []).find((g) => g && g.step === step && (!has || (g.input && typeof g.input === "object" && has in g.input))) || null;
  }
  /* A section's items exactly as Phase 11 placed them, at most five on screen, with each item's candidate. An item is
     shown only when it agrees with the file's own contract: its candidate exists once, its state is the item's state and
     one of the section's eligible states (selection_trace), its type is one of the section's types, a funding spread has
     two HEALTHY legs, and nothing but a TRADE is ever under Best trades now. Anything else is not shown and is counted as
     inconsistent, so a tampered or broken file can never put a WATCH into Best trades now. With `now`, an item past its
     own valid_until is not shown either (counted as expired): the decision on it has lapsed, and the desk never extends it. */
  const SECTION_ONLY = {best_trades_now: "TRADE"};   // the heading promises trade-readiness; nothing else is ever under it
  function legsHealthy(c) {
    const L = c && c.legs;
    return !!(L && L.long && L.short && L.long.health === "HEALTHY" && L.short.health === "HEALTHY");
  }
  function itemOk(name, t, it, cand) {
    if (!it || !cand) return false;
    if (!(Array.isArray(t.eligible_states) && t.eligible_states.includes(cand.state)) || it.state !== cand.state) return false;
    if (Array.isArray(t.types) && !t.types.includes(cand.type)) return false;
    if (SECTION_ONLY[name] && cand.state !== SECTION_ONLY[name]) return false;
    if (cand.type === DECISION.funding && !legsHealthy(cand)) return false;
    return true;
  }
  function section(doc, name, now) {
    const s = (doc && doc[name]) || {};
    const t = s.selection_trace && typeof s.selection_trace === "object" ? s.selection_trace : {};
    const byId = index(doc).byId, seen = new Set();
    const all = Array.isArray(s.items) ? s.items : [];
    const ok = [], expired = [];
    for (const it of all) {
      const cand = it && typeof it.id === "string" ? byId.get(it.id) || null : null;
      if (!cand || seen.has(it.id) || !itemOk(name, t, it, cand) ||
          (cand.type === DECISION.directional && (!candidateOk(cand) || !candidateWindow(cand, doc, now)))) continue;
      seen.add(it.id);
      if (isNum(now) && !(now <= cand.valid_until)) { expired.push({id: it.id, rank: it.rank, valid_until: cand.valid_until}); continue; }
      ok.push({rank: it.rank, id: it.id, cand});
    }
    const items = ok.slice(0, UI_MAX);
    return {name, label: SECTION_LABEL[name] || name, items, count: items.length, max: Math.min(UI_MAX, isInt(t.max) ? t.max : UI_MAX),
            trace: t, why_fewer: t.why_fewer || null, eligible: isInt(t.eligible) ? t.eligible : null,
            inconsistent: all.length - ok.length - expired.length, expired};
  }
  /* Why each placed item sits where it is: the engine's own pairwise explanation (selection_trace.order) and cutoff,
     used only between two items that are next to each other on screen. Items separated only by a name tie-break are
     shown as tied (T1, T1, ...) so no rank implies a strength it lacks. */
  function rankInfo(doc, name, now) {
    const sec = section(doc, name, now), order = Array.isArray(sec.trace.order) ? sec.trace.order : [], out = [];
    const pair = new Map();
    for (const o of order) if (o && o.above && o.below) pair.set(o.above.id + "\u0000" + o.below.id, o);
    const between = (i) => i + 1 < sec.items.length ? pair.get(sec.items[i].id + "\u0000" + sec.items[i + 1].id) || null : null;
    const tieNext = sec.items.map((_, i) => { const o = between(i); return !!(o && o.rule && TIE_FIELDS[o.rule[0]]); });
    let groupStart = 0;
    for (let i = 0; i < sec.items.length; i++) {
      if (i > 0 && !tieNext[i - 1]) groupStart = i;
      const tied = (i > 0 && tieNext[i - 1]) || tieNext[i];
      const rank = sec.items[i].rank;
      out.push({id: sec.items[i].id, rank, label: tied ? "T" + sec.items[groupStart].rank : "#" + rank, tied,
                belowPrev: i > 0 ? orderTxt(between(i - 1)) : null, aboveNext: orderTxt(between(i))});
    }
    const shownAll = sec.items.length && !sec.inconsistent && !sec.expired.length;
    return {items: out, cutoff: shownAll ? orderTxt(sec.trace.cutoff) : null, excluded: sec.trace.excluded_after_cutoff || []};
  }
  /* One pairwise explanation of the engine (explain_order): {tie, text}. A name tie-break is a tie on evidence. */
  function orderTxt(o) {
    if (!o || !o.rule) return null;
    const f = o.rule[0];
    if (TIE_FIELDS[f]) return {tie: true, field: f, text: "tied on every evidence rule; listed by " + (f === "id" ? "identifier" : f + " name")};
    const a = o.above && typeof o.above === "object" ? o.above[f] : null, b = o.below && typeof o.below === "object" ? o.below[f] : null;
    const fmtV = (v) => v == null ? "unknown" : f === "signal_age_s" ? durTxt(v) : /rate|risk|carry|basis/.test(f) ? pct(v) : String(v);
    return {tie: false, field: f, text: (RANK_FIELD_TXT[f] || f) + " (" + fmtV(a) + " vs " + fmtV(b) + ")",
            above: o.above && o.above.id, below: o.below && o.below.id};
  }

  /* What a card needs from one candidate, extracted from its trace and fields (never derived). */
  function cardModel(c) {
    const sig = gate(c, "SIGNAL", "bar_close_t") || gate(c, "SIGNAL");
    const liq = gate(c, "EXECUTION_LIQUIDITY"), after = gate(c, "PORTFOLIO_AFTER"), fund = gate(c, "FUNDING");
    const prop = gate(c, "PROPOSED_TRADE");
    const ex = c.explanation || {};
    const pl = c.placement || {};
    return {
      id: c.id, type: c.type, typeLabel: TYPE_LABEL[c.type] || c.type, asset: c.asset, state: c.state, side: sideOf(c.direction),
      strategy: c.strategy || null, blocking_step: c.blocking_step || null,
      blockers: c.blockers || [], caps: c.caps || [], missing: c.missing_authorities || [], warnings: c.warnings || [],
      evidence: (c.positive_evidence || []).map((e) => ({type: e.type, label: EVIDENCE_LABEL[e.type] || titleCase(e.type), raw: e})),
      signal: sig && sig.input && "bar_close_t" in sig.input ? {kind: sig.input.kind, age_s: sig.input.age_s, timeframe: sig.input.timeframe,
                                                                stop_pct: sig.input.stop_pct, result: sig.result} : null,
      liquidity: liq ? {result: liq.result, code: liq.code, state: (liq.input || {}).state, value: (liq.input || {}).observed_value,
                        threshold: (liq.input || {}).threshold, legs: (liq.input || {}).legs || null} : null,
      slippage: prop && prop.input && isNum(prop.input.expected_slippage) ? prop.input.expected_slippage : null,
      after: after ? {result: after.result, code: after.code, state: (after.input || {}).state} : null,
      funding: fund ? {result: fund.result, code: fund.code, input: fund.input} : null,
      why_trade: ex.why_trade || null, to_become_trade: ex.to_become_trade || [],
      section: pl.section || null, rank: pl.section ? pl.rank : null, placement_reason: pl.reason || null,
      valid_until: c.valid_until, tier: c.authority_tier || null, probation: c.probation || null, proposal: c.proposal || null,
    };
  }
  /* A TRADE's plan, exactly as the engine's Phase 10 proposal states it (entry is the current mark; the stop and the size
     are the governed proposal's; the account is the page's default sizing, labelled as such). Nothing is recomputed. */
  function planHtml(m) {
    const p = m.proposal || {};
    if (m.state !== "TRADE" || m.type !== DECISION.directional || !isNum(p.mark) || !isNum(p.stop) || p.mark <= 0) return "";
    const parts = ['Enter near <b>' + esc(price(p.mark)) + '</b>', 'Stop <b>' + esc(price(p.stop)) + '</b> <span class="muted">(' + esc(pct(Math.abs(p.mark - p.stop) / p.mark)) + ' away)</span>'];
    if (isNum(p.risk_fraction)) parts.push('Risk <b>' + esc(pct(p.risk_fraction)) + '</b> of the account' + (isNum(p.size_multiplier) && p.size_multiplier < 1 ? ' <span class="muted">(' + esc(String(p.size_multiplier)) + '× the page size)</span>' : ""));
    if (isNum(p.notional) && isNum(p.equity)) parts.push('Size <b>' + esc(usd(p.notional)) + '</b> <span class="muted">on a ' + esc(usd(p.equity)) + ' page account' + (isNum(p.stop_risk_usd) ? ', ' + esc(usd(p.stop_risk_usd)) + ' at the stop' : "") + '</span>');
    const pr = m.probation || {};
    const sig = m.signal || {};
    if (m.tier === "PROBATION" && isNum(pr.entry_window_s) && isNum(sig.age_s)) parts.push('Entry window <b>' + esc(durTxt(Math.max(0, pr.entry_window_s - sig.age_s))) + ' left</b>');
    return '<div class="opp-plan" aria-label="Trade plan">' + parts.map((x) => '<span>' + x + '</span>').join("") + '</div>';
  }
  /* The archive evidence and the live forward test behind a probation side, as the bound evidence states them. */
  function evidenceHtml(m) {
    const pr = m.probation;
    if (!pr || m.type !== DECISION.directional) return "";
    const e = pr.expectation || {}, f = pr.forward_test || {}, ho = pr.holdout || {};
    let h = '<p class="opp-sub"><b>Archive evidence:</b> ';
    h += isNum(e.out_of_sample_mean_R) ? esc((e.out_of_sample_mean_R >= 0 ? "+" : "") + e.out_of_sample_mean_R.toFixed(2)) + 'R per trade out of sample' +
      (isNum(e.out_of_sample_lower_95) && isNum(e.out_of_sample_upper_95) ? ' (95% interval ' + esc(e.out_of_sample_lower_95.toFixed(2)) + ' to ' + esc(e.out_of_sample_upper_95.toFixed(2)) + 'R' + (isInt(ho.n) ? ', ' + ho.n + ' trades before Oct 2023' : "") + ')' : "") : "not stated";
    h += isNum(e.all_windows_mean_R) ? '; ' + esc((e.all_windows_mean_R >= 0 ? "+" : "") + e.all_windows_mean_R.toFixed(2)) + 'R over every window' + (isInt(pr.archive_trades) ? ' (' + pr.archive_trades + ' trades, delisted coins included)' : "") : "";
    h += '. R is the result in units of the stop distance, after costs and funding. Past results do not promise future ones.</p>';
    h += '<p class="opp-sub"><b>Live forward test:</b> ' + (isInt(f.closed) ? f.closed + ' closed trade' + (f.closed === 1 ? "" : "s") + (isNum(f.mean_R) ? ', mean ' + esc((f.mean_R >= 0 ? "+" : "") + f.mean_R.toFixed(2)) + 'R' : "") +
      (isNum(f.band_p05_mean_R) ? ' · demoted below ' + esc(f.band_p05_mean_R.toFixed(2)) + 'R after ' + f.band_trades + ' trades' : isInt(f.min_trades) ? ' · checked against the archive band from ' + f.min_trades + ' trades' : "") : "no live record yet") + '.</p>';
    return h;
  }
  /* The one-line reason a card shows: the engine's own codes, worded. */
  function keyReason(m) {
    if (m.state === "TRADE") return "All required desk gates currently pass.";
    if (m.state === "AVOID") return "Rejected at " + (STEP_LABEL[m.blocking_step] || m.blocking_step) + ": " + m.blockers.map(codeLabel).join(", ") + ".";
    const codes = m.caps.concat(m.missing);
    return codes.length ? "Not trade-ready: " + codes.map(codeLabel).join(", ") + "." : "Not trade-ready.";
  }
  /* "What needs to change": explanation.to_become_trade, step by step, with the engine's rule for each. */
  function needs(c) {
    return ((c.explanation || {}).to_become_trade || []).filter((x) => x && x.step).map((x) => ({
      step: x.step, stepLabel: STEP_LABEL[x.step] || x.step, code: x.code || null, codeLabel: x.code ? codeLabel(x.code) : null, rule: x.rule || ""}));
  }

  /* Trace rows: INPUT -> RULE -> RESULT -> EFFECT, the artifact's own entries in its own order (decision trace plus the
     placement trace). Result and effect are shown verbatim; only the input is summarised for reading. */
  function traceRows(c) {
    const rows = [];
    for (const g of ((c && c.trace) || []).concat(((c && c.placement) || {}).trace || [])) {
      if (!g || typeof g !== "object") continue;
      const rv = RESULT_VIEW[g.result] || {label: String(g.result), cls: "r-info", mark: "·"};
      rows.push({step: g.step, stepLabel: STEP_LABEL[g.step] || String(g.step), input: inputTxt(g.step, g.input), rule: String(g.rule || ""),
                 result: g.result, resultLabel: rv.label, resultCls: rv.cls, mark: rv.mark, code: g.code || null,
                 codeLabel: g.code ? codeLabel(g.code) : null, effect: String(g.effect || "")});
    }
    return rows;
  }
  /* The gate strip: every decision-trace entry before the final state, in order, by its result. */
  function strip(c) {
    return ((c && c.trace) || []).filter((g) => g && g.step !== "DECISION_STATE")
      .map((g) => ({step: g.step, label: STEP_LABEL[g.step] || g.step, result: g.result, code: g.code || null}));
  }
  function stripSummary(s) {
    const n = (r) => s.filter((x) => x.result === r).length;
    const parts = [n("PASS") + " pass"];
    if (n("CAP")) parts.push(n("CAP") + " watch cap");
    if (n("MISSING")) parts.push(n("MISSING") + " missing");
    if (n("FAIL")) parts.push(n("FAIL") + " fail" + " (" + s.filter((x) => x.result === "FAIL").map((x) => x.label).join(", ") + ")");
    return "Gates: " + parts.join(", ");
  }
  function kv(o, keys) {
    return keys.filter((k) => o[k] != null && o[k] !== "" && !(Array.isArray(o[k]) && !o[k].length)).map((k) => k.replace(/_/g, " ") + " " + fmtAny(k, o[k])).join(" · ");
  }
  function fmtAny(k, v) {
    if (Array.isArray(v)) return v.map((x) => typeof x === "object" ? JSON.stringify(x) : String(x)).join(", ");
    if (v && typeof v === "object") return JSON.stringify(v);
    if (typeof v === "number") {
      if (/_ts$|_t$/.test(k)) return utcTxt(v);
      if (/age_s$/.test(k)) return durTxt(v);
      if (/volume|value|usd|threshold/.test(k)) return usd(v);
      if (/rate_8h|spread_8h/.test(k)) return rate8h(v);
      if (/risk|pct|fraction|basis|carry|costs|slippage|fees/.test(k)) return pct(v);
      if (/leverage/.test(k)) return lev(v);
      return Math.abs(v) >= 1000 || Number.isInteger(v) ? String(v) : String(+v.toPrecision(6));
    }
    return String(v);
  }
  function inputTxt(step, i) {
    if (i == null) return "—";
    if (typeof i !== "object") return String(i);
    switch (step) {
      case "DISCOVERY":
        if (i.stale_inputs) return "Stale inputs: " + i.stale_inputs.join(", ");
        return [i.stage ? "stage " + i.stage : null, i.venues ? "venues " + [].concat(i.venues).join(", ") : null,
                i.fallback_universe ? "fallback universe" : null].filter(Boolean).join(" · ") || "—";
      case "IDENTITY": return [i.state, i.reason].filter(Boolean).join(" · ") || "—";
      case "ECONOMIC_EXPOSURE": return "flags " + ((i.flags || []).join(", ") || "none") + (i.exposure_check_state ? " · checks " + i.exposure_check_state : "");
      case "VENUE_HEALTH": return "data quality " + (i.data_quality || "unknown") + ((i.venues_failed || []).length ? " · unavailable venues " + i.venues_failed.join(", ") : "");
      case "SIGNAL":
        if ("bar_close_t" in i) return [i.strategy, sideOf(i.direction), i.kind ? String(i.kind).toLowerCase() : null,
          i.timeframe ? i.timeframe + " bar closed " + (isNum(i.age_s) ? durTxt(i.age_s) + " before the decision" : "at an unknown time") : null,
          isNum(i.stop_pct) ? "stop " + pct(i.stop_pct) : null].filter(Boolean).join(" · ");
        if (i.open_positions) return "already open: " + i.open_positions.join(", ");
        if (i.evidence) return "evidence: " + i.evidence.map((e) => EVIDENCE_LABEL[e] || titleCase(e)).join(", ");
        if ("spread_8h" in i) return "spread " + rate8h(i.spread_8h) + " · legs " + (i.legs || []).join(" / ") +
          ((i.unhealthy_excluded || []).length ? " · unhealthy venues excluded " + i.unhealthy_excluded.join(", ") : "");
        return kv(i, Object.keys(i));
      case "STRATEGY_AUTHORITY":
        return i.strategy ? i.strategy + ": " + (i.deployment_state || "?") + " / " + (i.research_state || "?") +
          (i.tier ? " · tier " + i.tier : "") + ((i.confirmed_sides || []).length ? " · confirmed " + i.confirmed_sides.join(", ") : "") +
          (isNum(i.entry_window_s) ? " · entry window " + durTxt(i.entry_window_s) : "") : "no governed strategy";
      case "EXECUTION_LIQUIDITY":
        if (i.legs) return i.legs.map((l) => l[0] + " " + l[1] + (l[2] ? " (" + l[2] + ")" : "")).join(" · ") + (isNum(i.threshold) ? " · gate " + usd(i.threshold) : "");
        return (i.state || "unknown") + (isNum(i.observed_value) ? " · 24h trade-DEX volume " + usd(i.observed_value) : "") + (isNum(i.threshold) ? " vs gate " + usd(i.threshold) : "");
      case "FUNDING":
        if (i.long && i.short) return "long " + i.long.venue + " " + rate8h(i.long.rate_8h) + " · short " + i.short.venue + " " + rate8h(i.short.rate_8h) +
          " · carry " + pct(i.carry) + " − costs " + pct(i.costs) + " = net " + pct(i.net_carry) + " over " + i.holding_hours + " h";
        return (i.state || "unknown") + (isNum(i.rate_8h) ? " · " + rate8h(i.rate_8h) + (i.venue ? " on " + i.venue : "") : "") + (i.rule ? " · " + titleCase(i.rule) : "");
      case "PORTFOLIO_BEFORE": case "PORTFOLIO_AFTER":
        return [i.state, (i.breached || []).length ? "breached " + i.breached.map((k) => LIMIT_LABEL[k] || k).join(", ") : null,
                isNum(i.missing) ? i.missing + " missing authorities" : (i.missing || []).length ? i.missing.length + " missing authorities" : null].filter(Boolean).join(" · ") || "—";
      case "PROPOSED_TRADE":
        if ("basis_abs" in i) return "basis " + pct(i.basis_abs) + " (max " + pct(i.max_basis) + ")";
        return [isNum(i.mark) ? "mark " + price(i.mark) : null, isNum(i.stop) ? "stop " + price(i.stop) : null,
                isNum(i.leverage) ? "leverage " + lev(i.leverage) : null, isNum(i.stop_risk) ? "stop risk " + pct(i.stop_risk) : null,
                isNum(i.expected_slippage) ? "slippage " + pct(i.expected_slippage) : null, i.sizing_basis ? titleCase(i.sizing_basis) : null,
                i.status].filter(Boolean).join(" · ") || "—";
      case "RISK_LIMITS":
        return ["breached " + ((i.breached || []).map((k) => LIMIT_LABEL[k] || k).join(", ") || "none"),
                (i.approaching || []).length ? "approaching " + i.approaching.map((k) => LIMIT_LABEL[k] || k).join(", ") : null].filter(Boolean).join(" · ");
      case "DECISION_STATE":
        return ["fail " + ((i.fail || []).join(", ") || "none"), "cap " + ((i.cap || []).join(", ") || "none"), "missing " + ((i.missing || []).join(", ") || "none")].join(" · ");
      case "SECTION_PLACEMENT": return "candidate for " + (SECTION_LABEL[i.candidate_for] || i.candidate_for || "no section");
      case "RANKING": return rankInputs(i);
      default: return kv(i, Object.keys(i));
    }
  }

  /* A candidate's ranking inputs in words (the evidence fields first; the name tie-breaks are not evidence). */
  function rankInputs(i) {
    const out = [];
    if ("signal_kind_order" in i) out.push(i.signal_kind_order === 0 ? "new signal" : "active signal");
    if (isNum(i.signal_age_s)) out.push("signal age " + durTxt(i.signal_age_s));
    if (isNum(i.slippage_rate)) out.push("slippage tier " + pct(i.slippage_rate));
    if (isNum(i.after_executable_risk)) out.push("executable risk after " + pct(i.after_executable_risk));
    if (isNum(i.primary_evidence_count)) out.push(i.primary_evidence_count + " primary evidence");
    if (isNum(i.evidence_count)) out.push(i.evidence_count + " evidence in all");
    if (isNum(i.outstanding_blockers)) out.push(i.outstanding_blockers + " outstanding blocker" + (i.outstanding_blockers === 1 ? "" : "s"));
    if ("net_carry" in i) out.push("net carry " + pct(i.net_carry));
    if ("basis_abs" in i) out.push("basis " + pct(i.basis_abs));
    for (const k of Object.keys(i)) if (i[k] == null && !TIE_FIELDS[k]) out.push(k.replace(/_/g, " ") + " unknown");
    return out.join(" · ") || "—";
  }

  // ------------------------------------------------------------------ desk-level views (extraction and counting)
  function counts(doc) {
    const m = (doc && doc.market_summary) || {};
    const st = m.opportunity_states || {};
    return {trade: st.TRADE, watch: st.WATCH, avoid: st.AVOID, opportunities: m.opportunities, discovered: m.discovered_assets,
            evaluated: m.evaluated_assets, signals: m.current_strategy_signals, byType: m.opportunity_states_by_type || {},
            identityBlocked: m.identity_blocked_assets, executionBlocked: m.execution_blocked_assets};
  }
  /* System state the artifact records: unavailable venues, a degraded or fallback discovery, major missing authorities.
     "Cannot evaluate reliably" is reported apart from "no opportunity". */
  function degradations(doc) {
    const m = (doc && doc.market_summary) || {}, vd = m.venue_degradation || {}, out = [];
    if ((vd.venues_failed || []).length) out.push({kind: "venue", text: (vd.venues_failed.length === 1 ? "1 venue unavailable: " : vd.venues_failed.length + " venues unavailable: ") + vd.venues_failed.join(", "),
                                                   detail: "Its contracts are not part of this decision."});
    if (vd.fallback_universe) out.push({kind: "discovery", text: "Discovery is running on its fallback universe", detail: "Discovery is degraded: every asset's DISCOVERY gate is MISSING."});
    else if (vd.coverage_state && vd.coverage_state !== "FULL" && !(vd.venues_failed || []).length) out.push({kind: "coverage", text: "Market coverage " + String(vd.coverage_state).toLowerCase(), detail: ""});
    const pf = ((doc && doc.portfolio) || {}).binding || {};
    if (pf.consistent === false) out.push({kind: "portfolio", text: "Portfolio binding inconsistent", detail: "The decision's book state differs from the Phase 10 audit state."});
    return out;
  }
  /* Why nothing is trade-ready, counted from the directional decisions in this document (no reason is assumed). */
  function zeroTrade(doc) {
    const dir = ((doc && doc.candidates) || []).filter((c) => c && c.type === DECISION.directional);
    const prim = new Map(), also = new Map();
    const bump = (m, k) => m.set(k, (m.get(k) || 0) + 1);
    for (const c of dir) {
      if (c.state === "AVOID") {
        // the engine's blocking step and its code (blockers are the FAIL codes in trace order: the first is that step's)
        bump(prim, "AVOID|" + (c.blocking_step || "") + "|" + ((c.blockers || [])[0] || ""));
        for (const b of (c.blockers || []).slice(1).concat(c.caps || [], c.missing_authorities || [])) bump(also, b);
      } else if (c.state === "WATCH") {
        for (const b of (c.caps || []).concat(c.missing_authorities || [])) bump(prim, "WATCH||" + b);
      }
    }
    const rows = Array.from(prim.entries()).map(([k, n]) => { const [st, step, code] = k.split("|");
      return {state: st, step: step || null, stepLabel: step ? STEP_LABEL[step] || step : null, code, label: code ? codeLabel(code) : "", count: n}; })
      .sort((a, b) => b.count - a.count || (a.code < b.code ? -1 : 1));
    const alsoRows = Array.from(also.entries()).map(([code, n]) => ({code, label: codeLabel(code), count: n}))
      .sort((a, b) => b.count - a.count || (a.code < b.code ? -1 : 1));
    const pf = ((doc && doc.portfolio) || {}).phase10 || {};
    const portfolioBlocked = dir.filter((c) => (c.blockers || []).includes("PORTFOLIO_LIMIT_BREACHED")).length;
    return {signals: dir.length, trade: dir.filter((c) => c.state === "TRADE").length, watch: dir.filter((c) => c.state === "WATCH").length,
            avoid: dir.filter((c) => c.state === "AVOID").length, reasons: rows, also: alsoRows, portfolioState: pf.state || null, portfolioBlocked};
  }
  /* AVOID across every type, by rejection step and code (TODAY summarises them instead of listing hundreds). */
  function avoidSummary(doc) {
    const by = new Map();
    let n = 0;
    for (const c of (doc && doc.candidates) || []) {
      if (!c || c.state !== "AVOID") continue;
      n++;
      const k = (c.type || "") + "|" + (c.blocking_step || "") + "|" + ((c.blockers || [])[0] || "");
      by.set(k, (by.get(k) || 0) + 1);
    }
    return {total: n, rows: Array.from(by.entries()).map(([k, count]) => { const [type, step, code] = k.split("|");
      return {type, typeLabel: TYPE_LABEL[type] || type, step, stepLabel: STEP_LABEL[step] || step, code, label: code ? codeLabel(code) : "", count}; })
      .sort((a, b) => b.count - a.count || (a.type < b.type ? -1 : 1))};
  }
  /* The Phase 10 summary the decision carries (doc.portfolio.phase10), labelled; missing values stay missing. */
  function portfolioView(p10) {
    const p = p10 && typeof p10 === "object" ? p10 : {};
    const ex = p.exposure || {}, lim = p.limits || {}, stress = p.stress || {};
    const limits = LIMIT_ORDER.filter((k) => lim[k]).concat(Object.keys(lim).filter((k) => !LIMIT_LABEL[k])).map((k) => ({
      key: k, label: LIMIT_LABEL[k] || titleCase(k), metric: lim[k].metric, limit: lim[k].limit, status: lim[k].status,
      metricTxt: limitValue(k, lim[k].metric), limitTxt: limitValue(k, lim[k].limit)}));
    let worst = null;
    for (const [k, v] of Object.entries(stress)) if (isNum(v) && (!worst || v > worst.loss)) worst = {key: k, label: STRESS_LABEL[k] || titleCase(k), loss: v};
    const miss = p.missing_authorities || [];
    const groups = new Map();
    for (const m of miss) { const code = String(m).split(":")[0]; groups.set(code, (groups.get(code) || 0) + 1); }
    return {state: p.state || null, view: PF_VIEW[p.state] || PF_VIEW.UNEVALUABLE, as_of: p.as_of, positions: p.positions,
            gross: ex.gross_leverage, net: ex.net_leverage, long: ex.long_leverage, short: ex.short_leverage,
            exec: lim.max_executable_risk || null, worst, limits,
            breached: (p.breached || []).map((k) => ({key: k, label: LIMIT_LABEL[k] || titleCase(k)})),
            approaching: (p.approaching || []).map((k) => ({key: k, label: LIMIT_LABEL[k] || titleCase(k)})),
            missingCount: isInt(p.missing_authority_count) ? p.missing_authority_count : miss.length,
            missingGroups: Array.from(groups.entries()).map(([code, n]) => ({code, label: codeLabel(code), count: n})),
            stress: Object.entries(stress).map(([k, v]) => ({key: k, label: STRESS_LABEL[k] || titleCase(k), loss: v})),
            policy_hash: p.policy_hash || null, policy_review_status: p.policy_review_status || null};
  }
  /* Change explanation, only from the artifact's governed previous decision (never from browser state). */
  function changes(doc) {
    const ch = (doc && doc.changes) || {};
    if (!ch.previous_available) return {available: false, reason: ch.reason || "NO_PREVIOUS_PHASE11_AUTHORITY", note: ch.note || ""};
    const rows = (ch.changes || []).map((x) => {
      const asset = String(x.id || "").split(":")[1] || x.id;
      let text;
      if (x.change === "NEW_CANDIDATE") text = "new: " + (x.current_state || "?");
      else if (x.change === "NO_LONGER_A_CANDIDATE") text = "no longer a candidate (was " + (x.previous_state || "?") + ")";
      else if (x.previous_state !== x.current_state) text = x.previous_state + " → " + x.current_state;
      else if (x.previous_section !== x.current_section) text = x.current_section ? "entered " + (SECTION_LABEL[x.current_section] || x.current_section) : "removed from " + (SECTION_LABEL[x.previous_section] || x.previous_section);
      else text = "rank " + (x.previous_rank == null ? "–" : x.previous_rank) + " → " + (x.current_rank == null ? "–" : x.current_rank);
      const st = x.state_change_reason || {};
      return {id: x.id, asset, type: String(x.id || "").split(":")[0], text,
              added: (st.added || []).map(codeLabel), removed: (st.removed || []).map(codeLabel), raw: x};
    });
    return {available: true, previous_as_of: ch.previous_as_of, policy_changed: !!ch.policy_changed, rows};
  }

  // ------------------------------------------------------------------ HTML components (escaped strings)
  function stateChip(state, opt) {
    const v = STATE_VIEW[state] || STATE_VIEW.UNAVAILABLE;
    const txt = (opt && opt.text) || v.label;
    return '<span class="chip ' + v.cls + (opt && opt.big ? " chip-big" : "") + (opt && opt.quiet ? " chip-quiet" : "") + '"><span class="chip-mark" aria-hidden="true">' + v.mark + '</span>' + esc(txt) + '</span>';
  }
  function pfChip(state, opt) {
    const v = PF_VIEW[state] || PF_VIEW.UNEVALUABLE;
    return '<span class="chip ' + v.cls + (opt && opt.big ? " chip-big" : "") + '"><span class="chip-mark" aria-hidden="true">' + v.mark + '</span>' + esc(v.label) + '</span>';
  }
  function dirTag(side) {
    return side ? '<span class="dir dir-' + side + '">' + (side === "long" ? "Long" : "Short") + '</span>' : "";
  }
  function resultTag(r) {
    const v = RESULT_VIEW[r] || {label: String(r), cls: "r-info", mark: "·"};
    return '<span class="res ' + v.cls + '"><span aria-hidden="true">' + v.mark + '</span> ' + esc(v.label) + '</span>';
  }
  function gateStrip(c) {
    const s = strip(c);
    if (!s.length) return "";
    return '<span class="gates" role="img" aria-label="' + esc(stripSummary(s)) + '">' +
      s.map((g) => '<span class="g ' + (RESULT_VIEW[g.result] || RESULT_VIEW.INFO).cls + '" title="' + esc(g.label + ": " + (RESULT_VIEW[g.result] || {label: g.result}).label + (g.code ? " (" + g.code + ")" : "")) + '"></span>').join("") + '</span>';
  }
  function traceTable(c, doc) {
    const rows = traceRows(c);
    let h = '<div class="trace" role="table" aria-label="' + esc("Decision trace for " + c.id) + '">' +
      '<div class="trow thead" role="row"><span role="columnheader">Step</span><span role="columnheader">Checked</span><span role="columnheader">Rule</span><span role="columnheader">Result</span><span role="columnheader">Effect</span></div>';
    for (const r of rows) {
      h += '<div class="trow ' + r.resultCls + '" role="row"><span class="tstep" role="cell">' + esc(r.stepLabel) + '</span>' +
        '<span class="tin" role="cell"><span class="tlbl">Checked</span>' + esc(r.input) + '</span>' +
        '<span class="trule" role="cell"><span class="tlbl">Rule</span>' + esc(r.rule) + '</span>' +
        '<span class="tres" role="cell"><span class="tlbl">Result</span>' + resultTag(r.result) + (r.code ? '<small>' + esc(r.codeLabel) + ' <code>' + esc(r.code) + '</code></small>' : "") + '</span>' +
        '<span class="teff" role="cell"><span class="tlbl">Effect</span>' + esc(r.effect) + '</span></div>';
    }
    h += '</div>';
    const au = (doc && doc.authority) || {};
    h += '<details class="adv"><summary>Advanced</summary><dl class="advl">' +
      dl("Candidate", c.id) + dl("State", c.state + (c.blocking_step ? " (rejected at " + c.blocking_step + ")" : "")) +
      dl("Codes", [].concat(c.blockers || [], c.caps || [], c.missing_authorities || []).join(", ") || "none") +
      dl("Valid until", isInt(c.valid_until) ? utcTxt(c.valid_until) : "–") +
      (doc ? dl("Decision as of", utcTxt(doc.as_of)) + dl("Policy", (doc.policy_schema || "") + " " + (doc.policy_hash || "")) +
             dl("Implementation", doc.implementation_hash || "") + dl("Authority hash", au.authority_hash || "") : "") +
      '</dl></details>';
    return h;
  }
  const dl = (k, v) => '<dt>' + esc(k) + '</dt><dd>' + esc(v) + '</dd>';
  /* A Decision Trace disclosure; its rows are rendered on first open (bindTraces), so hundreds of rows never load. */
  function traceDetails(c, label) {
    return '<details class="tr" data-trace="' + esc(c.id) + '"><summary>' + esc(label || "Decision trace") + '</summary><div class="tr-body"></div></details>';
  }
  function bindTraces(rootEl, getDoc) {
    rootEl.addEventListener("toggle", (e) => {
      const d = e.target;
      if (!d || d.tagName !== "DETAILS" || !d.open || !d.dataset || !d.dataset.trace || d.dataset.filled) return;
      const doc = getDoc(), c = doc ? index(doc).byId.get(d.dataset.trace) : null;
      const body = d.querySelector(".tr-body");
      if (body) body.innerHTML = c ? traceTable(c, doc) : '<p class="muted">This decision is no longer in the loaded document.</p>';
      d.dataset.filled = "1";
    }, true);
  }
  function needsList(c) {
    const n = needs(c);
    if (!n.length) return "";
    return '<ul class="needs">' + n.map((x) => '<li><b>' + esc(x.stepLabel) + '</b>' + (x.codeLabel ? ': ' + esc(x.codeLabel) : "") +
      (x.rule ? '<small>' + esc(x.rule) + '</small>' : "") + '</li>').join("") + '</ul>';
  }
  /* The opportunity card, shared by Today and the Analyzer so the same candidate always looks the same.
     opt: {rank (a rankInfo item), asset (false to omit the name), link (Analyzer link)}. A direction is shown as a call
     only on a TRADE; on WATCH or AVOID it is the signal's side, said as such. */
  function oppCard(c, opt) {
    opt = opt || {};
    const m = cardModel(c), r = opt.rank || null, dir = c.type === DECISION.directional;
    const cls = "opp" + (c.state === "TRADE" ? " is-trade" : c.state === "WATCH" ? " is-watch" : " is-avoid");
    let h = '<article class="' + cls + '" data-cand="' + esc(c.id) + '" data-state="' + esc(c.state) + '" aria-label="' + esc(m.asset + ", " + m.typeLabel.toLowerCase() + ", " + (STATE_VIEW[c.state] || {}).label) + '">' +
      '<div class="opp-top">' + (r ? '<span class="opp-rank" title="' + (r.tied ? "Tied on evidence" : "Rank") + '">' + esc(r.label) + '</span>' : "") +
      (opt.asset === false ? '<span class="opp-type">' + esc(m.typeLabel) + '</span>' : '<span class="opp-asset">' + esc(m.asset) + '</span>');
    if (dir) h += (c.state === "TRADE" ? dirTag(m.side) : "") + '<span class="muted small">' + esc(m.strategy) + (c.state !== "TRADE" && m.side ? " · " + m.side + " signal, not a call" : "") + '</span>';
    else if (opt.asset !== false) h += '<span class="muted small">' + esc(m.typeLabel) + '</span>';
    h += stateChip(c.state) + (c.state === "TRADE" && TIER_VIEW[m.tier] ? '<span class="tag tier-' + esc(String(m.tier).toLowerCase()) + '" title="' + esc(TIER_VIEW[m.tier].line) + '">' + esc(TIER_VIEW[m.tier].label) + '</span>' : "") + '</div>';
    if (c.type === DECISION.emerging) h += '<p class="opp-why"><b>Why it is interesting:</b> ' + esc(m.evidence.map((e) => e.label).join(" · ") || "–") + '</p><p class="opp-sub">' + esc(keyReason(m)) + '</p>';
    else h += '<p class="opp-why">' + esc(keyReason(m)) + '</p>';
    h += planHtml(m);
    // a TRADE's distinguishing qualification: the engine's own strategy-authority rule (explanation.why_trade)
    const qual = c.state === "TRADE" && Array.isArray(m.why_trade) ? m.why_trade.find((x) => x && x.step === "STRATEGY_AUTHORITY") : null;
    if (qual && qual.rule) h += '<p class="opp-sub">Strategy authority: ' + esc(qual.rule) + '</p>';
    if (c.state === "TRADE" || (m.probation && c.state === "WATCH")) h += evidenceHtml(m);
    const facts = [];
    if (dir && m.signal) facts.push('Signal <b>' + esc(String(m.signal.kind || "").toLowerCase()) + ' · ' + esc(durTxt(m.signal.age_s)) + ' old</b>');
    if (m.liquidity && !m.liquidity.legs) facts.push('Execution <b>' + (m.liquidity.state === "KNOWN" ? esc(usd(m.liquidity.value)) + ' 24h' : esc(titleCase(m.liquidity.state || "unknown"))) +
      (m.slippage != null ? ' · slippage ' + esc(pct(m.slippage)) : "") + '</b>');
    if (dir && m.after && m.after.state) facts.push('Portfolio after <b>' + esc((PF_VIEW[m.after.state] || {label: m.after.state}).label) + '</b>');
    if (c.type === DECISION.funding && c.legs) facts.push('Long <b>' + esc((c.legs.long || {}).venue) + '</b> · short <b>' + esc((c.legs.short || {}).venue) + '</b> · net carry <b>' + esc(pct(c.net_carry)) + '</b>');
    if (m.warnings.length) facts.push('Warnings <b>' + esc(Array.from(new Set(m.warnings.map((w) => codeLabel(String(w).split(":")[0])))).join(", ")) + '</b>');
    if (facts.length) h += '<div class="opp-facts">' + facts.map((f) => '<span>' + f + '</span>').join("") + '</div>';
    if (c.state === "WATCH" && needs(c).length) h += '<div class="small" style="margin-top:8px"><b>What needs to change</b>' + needsList(c) + '</div>';
    h += '<div class="opp-gates">' + gateStrip(c) + '<span>' + esc(stripSummary(strip(c))) + '</span></div>';
    if (r) {
      const t = r.tied ? "Tied on every evidence rule with the neighbouring item; listed by name, not by strength." : r.aboveNext ? "Above the next: " + r.aboveNext.text + "." : "";
      if (t) h += '<p class="rankwhy">' + esc(t) + '</p>';
    }
    h += '<div class="opp-act">' + traceDetails(c) + (opt.link ? '<a href="analyze.html?coin=' + encodeURIComponent(m.asset) + '">Open in Analyzer</a>' : "") + '</div></article>';
    return h;
  }
  /* The fail-closed panel every desk page shows when the decision is missing, malformed or stale. */
  function failClosed(A, now) {
    const t = A.status === "STALE" ? "Decision expired — waiting for the next governed scan."
      : A.status === "MALFORMED" ? "The decision file is unreadable — nothing on the desk is actionable."
      : "No current decision is loaded — nothing on the desk is actionable.";
    const d = A.status === "STALE" ? "The last decision (" + utcTxt(A.as_of) + ") was valid until " + utcTxt(A.valid_until) + ", " + agoTxt(A.valid_until, now) + ". The desk does not extend it."
      : A.status === "MALFORMED" ? "It is not a valid " + DECISION.schema + " document, so nothing is shown from it."
      : "The decision file could not be loaded. Opportunities appear again when the next governed scan publishes one.";
    return '<div class="failclosed" role="alert"><p class="fc-t">' + stateChip("UNAVAILABLE") + ' ' + esc(t) + '</p><p class="fc-d">' + esc(d) + '</p></div>';
  }
  function freshness(A, now) {
    if (A.status === "AVAILABLE") {
      const left = A.valid_until - now;
      return '<span class="fresh ok">Decision of ' + esc(timeTxt(A.as_of)) + ' <span class="muted">· ' + esc(agoTxt(A.as_of, now)) +
        ' · current for ' + esc(durTxt(left)) + ' more</span></span>';
    }
    if (A.status === "STALE") return '<span class="fresh bad">Decision expired at ' + esc(timeTxt(A.valid_until)) + '</span>';
    return '<span class="fresh bad">' + (A.status === "MALFORMED" ? "Decision unreadable" : "No decision loaded") + '</span>';
  }

  // ------------------------------------------------------------------ page views (pure: HTML strings the pages only bind)
  const sep = '<span class="sep" aria-hidden="true"></span>';
  /* The desk status line: freshness, coverage, state counts, portfolio, the first degradation. */
  function vStatus(A, now, kind) {
    if (A.status !== "AVAILABLE") return {bad: true, html: freshness(A, now) + '<span class="fact why">' + esc(A.reason || "") + '</span>'};
    const doc = A.doc, c = counts(doc), pv = portfolioView(((doc.portfolio || {}).phase10)), deg = degradations(doc), live = section(doc, "best_trades_now", now).count;
    let h = freshness(A, now);
    if (kind === "funding") {
      const t = c.byType.FUNDING_SPREAD || {};
      h += sep + '<span class="fact"><b>' + ((t.WATCH || 0) + (t.AVOID || 0) + (t.TRADE || 0)) + '</b> spreads evaluated</span><span class="fact counts">' +
        stateChip("WATCH", {text: "Watch " + (t.WATCH || 0), quiet: true}) + stateChip("AVOID", {text: "Avoid " + (t.AVOID || 0), quiet: true}) + '</span>';
    } else if (kind === "portfolio") {
      h += sep + '<span class="fact">Portfolio ' + pfChip(pv.state) + '</span><span class="fact"><b>' + esc(pv.positions == null ? "–" : pv.positions) + '</b> open positions</span>';
    } else {
      h += sep + '<span class="fact"><b>' + esc(c.discovered) + '</b> assets discovered · <b>' + esc(c.opportunities) + '</b> opportunities evaluated</span>' + sep +
        '<span class="fact counts">' + stateChip("TRADE", {text: "Trade " + c.trade, quiet: !(c.trade > 0 && live > 0)}) + stateChip("WATCH", {text: "Watch " + c.watch, quiet: true}) +
        stateChip("AVOID", {text: "Avoid " + c.avoid, quiet: true}) + '</span>' + sep + '<span class="fact">Portfolio ' + pfChip(pv.state) + '</span>';
    }
    if (deg.length) h += sep + '<span class="fact"><span class="tag warn">' + esc(deg[0].text) + (deg.length > 1 ? " +" + (deg.length - 1) : "") + '</span></span>';
    return {bad: false, html: h};
  }
  const cutoffNote = (R, what) => R.cutoff ? '<p class="note">More ' + what + ' qualify than the section shows (at most five); the next one ranks lower on ' + esc(R.cutoff.text) + '.</p>' : "";
  const inconsistentNote = (sec) => sec.inconsistent ? '<p class="note" role="alert">' + sec.inconsistent + ' item' + (sec.inconsistent === 1 ? " in this section was" : "s in this section were") +
    ' not shown: ' + (sec.inconsistent === 1 ? "it does" : "they do") + ' not agree with the decision file\'s own section rules (state, type, eligibility, healthy legs), so the file is inconsistent.</p>' : "";

  const expiredNote = (sec) => sec.expired.length ? '<p class="note" role="status">' + sec.expired.length + (sec.expired.length === 1 ? " decision in this section has" : " decisions in this section have") +
    ' passed its own valid-until time (' + esc(timeTxt(Math.min.apply(null, sec.expired.map((x) => x.valid_until)))) + ') and ' + (sec.expired.length === 1 ? "is" : "are") + ' not shown. The desk does not extend a decision; the next governed scan re-decides it.</p>' : "";

  /* Which strategy sides may produce a TRADE at all (decision.strategy_tiers), so an empty section says what to expect. */
  function tiersNote(doc) {
    const t = doc && doc.strategy_tiers;
    if (!t || typeof t !== "object") return "";
    const rows = [];
    for (const x of t.FULL || []) rows.push(esc(x.strategy) + " (requalified)");
    for (const x of t.PROBATION || []) {
      const sides = Object.keys(x.sides || {}).sort();
      const failed = sides.filter((s) => (x.sides[s] || {}).forward_test_state === "FAILED");
      rows.push(esc(x.strategy) + " " + esc(sides.join(" and ")) + " (probation, " + esc(String(x.risk_multiplier)) + "× size" +
                (failed.length ? "; demoted by its forward test: " + esc(failed.join(", ")) : "") + ")");
    }
    if (!rows.length) return '<p class="e-d">No strategy side is authorized to trade yet, so this section stays empty until one is.</p>';
    const daily = (t.FULL || []).concat(t.PROBATION || []).some((x) => x.timeframe === "1d");
    return '<p class="e-d">Authorized to trade: ' + rows.join("; ") + '. A trade appears here only when one of them has a fresh signal and every other gate passes.' +
      (daily ? " Daily strategies decide at the 00:00 UTC close." : "") + '</p>';
  }
  /* The governed book behind the Phase 10 gates, and the legacy paper positions that no longer gate anything. */
  function governedNote(doc) {
    const g = (doc && doc.portfolio || {}).governed, full = (doc && doc.portfolio || {}).full_paper_book;
    if (!g || typeof g !== "object" || !isInt(g.governed_positions)) return "";
    const n = g.governed_positions, x = isInt(g.excluded_paper_positions) ? g.excluded_paper_positions : null;
    return '<p class="note">Governed book: ' + n + ' position' + (n === 1 ? "" : "s") + ' of trade-authorized strategy sides.' +
      (x ? ' ' + x + ' legacy paper position' + (x === 1 ? " is" : "s are") + ' a diagnostic only' + (full && PF_VIEW[full.state] ? ' (that book: ' + esc(PF_VIEW[full.state].label.toLowerCase()) + ')' : "") + ' and do' + (x === 1 ? "es" : "") + ' not gate trades.' : "") + '</p>';
  }

  /* TODAY. raw: the loaded decision (or null / "MALFORMED"). Returns every region's HTML; nothing is decided here. */
  function vToday(raw, now) {
    const A = authority(raw, now), st = vStatus(A, now, "today");
    const out = {status: A.status, statusHtml: st.html, statusBad: st.bad, bestN: "", best: "", emN: "", emerging: "", emHidden: true,
                 avN: "", avoided: "", avHidden: true, pf: "", fund: "", sys: "", ver: ""};
    if (A.status !== "AVAILABLE") {
      out.best = failClosed(A, now);
      out.pf = out.fund = '<p class="muted small">Shown again when a current decision loads.</p>';
      out.sys = '<p class="small">' + esc(A.reason || "") + '</p>';
      return out;
    }
    const doc = A.doc;
    // Best trades now: decision.best_trades_now only, at most five, never filled
    const sec = section(doc, "best_trades_now", now), R = rankInfo(doc, "best_trades_now", now);
    out.bestN = sec.count + " of up to " + sec.max;
    if (sec.count) {
      out.best = '<div class="cards">' + sec.items.map((it, i) => oppCard(it.cand, {rank: R.items[i], link: true})).join("") + '</div>' + cutoffNote(R, "trades") + expiredNote(sec) + inconsistentNote(sec);
    } else if (sec.expired.length) {
      out.best = '<div class="empty"><p class="e-t">Decision expired — waiting for the next governed scan.</p><p class="e-d">' + sec.expired.length + ' trade decision' + (sec.expired.length === 1 ? "" : "s") +
        ' in this file passed ' + (sec.expired.length === 1 ? "its" : "their") + ' own valid-until time (' + esc(timeTxt(Math.min.apply(null, sec.expired.map((x) => x.valid_until)))) + '). Nothing is trade-ready until the next governed scan re-decides ' + (sec.expired.length === 1 ? "it" : "them") + '.</p></div>' + inconsistentNote(sec);
    } else {
      const z = zeroTrade(doc);
      let h = '<div class="empty"><p class="e-t">No trade currently clears every desk gate.</p>' + tiersNote(doc);
      if (!z.signals) h += '<p class="e-d">No governed strategy has a current signal in this decision, so there is nothing to clear the gates.</p>';
      else {
        h += '<p class="e-d">From this decision: ' + z.signals + ' current strategy signal' + (z.signals === 1 ? "" : "s") + ', none trade-ready.</p>';
        if (z.portfolioState === "LIMIT_BREACHED" && z.portfolioBlocked) h += '<p class="blocker"><b>Portfolio limits are currently breached.</b> ' + z.portfolioBlocked + ' of ' + z.signals +
          ' signals were rejected because the portfolio would still breach a limit after the trade.</p>';
        h += '<ul class="reasons" aria-label="Why nothing is trade-ready">' + z.reasons.map((r) => '<li><span class="cnt">' + r.count + '</span><span>' +
          (r.state === "AVOID" ? "Rejected at " + esc(r.stepLabel) + ": " : "Capped: ") + esc(r.label) + '<small><code>' + esc(r.code) + '</code></small></span></li>').join("") + '</ul>';
        if (z.also.length) h += '<p class="note">Also on the same signals: ' + z.also.map((x) => esc(x.label) + " (" + x.count + ")").join("; ") + '.</p>';
      }
      out.best = h + '</div>' + inconsistentNote(sec);
    }
    // Emerging opportunities: WATCH observations, never trades
    const em = section(doc, "emerging_opportunities", now), ER = rankInfo(doc, "emerging_opportunities", now);
    out.emHidden = false;
    out.emN = em.count ? em.count + " to watch · not trade-ready" : "none";
    out.emerging = em.count ? '<div class="cards">' + em.items.map((it, i) => oppCard(it.cand, {rank: ER.items[i], link: true})).join("") + '</div>' + cutoffNote(ER, "observations") + expiredNote(em) + inconsistentNote(em)
      : '<div class="empty"><p class="e-t">Nothing new to watch in this decision.</p><p class="e-d">' + esc(em.why_fewer || "") + '</p></div>' + expiredNote(em) + inconsistentNote(em);
    // Avoided: summarised, never listed card by card
    const av = avoidSummary(doc);
    out.avHidden = false;
    out.avN = av.total + " evaluated as Avoid";
    out.avoided = !av.total ? '<p class="muted">Nothing was rejected in this decision.</p>' :
      '<details class="more-d panel"><summary>What rejected them</summary><table class="tbl" style="margin-top:10px"><thead><tr><th>Opportunity</th><th>Rejected at</th><th>Reason</th><th class="num">Count</th></tr></thead><tbody>' +
      av.rows.slice(0, 10).map((r) => '<tr><td>' + esc(r.typeLabel) + '</td><td>' + esc(r.stepLabel) + '</td><td>' + esc(r.label) + ' <code>' + esc(r.code) + '</code></td><td class="num">' + r.count + '</td></tr>').join("") +
      '</tbody></table><p class="note">Avoid is a current decision, not a verdict on the asset. Open any asset in the Analyzer to see its full trace.</p></details>';
    // Portfolio: the Phase 10 summary the decision carries
    const p = portfolioView((doc.portfolio || {}).phase10);
    let ph = '<p style="margin:2px 0 0">' + pfChip(p.state, {big: true}) + '</p>';
    if (p.state === "LIMIT_BREACHED") ph += '<p class="small" style="margin:8px 0 0"><b>Portfolio limits exceeded</b> — a new directional trade is rejected while the portfolio would still breach a limit after it.</p>' +
      '<p class="small" style="margin:6px 0 0"><b>Breached:</b> ' + esc(p.breached.map((b) => b.label).join(", ")) + '.</p>';
    else if (p.state === "UNEVALUABLE" || !p.state) ph += '<p class="small" style="margin:8px 0 0">' + esc(p.view.line) + '</p>';
    ph += '<dl class="kv"><dt>Gross leverage</dt><dd>' + esc(lev(p.gross)) + '</dd><dt>Net leverage</dt><dd>' + esc(lev(p.net)) + '</dd>' +
      '<dt>Executable risk</dt><dd>' + (p.exec ? esc(pct(p.exec.metric)) + ' <span class="muted">/ ' + esc(pct(p.exec.limit)) + '</span>' : "–") + '</dd>' +
      '<dt>Worst stressed loss</dt><dd>' + (p.worst ? esc(pct(p.worst.loss)) + ' <span class="muted">' + esc(p.worst.label.toLowerCase()) + '</span>' : "–") + '</dd>' +
      (p.approaching.length ? '<dt>Approaching</dt><dd>' + esc(p.approaching.map((x) => x.label).join(", ")) + '</dd>' : "") +
      (p.missingCount ? '<dt>Missing authority</dt><dd>' + esc(p.missingGroups.map((g) => g.label + " ×" + g.count).join(", ")) + '</dd>' : "") + '</dl>' +
      '<p class="note">Risk and stressed loss as a share of equity. Stress losses are governed deterministic scenarios, not probabilities.</p><a class="more" href="portfolio.html">Open the portfolio console</a>';
    out.pf = ph + governedNote(doc);
    // Funding spreads: qualified Phase 11 funding_opportunities only
    const fs = section(doc, "funding_opportunities", now), ev = counts(doc).byType.FUNDING_SPREAD || {}, total = (ev.TRADE || 0) + (ev.WATCH || 0) + (ev.AVOID || 0);
    out.fund = (fs.count ? '<ul class="reasons">' + fs.items.map((it) => { const c = it.cand, L = c.legs || {};
        return '<li><span class="cnt">' + esc(pct(c.net_carry)) + '</span><span><b>' + esc(c.asset) + '</b> long ' + esc((L.long || {}).venue) + ', short ' + esc((L.short || {}).venue) +
          ' ' + stateChip(c.state) + '<small>net carry over the holding horizon, after costs · not risk-free</small></span></li>'; }).join("") + '</ul>'
      : '<p style="margin:0">No funding spread currently clears the desk\'s qualification gates.</p><p class="note">' + total + ' spread' + (total === 1 ? "" : "s") +
        ' evaluated this scan; none qualified. A raw funding difference is not an opportunity.</p>') + expiredNote(fs) + inconsistentNote(fs) + '<a class="more" href="funding.html">Open the funding desk</a>';
    // System: degradation, coverage and governed changes
    const deg = degradations(doc), c = counts(doc), ch = changes(doc);
    let sh = deg.length ? '<ul class="reasons">' + deg.map((d) => '<li><span class="cnt" aria-hidden="true">◌</span><span>' + esc(d.text) + '<small>' + esc(d.detail) + '</small></span></li>').join("") + '</ul>'
      : '<p class="small" style="margin:0">No unavailable venue or degraded discovery is recorded in this decision.</p>';
    sh += '<p class="note">Of ' + esc(c.discovered) + ' discovered assets, ' + esc(c.identityBlocked) + ' are not verified as crypto and ' + esc(c.executionBlocked) + ' do not clear the execution gate.</p>';
    if (ch.available) {
      sh += '<h3 style="margin-top:12px">Since the previous decision</h3>' + (ch.rows.length ? '<ul class="reasons">' + ch.rows.slice(0, 6).map((r) => '<li><span class="cnt">' + esc(r.asset) + '</span><span>' + esc(r.text) +
        (r.added.length ? '<small>added: ' + esc(r.added.join(", ")) + '</small>' : "") + (r.removed.length ? '<small>cleared: ' + esc(r.removed.join(", ")) + '</small>' : "") + '</span></li>').join("") + '</ul>' +
        (ch.rows.length > 6 ? '<p class="note">' + (ch.rows.length - 6) + ' more changes.</p>' : "") : '<p class="small">No state, rank or section changed.</p>');
    } else sh += '<p class="note">No earlier governed decision to compare with yet, so no change is shown.</p>';
    out.sys = sh;
    out.ver = "Policy " + (doc.policy_schema || "") + ", " + (doc.authority.decision_policy_review_status || "") + ".";
    return out;
  }

  /* FUNDING. Qualified spreads: decision.funding_opportunities only (WATCH at most). */
  function legRow(side, l) {
    l = l || {};
    return '<tr><td>' + side + '</td><td>' + esc(l.venue) + '</td><td class="num">' + esc(rate8h(l.rate_8h)) + '</td><td class="num">' + (l.interval_h ? esc(l.interval_h) + " h" : "–") +
      '</td><td class="num">' + esc(usd(l.volume)) + '</td><td>' + esc(l.health || "–") + '</td></tr>';
  }
  function fundingCard(c, r) {
    const L = c.legs || {}, fin = (gate(c, "FUNDING") || {}).input || {}, liq = gate(c, "EXECUTION_LIQUIDITY") || {};
    const why = (c.caps || []).concat(c.missing_authorities || []);
    return '<article class="opp is-watch" data-cand="' + esc(c.id) + '" data-state="' + esc(c.state) + '" aria-label="' + esc(c.asset + " funding spread, " + (STATE_VIEW[c.state] || {}).label) + '"><div class="opp-top"><span class="opp-rank">' + esc(r ? r.label : "") + '</span><span class="opp-asset">' + esc(c.asset) +
      '</span><span class="muted small">Funding spread</span>' + stateChip(c.state) + '</div>' +
      '<div class="tblwrap"><table class="legs"><thead><tr><th>Leg</th><th>Venue</th><th class="num">Rate (per 8 h)</th><th class="num">Venue interval</th><th class="num">24h volume</th><th>Contract health</th></tr></thead><tbody>' +
      legRow("Long", L.long) + legRow("Short", L.short) + '</tbody></table></div>' +
      '<div class="opp-facts"><span>Spread <b>' + esc(rate8h(c.spread_8h)) + '</b></span><span>Carry over ' + esc(fin.holding_hours) + ' h <b>' + esc(pct(c.carry)) + '</b></span>' +
      '<span>Estimated costs <b>' + esc(pct(c.costs)) + '</b></span><span>Net carry <b>' + esc(pct(c.net_carry)) + '</b></span><span>Basis <b>' + esc(pct(c.basis_abs)) + '</b></span>' +
      '<span>Liquidity <b>' + esc((RESULT_VIEW[liq.result] || {label: "–"}).label) + '</b></span></div>' +
      '<p class="opp-sub"><b>Why not trade-ready:</b> ' + esc(why.map(codeLabel).join("; ") || "–") + '.</p>' +
      '<p class="notrf"><b>Not risk-free.</b> ' + esc((c.warnings || []).join(" ").replace(/^NOT_RISK_FREE:\s*/, "")) + '</p>' +
      (needs(c).length ? '<div class="small" style="margin-top:8px"><b>What needs to change</b>' + needsList(c) + '</div>' : "") +
      '<div class="opp-gates">' + gateStrip(c) + '<span>' + esc(stripSummary(strip(c))) + '</span></div>' +
      (r && (r.tied || r.aboveNext) ? '<p class="rankwhy">' + esc(r.tied ? "Tied on every evidence rule with the neighbouring item; listed by name, not by strength." : "Above the next: " + r.aboveNext.text + ".") + '</p>' : "") +
      '<div class="opp-act">' + traceDetails(c) + '<a href="analyze.html?coin=' + encodeURIComponent(c.asset) + '">Open in Analyzer</a></div></article>';
  }
  function vFunding(raw, now) {
    const A = authority(raw, now), st = vStatus(A, now, "funding");
    const out = {status: A.status, statusHtml: st.html, statusBad: st.bad, qN: "", qualified: "", marketHidden: true};
    if (A.status !== "AVAILABLE") { out.qualified = failClosed(A, now); return out; }
    const doc = A.doc, sec = section(doc, "funding_opportunities", now), R = rankInfo(doc, "funding_opportunities", now);
    out.qN = sec.count + " of up to " + sec.max;
    out.marketHidden = false;
    if (!sec.count) {
      const a = avoidSummary(doc).rows.filter((r) => r.type === DECISION.funding);
      out.qualified = '<div class="empty"><p class="e-t">No funding spread currently clears the desk\'s qualification gates.</p>' +
        (a.length ? '<p class="e-d">Why the evaluated spreads were rejected:</p><ul class="reasons">' + a.slice(0, 5).map((r) => '<li><span class="cnt">' + r.count + '</span><span>Rejected at ' +
          esc(r.stepLabel) + ': ' + esc(r.label) + '<small><code>' + esc(r.code) + '</code></small></span></li>').join("") + '</ul>' : '<p class="e-d">No spread was evaluated: fewer than two healthy venues reported fresh funding for any asset.</p>') + '</div>' + expiredNote(sec) + inconsistentNote(sec);
    } else {
      out.qualified = '<div class="cards">' + sec.items.map((it, i) => fundingCard(it.cand, R.items[i])).join("") + '</div>' + cutoffNote(R, "spreads") + expiredNote(sec) + inconsistentNote(sec);
    }
    return out;
  }
  /* Every other evaluated spread (observation only, with its rejection). opt: {sort, filter, shown, open}. */
  function vFundingMarket(doc, opt) {
    opt = opt || {};
    const selected = new Set(section(doc, "funding_opportunities").items.map((i) => i.id));
    const all = doc.candidates.filter((c) => c && c.type === DECISION.funding && !selected.has(c.id) && legsHealthy(c));
    const reasonOf = (c) => (c.blockers || [])[0] || (c.state === "WATCH" ? "BEYOND_SECTION_MAXIMUM" : "");
    const lbl = (code) => code === "BEYOND_SECTION_MAXIMUM" ? "qualifies (watch) beyond the five shown" : codeLabel(code);
    if (!all.length) return {count: 0, html: '<p class="muted">Every evaluated spread is listed above.</p>'};
    const reasons = Array.from(new Set(all.map(reasonOf))).filter(Boolean).sort();
    let rows = opt.filter ? all.filter((c) => reasonOf(c) === opt.filter) : all.slice();
    const num = (x) => isNum(x) ? x : -Infinity;
    rows.sort(opt.sort === "spread" ? (a, b) => num(b.spread_8h) - num(a.spread_8h) : opt.sort === "net" ? (a, b) => num(b.net_carry) - num(a.net_carry) : (a, b) => (a.asset < b.asset ? -1 : a.asset > b.asset ? 1 : 0));
    const shown = opt.shown || 40;
    let h = '<div class="controls"><label>Sort <select id="sort"><option value="asset">by asset</option><option value="spread"' + (opt.sort === "spread" ? " selected" : "") + '>by spread</option><option value="net"' + (opt.sort === "net" ? " selected" : "") + '>by net carry</option></select></label>' +
      '<label>Reason <select id="filter"><option value="">all</option>' + reasons.map((r) => '<option value="' + esc(r) + '"' + (r === opt.filter ? " selected" : "") + '>' + esc(lbl(r)) + '</option>').join("") + '</select></label></div>';
    h += '<div class="flist"><div class="frow head" aria-hidden="true"><div class="fsum"><span>Asset</span><span>Long leg</span><span>Short leg</span><span class="num">Spread / 8 h</span><span class="num">Net carry</span><span>State</span><span>Rejected at</span></div></div>' +
      rows.slice(0, shown).map((c) => { const L = c.legs || {};
        return '<details class="frow" data-trace="' + esc(c.id) + '" data-state="' + esc(c.state) + '"><summary aria-label="' + esc(c.asset + ", " + c.state + ", show decision trace") + '"><span><b>' + esc(c.asset) + '</b></span>' +
          '<span><span class="fl">Long</span>' + esc((L.long || {}).venue) + ' ' + esc(rate8h((L.long || {}).rate_8h)) + '</span>' +
          '<span><span class="fl">Short</span>' + esc((L.short || {}).venue) + ' ' + esc(rate8h((L.short || {}).rate_8h)) + '</span>' +
          '<span class="num"><span class="fl">Spread</span>' + esc(rate8h(c.spread_8h)) + '</span><span class="num"><span class="fl">Net carry</span>' + esc(pct(c.net_carry)) + '</span>' +
          '<span class="fstate">' + stateChip(c.state, {quiet: true}) + '</span><span>' + (c.state === "AVOID" ? esc((STEP_LABEL[c.blocking_step] || c.blocking_step) + ": " + codeLabel(reasonOf(c))) : esc(lbl("BEYOND_SECTION_MAXIMUM"))) + '</span></summary><div class="tr-body"></div></details>';
      }).join("") + '</div>';
    if (rows.length > shown) h += '<p><button class="btn" type="button" id="moreRows">Show ' + Math.min(40, rows.length - shown) + ' more of ' + (rows.length - shown) + '</button></p>';
    return {count: all.length, html: '<details class="more-d" id="mkt"' + (opt.open ? " open" : "") + '><summary>Show the ' + all.length + ' evaluated spread' + (all.length === 1 ? "" : "s") + '</summary><div style="margin-top:10px">' + h + '</div></details>'};
  }

  /* PORTFOLIO. The decision's Phase 10 summary first; the same evaluation's detail (audit snapshot) when it is bound. */
  function statusTag(st) {
    const m = {OK: ["WITHIN_LIMITS", "OK"], APPROACHING: ["APPROACHING_LIMITS", "Approaching"], BREACHED: ["LIMIT_BREACHED", "Breached"]}[st];
    return m ? '<span class="chip ' + PF_VIEW[m[0]].cls + (st === "OK" ? " chip-quiet pf-okq" : "") + '"><span class="chip-mark" aria-hidden="true">' + PF_VIEW[m[0]].mark + '</span>' + m[1] + '</span>' : '<span class="tag warn">' + esc(st || "unknown") + '</span>';
  }
  const tile = (l, v, sub, id) => '<div class="tile"' + (id ? ' id="' + id + '"' : "") + '><div class="t-l">' + esc(l) + '</div><div class="t-v">' + esc(v) + '</div>' + (sub ? '<div class="t-s">' + esc(sub) + '</div>' : "") + '</div>';
  /* The audit detail belongs to this decision's evaluation only when the audit's own evaluation says exactly what the
     decision's Phase 10 summary says: the same as_of, policy, state, breached and approaching limits, number of
     positions and every limit's metric, limit and status. Otherwise it is not shown (a comparison, never a merge). */
  function boundDetail(doc, audit) {
    const pr = audit && typeof audit === "object" ? audit.portfolio_risk : null, p10 = (doc.portfolio || {}).phase10 || {};
    if (!pr || typeof pr !== "object" || !isInt(p10.as_of)) return null;
    const lim = (L) => Object.keys(L && typeof L === "object" ? L : {}).sort().map((k) => [k, (L[k] || {}).metric, (L[k] || {}).limit, (L[k] || {}).status]);
    const key = (x, n) => JSON.stringify([x.as_of, x.policy_hash, x.state, x.breached || [], x.approaching || [], n, lim(x.limits)]);
    return key(pr, Array.isArray(pr.positions) ? pr.positions.length : null) === key(p10, p10.positions) ? pr : null;
  }
  /* The audit evaluates the whole paper book; it is bound to the decision's full-paper-book summary the same way. */
  function boundFullDetail(doc, audit) {
    const full = (doc.portfolio || {}).full_paper_book;
    return full && typeof full === "object" ? boundDetail({portfolio: {phase10: full}}, audit) : null;
  }
  function governedPositions(doc) {
    const rows = (doc.portfolio || {}).governed_positions;
    if (!Array.isArray(rows)) return "";
    let h = '<section class="sec panel" aria-labelledby="gp-h"><h2 id="gp-h">Governed positions</h2><p class="secsub">' + rows.length + ' paper position' + (rows.length === 1 ? "" : "s") +
      ' of trade-authorized strategy sides, entered since that authority took effect. These are what the limits above evaluate.</p>';
    if (!rows.length) return h + '<p class="small" style="margin:0">None yet.</p></section>';
    return h + '<div class="tblwrap"><table class="tbl"><thead><tr><th>Asset</th><th>Strategy</th><th>Side</th><th class="num">Entry</th><th class="num">Mark</th><th class="num">Stop</th><th class="num">Leverage</th><th class="num">Stop risk</th><th>Funding</th><th class="num">Time left</th></tr></thead><tbody>' +
      rows.map((x) => '<tr><td><a href="analyze.html?coin=' + encodeURIComponent(x.asset) + '">' + esc(x.asset) + '</a></td><td>' + esc(x.strategy) + '</td><td>' + dirTag(sideOf(x.direction)) + '</td><td class="num">' + esc(price(x.entry)) +
        '</td><td class="num">' + esc(price(x.mark)) + '</td><td class="num">' + esc(price(x.stop)) + '</td><td class="num">' + esc(lev(x.leverage)) + '</td><td class="num">' + esc(pct(x.account_risk)) +
        '</td><td>' + esc(String(x.funding || "–").toLowerCase()) + (isNum(x.funding_rate_8h) ? ' ' + esc(rate8h(x.funding_rate_8h)) : "") + '</td><td class="num">' +
        (isNum(x.hold_hours_remaining) ? esc(durTxt(x.hold_hours_remaining * 3600)) : "–") + '</td></tr>').join("") + '</tbody></table></div></section>';
  }
  function vPortfolio(raw, now, audit, auditState) {
    const A = authority(raw, now), st = vStatus(A, now, "portfolio");
    if (A.status !== "AVAILABLE") return {status: A.status, statusHtml: st.html, statusBad: true, body: failClosed(A, now)};
    const doc = A.doc, p = portfolioView((doc.portfolio || {}).phase10), full = (doc.portfolio || {}).full_paper_book;
    const governed = !!(doc.portfolio || {}).governed, pr = governed ? null : boundDetail(doc, audit), fullPr = governed ? boundFullDetail(doc, audit) : null;
    let h = '<section class="sec panel" aria-labelledby="st-h"><h2 id="st-h" class="sr">Portfolio state</h2><div class="pfhead">' + pfChip(p.state, {big: true}) + '<p>' + esc(p.view.line) + '</p></div>';
    if (p.breached.length) h += '<p class="blocker"><b>Breached:</b> ' + esc(p.breached.map((b) => b.label).join(", ")) + '. A new directional trade is rejected while the portfolio would still breach a limit after it.</p>';
    if (p.approaching.length) h += '<p class="small" style="margin:10px 0 0"><b>Approaching:</b> ' + esc(p.approaching.map((b) => b.label).join(", ")) + '.</p>';
    if (p.state === "UNEVALUABLE" || !p.state) h += '<p class="small" style="margin:10px 0 0">Missing authority keeps the state unevaluable; unknown values are shown as unknown, never as zero.</p>';
    h += '</section><section class="sec" aria-labelledby="ex-h"><div class="sechead"><h2 id="ex-h">Exposure</h2></div><div class="tiles">' +
      tile("Gross leverage", lev(p.gross)) + tile("Long leverage", lev(p.long)) + tile("Short leverage", lev(p.short)) + tile("Net leverage", lev(p.net)) + '</div></section>';
    const lim = (k) => p.limits.find((x) => x.key === k), ar = lim("max_asset_stop_risk"), cr = lim("max_cluster_stop_risk");
    h += '<section class="sec" aria-labelledby="rk-h"><div class="sechead"><h2 id="rk-h">Risk</h2><span class="n">share of equity</span></div><div class="tiles">' +
      tile("Executable risk", p.exec ? pct(p.exec.metric) : "–", p.exec ? "limit " + pct(p.exec.limit) : "") +
      tile("Theoretical stop risk", pr ? pct((pr.liquidity || {}).theoretical_stop_risk) : "–", pr ? "every stop filled exactly" : "detail " + (auditState === "loading" ? "loading" : "unavailable")) +
      tile("Worst stressed loss", p.worst ? pct(p.worst.loss) : "–", p.worst ? p.worst.label : "") +
      tile("Largest concentration", ar ? pct(ar.metric) : "–", cr ? "one asset; correlated cluster " + pct(cr.metric) : "one asset") + '</div></section>';
    h += '<section class="sec panel" aria-labelledby="lm-h"><h2 id="lm-h">Limits</h2><div class="tblwrap"><table class="tbl lim"><thead><tr><th>Limit</th><th class="num">Current</th><th class="num">Policy limit</th><th>Status</th><th>Use</th></tr></thead><tbody>' +
      p.limits.map((l) => { const ratio = isNum(l.metric) && l.limit ? Math.min(1.5, l.metric / l.limit) : null, cls = l.status === "BREACHED" ? "breach" : l.status === "APPROACHING" ? "near" : "ok";
        return '<tr><td>' + esc(l.label) + '</td><td class="num">' + esc(l.metricTxt) + '</td><td class="num">' + esc(l.limitTxt) + '</td><td>' + statusTag(l.status) + '</td><td>' +
          (ratio == null ? '<span class="muted">unknown</span>' : '<div class="bar ' + cls + '" role="img" aria-label="' + esc(Math.round(ratio * 100) + "% of the limit") + '"><i style="width:' + (ratio / 1.5 * 100).toFixed(1) + '%"></i><b style="left:' + (100 / 1.5).toFixed(1) + '%"></b></div>') + '</td></tr>'; }).join("") +
      '</tbody></table></div><p class="note">The bar marks the policy limit; a bar past the mark is over it. Limits are reviewed policy values (' + esc(p.policy_review_status || "") + '), not empirical estimates.</p></section>';
    const scen = pr ? ((pr.stress || {}).scenarios || {}) : {};
    h += '<section class="sec panel" aria-labelledby="sx-h"><h2 id="sx-h">Stress scenarios</h2><p class="secsub">Governed deterministic scenarios: each applies one adverse rule to the whole book. They are not probabilities, value-at-risk or expected losses.</p>' +
      '<div class="tblwrap"><table class="tbl"><thead><tr><th>Scenario</th><th class="num">Loss</th><th>What it assumes</th></tr></thead><tbody>' +
      p.stress.map((x) => { const sc = scen[x.key] || {};
        return '<tr><td>' + esc(x.label) + '</td><td class="num">' + esc(pct(x.loss)) + '</td><td class="ink2">' + esc(pr ? (sc.rule || "–") + ((sc.missing || []).length ? " · missing: " + sc.missing.join(", ") : "") + (sc.status && sc.status !== "AVAILABLE" ? " · " + sc.status : "") : "…") + '</td></tr>'; }).join("") + '</tbody></table></div></section>';
    h += '<section class="sec panel" aria-labelledby="ma-h"><h2 id="ma-h">Missing authority</h2>' + (p.missingCount ? '<ul class="reasons">' + p.missingGroups.map((g) => '<li><span class="cnt">' + g.count + '</span><span>' + esc(g.label) +
      '<small><code>' + esc(g.code) + '</code></small></span></li>').join("") + '</ul><p class="note">Missing values stay missing: they are never counted as zero' + (pr && pr.funding && pr.funding.rule ? " (" + esc(pr.funding.rule) + ")" : "") + '.</p>' : '<p class="small" style="margin:0">None recorded.</p>') + '</section>';
    if (!governed) {
      h += portfolioDetail(doc, pr, audit, auditState);
      return {status: "AVAILABLE", statusHtml: st.html, statusBad: false, body: h};
    }
    h += governedPositions(doc);
    const fv = portfolioView(full);
    h += '<section class="sec panel" aria-labelledby="lb-h"><h2 id="lb-h">Legacy paper book · diagnostic only</h2><div class="pfhead">' + pfChip(fv.state) +
      '<p>Every open paper position of the quant desk, including legacy holdovers the desk never recommended. It no longer gates any decision.</p></div>' +
      (fv.breached.length ? '<p class="small" style="margin:8px 0 0"><b>Breached in this book:</b> ' + esc(fv.breached.map((b) => b.label).join(", ")) + '.</p>' : "") + '</section>';
    h += portfolioDetail(doc, fullPr, audit, auditState);
    return {status: "AVAILABLE", statusHtml: st.html, statusBad: false, body: h};
  }
  function portfolioDetail(doc, pr, audit, auditState) {
    if (!pr) return '<section class="sec"><div class="skel">' + (auditState === "loading" || auditState === "idle" ? "Loading position detail…" : audit ? "The loaded position detail belongs to a different evaluation than this decision, so it is not shown. The summary above is the governed state."
      : "Position detail is unavailable (the audit snapshot did not load). The summary above is the governed state.") + '</div></section>';
    const con = pr.concentration || {}, dep = pr.dependence || {}, sz = (pr.inputs || {}).sizing || {};
    const table = (title, obj, keyLabel) => { const rows = Object.entries(obj || {}).sort((a, b) => (b[1].stop_risk || 0) - (a[1].stop_risk || 0));
      return '<div class="panel"><h3>' + esc(title) + '</h3><table class="tbl" style="margin-top:6px"><thead><tr><th>' + esc(keyLabel) + '</th><th class="num">Positions</th><th class="num">Notional</th><th class="num">Stop risk</th></tr></thead><tbody>' +
        rows.map(([k, v]) => '<tr><td>' + esc(k) + '</td><td class="num">' + esc(v.positions) + '</td><td class="num">' + esc(lev(v.notional)) + '</td><td class="num">' + esc(pct(v.stop_risk)) + '</td></tr>').join("") + '</tbody></table></div>'; };
    let h = '<section class="sec" aria-labelledby="cc-h"><div class="sechead"><h2 id="cc-h">Concentration</h2><span class="n">notional as leverage, stop risk as a share of equity</span></div><div class="grid2">' +
      table("By asset", con.asset, "Asset") + table("By strategy", con.strategy, "Strategy") + table("By side", con.side, "Side") +
      '<div class="panel"><h3>Correlated clusters</h3><table class="tbl" style="margin-top:6px"><thead><tr><th>Cluster</th><th class="num">Positions</th><th class="num">Stop risk</th></tr></thead><tbody>' +
      (dep.clusters || []).map((c, i) => '<tr><td>' + (i + 1) + '</td><td class="num">' + esc((c.positions || []).length) + '</td><td class="num">' + esc(pct(c.stop_risk)) + '</td></tr>').join("") +
      '</tbody></table><p class="note">' + esc(dep.note || "") + '</p></div></div>' + ((con.shared_assets || []).length ? '<p class="note">Held by more than one strategy: ' + esc(con.shared_assets.join(", ")) + '.</p>' : "") + '</section>';
    const pos = pr.positions || [], blocked = pos.filter((x) => x.actionability !== "ACTIONABLE").length;
    h += '<section class="sec panel" aria-labelledby="ps-h"><h2 id="ps-h">Positions</h2><p class="secsub">' + pos.length + ' open paper position' + (pos.length === 1 ? "" : "s") +
      (blocked ? ', ' + blocked + ' identity-blocked (still counted in every risk figure above)' : ', none identity-blocked') + '.' +
      (isNum(sz.account) ? ' Sized for a ' + esc(usd(sz.account)) + ' paper account' + (sz.basis ? ' (' + esc(titleCase(sz.basis)) + ')' : "") + ', not your account.' : ' Paper sizes, not your account.') + '</p>' +
      '<div class="tblwrap"><table class="tbl"><thead><tr><th>Asset</th><th>Strategy</th><th>Side</th><th>Status</th><th class="num">Entry</th><th class="num">Mark</th><th class="num">Stop</th><th class="num">Leverage</th><th class="num">Stop risk</th><th>Liquidity</th><th>Funding</th><th class="num">Time left</th></tr></thead><tbody>' +
      pos.map((x) => '<tr class="' + (x.actionability !== "ACTIONABLE" ? "blocked" : "") + '" data-actionability="' + esc(x.actionability) + '"><td><a href="analyze.html?coin=' + encodeURIComponent(x.asset) + '">' + esc(x.asset) + '</a></td><td>' + esc(x.strategy) + '</td><td>' + dirTag(sideOf(x.direction)) + '</td><td>' +
        (x.actionability === "ACTIONABLE" ? '<span class="tag">Actionable</span>' : '<span class="tag warn">' + esc(titleCase(x.actionability || "unknown")) + '</span>') + (x.status !== "VALID" ? ' <span class="tag warn">' + esc(x.status || "") + '</span>' : "") + '</td>' +
        '<td class="num">' + esc(price(x.entry)) + '</td><td class="num">' + esc(price(x.mark)) + '</td><td class="num">' + esc(price(x.stop)) + '</td><td class="num">' + esc(lev(x.leverage)) +
        '</td><td class="num">' + esc(pct(x.account_risk)) + '</td><td>' + esc(((x.liquidity || {}).state || "–").toLowerCase()) + '</td><td>' + esc(((x.funding || {}).state || "–").toLowerCase()) +
        '</td><td class="num">' + (isNum(x.hold_hours_remaining) ? esc(durTxt(x.hold_hours_remaining * 3600)) : "–") + '</td></tr>').join("") + '</tbody></table></div>' +
      '<p class="note">' + esc(((pr.stop_realism || {}).statement) || "") + '</p></section>';
    return h;
  }

  /* ANALYZER: the decision panel for one asset (the same cards as Today). call: the Analyzer's decide() result or null. */
  function vAssetPanel(raw, coin, now, call) {
    const A = authority(raw, now);
    let h = '<div class="dtop"><h2 class="dasset" id="dec-h">' + esc(coin) + '</h2>';
    if (A.status !== "AVAILABLE") return {status: A.status, state: null, html: h + stateChip("UNAVAILABLE", {big: true}) + '</div><div style="margin-top:12px">' + failClosed(A, now) + '</div>'};
    const doc = A.doc, I = index(doc), rec = I.assets.get(coin) || null;
    const cands = (I.byAsset.get(coin) || []).slice().sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state] || (a.id < b.id ? -1 : 1));
    const state = rec ? rec.state : "NONE", ad = assetDecision(doc, coin, now);
    if (ad.status !== "AVAILABLE") {
      const t = ad.status === "STALE" ? "Decision expired — waiting for the next governed scan." : "The decision on " + coin + " is unreadable — nothing here is actionable.";
      return {status: ad.status, state: null, html: h + stateChip("UNAVAILABLE", {big: true}) + '</div><div class="failclosed" role="alert" style="margin-top:12px"><p class="fc-t">' +
        esc(t) + '</p><p class="fc-d">' + esc(ad.reason || "") + '. The desk does not extend a decision.</p></div>'};
    }
    if (call && ad.trade && !call.lead) {
      return {status: "UNAVAILABLE", state: null, html: h + stateChip("UNAVAILABLE", {big: true}) +
        '</div><div class="failclosed" role="alert"><p>' + esc(call.headline) +
        '</p><p>No approved plan is displayed. Restore the exact evaluated proposal or wait for a new governed evaluation.</p></div>'};
    }
    h += stateChip(state, {big: true});
    if (call && call.lead && call.side) h += dirTag(call.side) + '<span class="muted small">' + esc(call.lead.strategy) + (call.plan ? "" : " · no plan here") + '</span>';
    const line = call && ad.trade && !call.lead ? call.headline : assetLine(doc, coin, now);
    h += '</div><p class="dhead">' + esc(line) + '</p>';
    if (!rec) h += '<p class="note">' + esc(coin) + ' is not in this scan\'s governed discovery, so the desk has no decision on it. Price and context below are for reference only; they are never a trade.</p>';
    else if (!cands.length) {
      const pseudo = {id: "ASSET:" + rec.asset, trace: rec.trace || [], state: rec.state, blockers: rec.blockers || [], caps: [], missing_authorities: [], placement: {}};
      h += '<p class="small" style="margin:8px 0 0">No opportunity on ' + esc(coin) + ' in this decision. Asset checks: ' + esc((rec.blockers || []).map(codeLabel).join(", ") || "none failed") + '.</p>' +
        '<details class="tr" style="margin-top:8px"><summary>Asset checks</summary><div class="tr-body">' + traceTable(pseudo, doc) + '</div></details>';
    }
    h += cands.map((x) => oppCard(x, {asset: false})).join("");
    return {status: "AVAILABLE", state, html: h};
  }

  /* RESEARCH: an explicitly labelled evidence record, never runtime/promotion authority. S: {sum, mt, mc, reg, adj, dash}, each optional
     except the summary. */
  const STATE_TXT = {LEGACY_HOLDOVER: "Legacy holdover", ACTIVE_REQUALIFIED: "Requalified", PAPER_ONLY: "Paper only", DISABLED: "Disabled",
                     INSUFFICIENT_EVIDENCE: "Insufficient evidence", REQUALIFIED: "Requalified", PROBATION: "Probation", REJECTED: "Rejected", INVALIDATED: "Invalidated"};
  const st = (x) => STATE_TXT[x] || titleCase(x || "unknown");
  const unavail = (x) => x && /UNAVAILABLE|MISSING|INSUFFICIENT|INCOMPLETE/.test(x) ? '<span class="tag warn">' + esc(titleCase(x)) + '</span>' : '<span class="tag">' + esc(titleCase(x || "–")) + '</span>';

  function vResearch(S) {
    S = S || {};
    const s = S.sum;
    if (!s || s.schema !== "v8.phase9-summary/1") {
      return '<div class="failclosed" role="alert"><p class="fc-t">' + stateChip("UNAVAILABLE") + ' The governed research record did not load.</p><p class="fc-d">Strategy authority still gates every decision on Today; only this explanation is missing.</p></div>';
    }
    const strats = (s.strategies || []).slice().sort((a, b) => (a.deployment_state === "DISABLED") - (b.deployment_state === "DISABLED") || (a.strategy_id < b.strategy_id ? -1 : 1));
    const qualified = strats.reduce((n, x) => n + (x.qualified_closed_trades || 0), 0);
    const holdovers = strats.filter((x) => x.deployment_state === "LEGACY_HOLDOVER"), disabled = strats.filter((x) => x.deployment_state === "DISABLED");
    const g = (S.adj && S.adj.gate) || {};
    let h = '<section class="sec panel" aria-labelledby="why-h"><h2 id="why-h">' + esc(S.evidenceLabel || "Reviewed Phase 9 baseline") + '</h2>' +
      '<p class="lead">A strategy signal can become a trade only when its strategy is requalified on point-in-time evidence (runtime <b>Requalified</b>, research <b>Requalified</b>). ' +
      (g.pit_calendar_days ? 'Requalification needs at least ' + esc(g.pit_calendar_days) + ' days of point-in-time history and ' + esc(g.qualified_closed_trades) + ' fully qualified closed trades, among other gates. ' : "") +
      'This evaluation records ' + esc(s.pit_overlap_calendar_days) + ' point-in-time overlap days and ' + esc(qualified) + ' qualified trades, so <b>' + esc(s.requalified_count) + ' of ' + esc(s.candidate_count) + '</b> strategies are requalified in evidence.</p>' +
      '<p class="lead ink2">The record contains ' + holdovers.length + ' legacy holdovers and ' + disabled.length + ' disabled strategies. Research evidence never promotes or enables a strategy. Production authority is shown separately.</p></section>';
    h += '<section class="sec" aria-labelledby="tr-h"><div class="sechead"><h2 id="tr-h">Evaluation results</h2><span class="n">Phase 9 adjudication</span></div><div class="tiles">' +
      rtile("Strategy candidates", s.candidate_count) + rtile("Known historical trials", "≥ " + s.known_historical_trials, "a lower bound") +
      rtile("Trial census", s.trial_census_complete ? "Complete" : "Incomplete") + rtile("Point-in-time overlap", s.pit_overlap_calendar_days + " days", g.pit_calendar_days ? "of " + g.pit_calendar_days + " required" : "") +
      rtile("Qualified closed trades", qualified, g.qualified_closed_trades ? "of " + g.qualified_closed_trades + " required per strategy" : "") + rtile("Requalified strategies", s.requalified_count) + '</div></section>';
    const row = (x) => '<tr class="' + (x.deployment_state === "DISABLED" ? "dim" : "") + '"><td>' + esc(x.strategy_id) + '</td><td>' + esc(st(x.deployment_state)) + '</td><td>' + esc(st(x.research_state)) +
      '</td><td class="num">' + esc(x.qualified_closed_trades) + '</td><td>' + (x.deployment_state === "ACTIVE_REQUALIFIED" && x.research_state === "REQUALIFIED" ? '<span>Evidence gate passed; reviewed promotion required</span>'
        : x.deployment_state === "DISABLED" ? '<span class="muted">No: disabled</span>' : '<span>No: watch at most</span>') + '</td></tr>';
    const thead = '<thead><tr><th>Strategy</th><th>Recorded runtime</th><th>Research result</th><th class="num">Qualified trades</th><th>Promotion from this evidence?</th></tr></thead>';
    const live = strats.filter((x) => x.deployment_state !== "DISABLED");
    h += '<section class="sec panel" aria-labelledby="mx-h"><h2 id="mx-h">Evaluation record</h2><p class="small ink2" style="margin:0 0 8px">Recorded deployment states describe the authority evaluated by this result. They do not update production policy.</p>' +
      '<div class="tblwrap"><table class="tbl matrix">' + thead + '<tbody>' + (live.length ? live.map(row).join("") : '<tr><td colspan="5" class="muted">No strategy runs on the paper desk.</td></tr>') + '</tbody></table></div>' +
      (disabled.length ? '<details class="more-d" style="margin-top:10px"><summary>The ' + disabled.length + ' disabled strategies</summary><div class="tblwrap" style="margin-top:8px"><table class="tbl matrix">' + thead + '<tbody>' + disabled.map(row).join("") + '</tbody></table></div></details>' : "") + '</section>';
    h += '<section class="sec" aria-labelledby="ev-h"><div class="sechead"><h2 id="ev-h">Research evidence</h2><span class="n">for advanced review</span></div><div class="panel ev">' + evidence(S) + '</div></section>';
    h += '<section class="sec" aria-labelledby="hl-h"><div class="sechead"><h2 id="hl-h">Historical and unqualified research</h2></div><div class="panel legacy">' + legacy(S) + '</div></section>';
    return h;
  }
  const rtile = (l, v, sub) => '<div class="tile"><div class="t-l">' + esc(l) + '</div><div class="t-v">' + esc(v) + '</div>' + (sub ? '<div class="t-s">' + esc(sub) + '</div>' : "") + '</div>';
  const det = (title, body) => '<details class="more-d"><summary>' + esc(title) + '</summary><div class="dbody">' + body + '</div></details>';

  function vResearchPublication(S) {
    S = S || {};
    const a = S.authority, snap = S.snapshot, now = isInt(S.now) ? S.now : Math.floor(Date.now() / 1000);
    const binding = ["main_sha", "tree_sha", "strategy_policy_hash", "runtime_implementation_hash", "method_code_hash"];
    const bound = (o) => o && binding.every((k) => typeof o[k] === "string" && /^[a-f0-9]+$/.test(o[k]) && o[k].length === (k === "main_sha" || k === "tree_sha" ? 40 : 64));
    const rowsOk = (rows) => Array.isArray(rows) && rows.every((r) => r && typeof r === "object" && typeof r.strategy_id === "string" && typeof r.deployment_state === "string" && typeof r.research_state === "string");
    const validA = a && a.schema === "v8.production-research-authority/1" && bound(a) && a.strategy_policy && rowsOk(a.strategy_policy.strategies);
    // Complete hashes are validated before publication; the browser independently checks source and authority.
    const docs = snap && snap.documents || {}, sum = docs["research_phase9_summary.json"], adj = docs["research_strategy_adjudication.json"];
    const valid = snap && snap.schema === "v8.production-research/1" && snap.source && snap.source.channel === "research-production" && snap.source.ref === "refs/heads/main" && snap.source.promotion_authority === "NONE" && snap.source.workflow === ".github/workflows/research.yml" && ["schedule", "workflow_dispatch"].includes(snap.source.event) && bound(snap.authority) && snap.source.sha === snap.authority.main_sha && isInt(snap.generated_at) && snap.generated_at > 0 && snap.generated_at <= now && snap.provenance && isInt(snap.provenance.cutoff) && sum && sum.schema === "v8.phase9-summary/1" && rowsOk(sum.strategies) && adj && Array.isArray(adj.strategies) && adj.strategies.every((r) => r && typeof r === "object") && adj.runtime_policy_hash === snap.authority.strategy_policy_hash && adj.runtime_implementation_hash === snap.authority.runtime_implementation_hash && snap.provenance.method_code_hash === snap.authority.method_code_hash && snap.file_hashes && sum.adjudication_hash === snap.file_hashes["research_strategy_adjudication.json"];
    const baseline = S.baseline && S.baseline.sum && S.baseline.sum.schema === "v8.phase9-summary/1" && rowsOk(S.baseline.sum.strategies) ? S.baseline : null;
    let status = valid ? (validA && binding.every((k) => snap.authority[k] === a[k]) ? "CURRENT" : "AUTHORITY_MISMATCH") : baseline ? "BASELINE_ONLY" : "UNAVAILABLE";
    if (status === "CURRENT" && (a.evidence_status === "LAST_KNOWN_GOOD" || now - snap.generated_at > 36 * 3600)) status = "LAST_KNOWN_GOOD";
    let h = '<section class="sec panel"><h2>Production strategy authority</h2><p class="lead">Only the reviewed production policy can enable a strategy. New research evidence never changes this authority or grants a trade.</p>';
    if (validA) {
      h += '<div class="tblwrap"><table class="tbl matrix"><thead><tr><th>Strategy</th><th>Deployment</th><th>Research authority</th></tr></thead><tbody>' + a.strategy_policy.strategies.map((r) => '<tr><td>' + esc(r.strategy_id) + '</td><td>' + esc(st(r.deployment_state)) + '</td><td>' + esc(st(r.research_state)) + '</td></tr>').join("") + '</tbody></table></div><p class="note">Strategies absent from the production policy are disabled. Today and Analyzer continue to use the Phase 11 decision.</p>';
    } else h += '<p class="note">Production policy detail is unavailable. The historical baseline does not substitute for runtime authority. Today and Analyzer still use their own governed decision artifact.</p>';
    h += '</section><section class="sec panel"><h2>Latest research evidence</h2><p><b>' + esc(titleCase(status)) + '</b></p>';
    if (valid) h += '<p class="lead">Governed evaluation from production main ' + esc(snap.authority.main_sha.slice(0, 7)) + ', generated ' + esc(utcTxt(snap.generated_at)) + ' (' + esc(durTxt(Math.max(0, now - snap.generated_at))) + ' old).</p>';
    if (status === "AUTHORITY_MISMATCH") h += '<p class="note">This evidence belongs to a different production authority or current authority could not be verified. It is not current evidence.</p>';
    if (status === "LAST_KNOWN_GOOD") h += '<p class="note">Showing the previous successful production evaluation. A newer refresh failed or the daily refresh is overdue; the evidence age is shown above.</p>';
    if (status === "BASELINE_ONLY") h += '<p class="note">No valid production research snapshot is available. The reviewed Phase 9 baseline below is historical, not current evidence.</p>';
    if (status === "UNAVAILABLE") h += '<p class="note">Research evidence is unavailable. Today and Analyzer remain governed by Phase 11.</p>';
    h += '</section>';
    const selected = valid ? {sum, adj, mt: docs["research_multiple_testing.json"], mc: docs["research_matched_controls.json"], reg: docs["research_phase9_registration_plan.json"], dash: S.dash,
      evidenceLabel: status === "CURRENT" ? "Latest governed production evaluation" : "Previous governed production evaluation"} : baseline && {...baseline, dash: S.dash, evidenceLabel: "Reviewed Phase 9 baseline"};
    if (selected) h += vResearch(selected);
    if (validA || valid) h += '<section class="sec panel ev">' + det("Advanced: production and research provenance", '<pre style="white-space:pre-wrap;overflow-wrap:anywhere">' + esc(JSON.stringify({production: validA ? Object.fromEntries(binding.map((k) => [k, a[k]])) : null,
      evidence: valid ? {authority: snap.authority, generated_at: snap.generated_at, source: snap.source, provenance: snap.provenance, adjudication_hash: sum.adjudication_hash, trial_census_hash: sum.trial_census_hash, run_provenance: snap.run_provenance} : null}, null, 2)) + '</pre>') + '</section>';
    return {status, html: h};
  }

  function evidence(S) {
    const mt = S.mt || {}, mc = S.mc || {}, adj = S.adj || {}, g = adj.gate || {}, reg = S.reg || {};
    const best = (k) => Math.max.apply(null, (adj.strategies || []).map((x) => ((x.evidence || {})[k]) || 0).concat([0]));
    const req = [["Point-in-time history", "≥ " + g.pit_calendar_days + " days", best("pit_calendar_days") + " days"],
                 ["Fully qualified closed trades", "≥ " + g.qualified_closed_trades, String(best("qualified_closed_trades"))],
                 ["Trades on each side", "≥ " + g.minimum_side_trades, "–"], ["Mean R, lower 95% bound", "> " + g.mean_R_lower_95, "unavailable"],
                 ["Out-of-sample mean R (last " + Math.round((g.oos_fraction || 0) * 100) + "%)", "> " + g.oos_mean_R, "unavailable"],
                 ["Probability of backtest overfitting (PBO)", "≤ " + g.pbo, "unavailable"], ["White Reality Check p", "≤ " + g.white_rc_p, "unavailable"],
                 ["Hansen SPA p", "≤ " + g.spa_p, "unavailable"], ["Deflated Sharpe probability", "≥ " + g.dsr_probability, "unavailable"],
                 ["Matched controls per signal", g.controls_per_signal + ", ≥ " + Math.round((g.full_matched_fraction || 0) * 100) + "% fully matched", "unavailable"],
                 ["Mean R at 1.5× costs", "> " + g.stress_1_5_mean_R, "unavailable"]];
    let h = det("The requalification gate", '<table class="tbl"><thead><tr><th>Requirement</th><th>Gate</th><th>Best of the ' + esc((adj.strategies || []).length) + ' candidates in this evaluation</th></tr></thead><tbody>' +
      (g.pit_calendar_days ? req.map((r) => '<tr><td>' + esc(r[0]) + '</td><td>' + esc(r[1]) + '</td><td>' + esc(r[2]) + '</td></tr>').join("") : '<tr><td colspan="3" class="muted">The adjudication record did not load.</td></tr>') +
      '</tbody></table><p class="note">Promotion: ' + esc(adj.promotion || "–") + '.</p>');
    h += det("Multiple-testing authority (PBO, Reality Check, SPA, FDR)", '<dl class="kv" style="text-align:left">' +
      kvrow("Status", unavail(mt.blocking_reason || "")) + kvrow("Probability of backtest overfitting", unavail((mt.pbo || {}).status)) +
      kvrow("White Reality Check", unavail((mt.white_reality_check || {}).status)) + kvrow("Hansen SPA", unavail((mt.hansen_spa || {}).status)) +
      kvrow("False discovery rate (BH / BY)", unavail((mt.fdr || {}).status)) + kvrow("Family tests", unavail((mt.family_tests || {}).status)) +
      kvrow("Trial return universe", mt.trial_return_universe_complete ? "complete" : '<span class="tag warn">Incomplete</span>') + '</dl>' +
      '<p class="note">' + esc((mt.family_tests || {}).reason || "") + '</p>');
    h += det("Matched controls", '<dl class="kv" style="text-align:left">' + kvrow("Status", unavail(mc.status)) + kvrow("Fully matched signal fraction", esc(pct(mc.full_signal_fraction, 0))) +
      kvrow("Listing age", unavail(mc.listing_age_status)) + kvrow("Market cap", unavail(mc.market_cap_status)) + '</dl>');
    h += det("Out-of-sample", '<p style="margin:0">The gate holds out the last ' + esc(Math.round((g.oos_fraction || 0) * 100)) + '% of point-in-time history and needs a positive mean R there. With ' +
      esc(best("pit_calendar_days")) + ' days of history, no out-of-sample result exists for any candidate.</p>');
    h += det("Prospective registration", '<p style="margin:0">' + esc((reg.entries || []).length) + ' experiments planned, state <b>' + esc(titleCase(reg.state || "–")) + '</b>, authority ' + esc(reg.authority || "–") +
      '. A registered experiment is evaluated only on data after its registration.</p>');
    const sl = adj.shadow_ledger || {};
    h += det("Shadow ledger", '<p style="margin:0">' + esc(sl.records || 0) + ' record' + (sl.records === 1 ? "" : "s") + ', ' + esc(sl.experiments || 0) + ' experiments, ' + (sl.valid ? "hash chain valid" : "hash chain not verified") +
      '. Append-only pre-registration of research experiments; no record has trade authority.</p>');
    h += det("Provenance", '<dl class="advl"><dt>Adjudication</dt><dd>' + esc((S.sum || {}).adjudication_hash || "–") + '</dd><dt>Trial census</dt><dd>' + esc((S.sum || {}).trial_census_hash || "–") +
      '</dd><dt>Dataset</dt><dd>' + esc(((mt.provenance || {}).dataset_sha256) || "–") + '</dd><dt>Data cutoff</dt><dd>' + esc((mt.provenance || {}).cutoff ? utcTxt(mt.provenance.cutoff) : "–") +
      '</dd><dt>Strategy policy</dt><dd>' + esc(adj.runtime_policy_hash || "–") + '</dd></dl>');
    return h;
  }
  const kvrow = (k, v) => '<dt>' + esc(k) + '</dt><dd style="text-align:left;font-weight:500">' + v + '</dd>';

  function legacy(S) {
    let h = '<p class="small" style="margin:0"><b>Not strategy authority.</b> These are the earlier engines\' own backtest and live records. They are survivorship-unqualified (the coin lists were chosen with hindsight) and no Phase 9 gate has passed them, so they never make, size or block a desk decision.</p>';
    const sc = ((S.dash || {}).scorecard) || [];
    if (sc.length) h += det("Earlier engines' records", '<div class="tblwrap"><table class="tbl"><thead><tr><th>Engine</th><th class="num">Tested trades</th><th class="num">Per $100 risked</th><th class="num">Winners</th><th>Period</th><th class="num">Live trades</th></tr></thead><tbody>' +
      sc.map((r) => { const t = r.tested || {}, l = r.live || {};
        return '<tr class="dim"><td>' + esc(r.name) + '</td><td class="num">' + esc(t.n == null ? "–" : t.n) + '</td><td class="num">' + esc(t.per100 == null ? "–" : (t.per100 > 0 ? "+$" : "$") + t.per100) +
          '</td><td class="num">' + esc(t.win == null ? "–" : Math.round(t.win * 100) + "%") + '</td><td>' + esc(t.period || "–") + '</td><td class="num">' + esc(l.n == null ? "–" : l.n) + '</td></tr>'; }).join("") +
      '</tbody></table></div><p class="note">Shown as historical context only. A positive figure here does not override the strategy authority above.</p>');
    h += '<h3 style="margin-top:14px">Diagnostic pages</h3><ul class="diag">' +
      '<li><a href="quant.html">Quant desk</a> <span class="ink2">the paper desk\'s positions and journal for the legacy holdovers.</span></li>' +
      '<li><a href="picks.html">Coin picks</a> <span class="ink2">the swing and day-trade scores of an earlier engine.</span></li>' +
      '<li><a href="radar.html">15m radar</a> <span class="ink2">the 15-minute scanner and its strategy tournament.</span></li>' +
      '<li><a href="smart.html">Smart money</a> <span class="ink2">what Hyperliquid\'s top traders hold.</span></li></ul>' +
      '<p class="note">These pages show the earlier engines as they run. Their scores and calls are not desk decisions; Today and the Analyzer show those.</p>';
    return h;
  }


  /* What the pages re-render on with time alone: the document's validity and every section item that has passed its
     own valid_until. A page redraws when this changes, so a lapsed decision leaves the screen without a reload. */
  function timeKey(raw, now) {
    const A = authority(raw, now);
    if (A.status !== "AVAILABLE") return A.status + "|" + (A.as_of || "");
    return A.status + "|" + A.as_of + "|" + SECTIONS.map((n) => section(A.doc, n, now).expired.length).join(",");
  }

  // ------------------------------------------------------------------ browser loading
  const nowS = () => Math.floor(Date.now() / 1000);
  /* GET a JSON file. Revalidated on every call (cache "no-cache": a 304 when unchanged). Returns {status: OK | MISSING
     | MALFORMED, data}. A body that is not JSON is MALFORMED (authority() then fails closed on it). */
  async function getJSON(path, opt) {
    let r;
    try {
      r = await fetch(path, {cache: "no-cache", signal: opt && opt.signal});
    } catch (e) { return {status: "MISSING", data: null, error: String(e && e.message || e)}; }
    if (!r.ok) return {status: "MISSING", data: null, error: "HTTP " + r.status};
    try { return {status: "OK", data: await r.json()}; } catch (e) { return {status: "MALFORMED", data: "MALFORMED", error: "not JSON"}; }
  }
  async function loadDecision() {
    const r = await getJSON(DECISION.file);
    return {doc: r.status === "OK" ? r.data : r.status === "MALFORMED" ? "MALFORMED" : null, status: r.status, loadedAt: nowS(), error: r.error || null};
  }
  /* The audit snapshot (Phase 10 detail, Phase 9 bindings): its gzip copy when the browser can decompress (about 1/16 of
     the bytes), otherwise the plain file. */
  async function loadAudit() {
    if (typeof DecompressionStream === "function") {
      try {
        const r = await fetch(AUDIT_FILE + ".gz", {cache: "no-cache"});
        if (r.ok && r.body) {
          const txt = await new Response(r.body.pipeThrough(new DecompressionStream("gzip"))).text();
          return {status: "OK", data: JSON.parse(txt)};
        }
      } catch (e) { /* fall back to the plain file */ }
    }
    return getJSON(AUDIT_FILE);
  }
  /* Theme toggle and the scrolling tab bar, shared by every page. */
  function shell() {
    if (typeof document === "undefined") return;
    const b = document.getElementById("theme");
    if (b) b.addEventListener("click", () => {
      const r = document.documentElement, dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      r.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("picks_theme", r.dataset.theme); } catch (e) { /* private mode */ }
    });
  }

  return {
    VERSION: "desk/1", DECISION, SECTIONS, UI_MAX, AUDIT_FILE, RESEARCH_DIR, STATE_ORDER,
    STEP_LABEL, RESULT_VIEW, STATE_VIEW, PF_VIEW, SECTION_LABEL, TYPE_LABEL, EVIDENCE_LABEL, CODE_TXT, LIMIT_LABEL, STRESS_LABEL,
    authority, assetDecision, assetLine, candidateOk, briefOf, codeTxt, codeLabel, index, gate, section, rankInfo, cardModel, keyReason, needs,
    traceRows, strip, stripSummary, counts, degradations, zeroTrade, avoidSummary, portfolioView, changes,
    fmt: {esc, pct, lev, usd, price, rate8h, utc: utcTxt, time: timeTxt, dur: durTxt, ago: agoTxt, title: titleCase, limit: limitValue},
    html: {stateChip, pfChip, dirTag, resultTag, gateStrip, traceTable, traceDetails, needsList, failClosed, freshness, oppCard, fundingCard},
    views: {research: vResearch, researchPublication: vResearchPublication, status: vStatus, today: vToday, funding: vFunding, fundingMarket: vFundingMarket, portfolio: vPortfolio, assetPanel: vAssetPanel, boundDetail},
    timeKey, bindTraces, getJSON, loadDecision, loadAudit, shell, nowS, esc, sideOf,
  };
});
