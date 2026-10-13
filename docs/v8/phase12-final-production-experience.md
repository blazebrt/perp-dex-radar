# v8 Phase 12: the Perp Decision Desk (final production experience)

Phase 12 turns the governed Phase 11 decision into the product. It changes published pages only. No engine, policy,
identity, discovery, quant, portfolio-risk or research code changes, and no golden is moved to hide drift (see
[Parity](#parity)).

Base: production `main` at `0efcf72aecc3f8712c78039c5573cdc445c0ec40` (tree `d69eb9e3438b22370951a9826f45b0752dee3f10`,
parent `413d972d60fc4a1e1666c5b56eb70275fb3e3942`).

## 1. What the UI was before (audit)

| Surface (base) | What it did | Problem for a decision desk |
|---|---|---|
| `dashboard.html` (published as the front page `index.html`) | "Market now", "The three versions", "Where the signals line up" (coins two legacy engines pointed at), smart money, an accuracy scorecard with Proven / Mixed / No edge verdicts | It was the product's centre, but it presented legacy agreement and legacy "Proven" verdicts as if they were calls. It never read the Phase 11 decision or the Phase 10 portfolio state. |
| `picks.html`, `quant.html`, `smart.html`, the 15-minute radar (`index.html` source, published as `radar.html`) | Each engine's own scores, positions and calls | Five competing dashboards in the main tab bar, each with its own language for "ready". |
| `analyze.html` / `analyze.js` | Since the Phase 11 correction, the call came from the decision, but the page led with the legacy signal grid and chart | Authority and context looked equally weighty. |
| Phase 10 portfolio state, Phase 9 research record, funding spreads | Audit and research files only | No page showed them. |

The Phase 11 decision (`data/v8/decision.json`, `v8.decision/1`) already held every state, gate, blocker, rank,
section, trace, explanation, change and the Phase 10 summary. No machine-readable field was missing, so the engine
stays byte-stable and the UI only presents.

## 2. Information architecture

Exactly five surfaces, the same tab bar on every page:

| Tab | File (published) | Primary source |
|---|---|---|
| Today | `today.html` (as `index.html`) | `decision.json` |
| Analyzer | `analyze.html`, `analyze.js` | `decision.json`; prices, chart, legacy records, CoinGecko and sentiment as labelled context |
| Funding | `funding.html` | `decision.json` (`funding_opportunities` and every evaluated `FUNDING_SPREAD`) |
| Portfolio | `portfolio.html` | `decision.json` (`portfolio.phase10`); detail from `audit_latest.json(.gz)` only when it is the same evaluation |
| Research | `research.html` | production policy authority, isolated current production evidence (`data/v8/research/current/snapshot.json`), explicitly historical Phase 9 baseline, diagnostic context |

Shared by all of them: `desk.js` (the presentation core, `window.DESK`) and `desk.css` (the design system).

Legacy surfaces:

- `dashboard.html`: retired (no longer published). Its data file `data/dashboard.json` is still written byte-identically and shown on Research as historical, unqualified context.
- `picks.html`, `quant.html`, `smart.html`, `radar.html`: kept running unchanged as diagnostics, reachable from Research. They carry the desk's tab bar with no tab current, the desk brand and a note: "Diagnostic page… Its scores and calls are not desk decisions and are not trade-ready."

## 3. Data contract

`desk.js` is the only code that reads the decision. Every page calls the same functions:

- `authority(doc, now)`: `AVAILABLE`, or `MISSING`, `MALFORMED` or `STALE`.
  - Stale means `now > doc.valid_until`. There is no local TTL, no age limit of the desk's own and no extension.
  - A document with an old `as_of` and a current `valid_until` is shown; a fresh `as_of` with a past `valid_until` is not.
- `section(doc, name, now)`: a section's items exactly as Phase 11 placed them, at most five.
  - An item is shown only when it agrees with the file's own contract: its candidate exists once, its state equals the item's state and is in `selection_trace.eligible_states`, its type is in `selection_trace.types`, a funding spread has two `HEALTHY` legs, and Best trades now holds `TRADE` only.
  - Anything else is not shown and is counted as "inconsistent", with a note.
  - An item past its own candidate `valid_until` is not shown either; the note says "Decision expired — waiting for the next governed scan."
- `assetDecision(doc, coin, now)`: the Analyzer's authority (moved verbatim from `analyze.js`), so Today and the Analyzer read one object one way.
- `boundDetail(doc, audit)`: the audit snapshot's `portfolio_risk` is shown only when its `as_of`, policy hash, state, breached and approaching limits, position count and every limit's metric, limit and status equal the decision's `portfolio.phase10`.

What the frontend decides (presentation only):

- wording and labels;
- at most five cards;
- hiding an inconsistent or lapsed item;
- the zero-TRADE reason counts (grouped from the candidates' own `blocking_step` and `blockers[0]`, never a hard-coded reason);
- tie groups for ranks separated only by a name tie-break (`asset`, `strategy`, `direction` or `id`).

It never infers TRADE / WATCH / AVOID, a rank, a section, strategy authority, identity, execution readiness, funding authority or a portfolio pass or fail, and it builds no score.

## 4. Design system

- Tokens are defined on `:root` with light and dark values (`prefers-color-scheme` and the theme toggle): `--page #f6f6f3`, `--surface #fff`, `--ink #15171a`, `--muted #6f747b`, and state colours.
- One sans family; tabular numbers for figures.
- Layout: a two-column desk (decisions, then a 340 px rail for Portfolio, Funding and System), one column under 1000 px.

### One state language

Every page uses the same chip, card edge and gate strip. The mark and the text carry the state; colour is never the only signal.

| State | Chip | Card | Meaning on screen |
|---|---|---|---|
| TRADE | solid green, `●` "Trade" | green edge | "All required desk gates currently pass." A direction tag (Long / Short) only here. |
| WATCH | amber outline, `◐` "Watch" | amber edge | "Not trade-ready: …" with what needs to change. A signal's side reads "long signal, not a call". |
| AVOID | red outline, `✕` "Avoid" | red edge | "Rejected at {step}: {reason}." Summarised on Today, listed in the Analyzer. |
| MISSING / DEGRADED | dashed grey, `◌` "No authority" | dashed panel | Fail closed: nothing is actionable. |

Gate strip: one cell per trace entry. Each result has its own shape as well as its own colour:

- Pass: solid;
- Watch cap: half;
- Missing: dashed outline;
- Fail: dark solid;
- Not applicable: hairline.

An `aria-label` summarises the strip ("Gates: 7 pass, 1 watch cap, 1 missing, 1 fail (Portfolio after)").

## 5. Today

- **Desk Status** (one line):
  - decision time, age and how long it stays current;
  - assets discovered and opportunities evaluated;
  - Trade / Watch / Avoid counts. The Trade chip is loud only when a current trade is on screen;
  - the portfolio state;
  - the first recorded degradation (venue unavailable, fallback discovery, coverage, portfolio binding).
  - On a missing, malformed or stale decision the status turns dashed, and every region fails closed.
- **Best trades now**: `best_trades_now` only, at most five, never filled.
  - Each card shows the rank (or tie), asset, Long/Short, strategy, Trade chip and "All required desk gates currently pass."
  - It shows the engine's own strategy-authority rule, signal kind and age, execution volume and slippage, and Portfolio after.
  - Below that: the gate strip, the "Above the next" rank reason, the Decision trace and an Analyzer link.
- **Zero TRADE**: "No trade currently clears every desk gate."
  - The count of current strategy signals.
  - When the portfolio is breached and has rejected signals: "Portfolio limits are currently breached. N of M signals were rejected because the portfolio would still breach a limit after the trade."
  - Then the reasons, counted from the candidates (blocking step and code, with the raw code), and the other codes on the same signals.
  - No signal at all says so instead.
- **Emerging**: `emerging_opportunities`, WATCH only.
  - Each card says why it is interesting (the engine's evidence), what blocks it and what needs to change.
  - Ties are labelled T1 / T1 and "listed by name, not by strength".
- **Avoided**: a count and a collapsed table by type, rejection step and code. AVOID cards are never listed on Today.
- **Portfolio** (rail): the Phase 10 state chip. With `LIMIT_BREACHED`:
  - "Portfolio limits exceeded — a new directional trade is rejected while the portfolio would still breach a limit after it";
  - the breached limits by name;
  - gross and net leverage, executable risk against its limit, the worst stressed loss and its scenario, approaching limits and missing authority.
- **Funding** (rail): qualified spreads only, or "No funding spread currently clears the desk's qualification gates." with the number evaluated.
- **System** (rail):
  - recorded degradation, distinguished from "no opportunity";
  - identity- and execution-blocked counts;
  - changes since the previous governed decision, only when the artifact has it.

## 6. Decision Trace and "What needs to change"

The Decision Trace is a disclosure on every card. Its rows are built on first open from the loaded document, so hundreds of rows never load up front.

- Each row reads Step → Checked → Rule → Result → Effect:
  - Step, Rule and Effect are the artifact's own text;
  - Result is the artifact's result with its mark;
  - the code is shown next to its plain words;
  - only "Checked" summarises the input for reading.
- The rows are the decision trace followed by the placement trace (ranking, section).
- An "Advanced" disclosure holds the candidate id, codes, `valid_until`, decision time, policy schema and hash, implementation hash and authority hash. No hash appears on a card.
- On mobile the five columns stack, each with its label.

"What needs to change" lists `explanation.to_become_trade` step by step with the engine's rule, on every WATCH card and every qualified funding card. Nothing is invented.

## 7. Analyzer

The page's top area is the decision panel, using the same `desk.js` cards as Today:

- the asset;
- a big state chip;
- a direction only for a current TRADE;
- one sentence worded from the same objects;
- one card per opportunity on the asset, with its trace.

The rest of the page is context:

- **Labelling:** the context below the panel is labelled "Context".
- **Legacy signals:** the grid moved below the chart and is retitled "Legacy signals on X — context".
- **CoinGecko:** fundamentals are "matched by ticker (context, not identity)".
- **Outside discovery:** "outside the desk's governed discovery: there is no decision, and nothing here is a trade."
- **Order of loading:** the decision renders before candles load.
- **Chart failure:** says "The desk decision above does not depend on it."
- **Search:** lists the decision's discovery assets first. CoinGecko results are marked as outside discovery (context only).

The call (`decide()`) is unchanged: LONG or SHORT only for a current Phase 11 TRADE, and without a live price there is no plan.

## 8. Funding, Portfolio and Research

- **Funding:**
  - Qualified opportunities come first. Each card shows both legs with venue, rate per 8 h, settlement interval, volume and contract health, then spread, carry, costs, net carry, basis and liquidity, then why it is not trade-ready.
  - Every card carries "Not risk-free.", plus what needs to change and the trace.
  - Every other evaluated spread sits in a separate, closed list with its rejection, a sort and a reason filter. Only spreads with two healthy legs are ever listed.
- **Portfolio:**
  - The state chip and its line.
  - Breached and approaching limits, and exposure (gross, long, short, net).
  - Risk: executable, theoretical stop, worst stressed loss, largest concentration.
  - Every limit with current value, policy limit, status and a bar marked at the limit.
  - Stress scenarios "governed deterministic scenarios … not probabilities, value-at-risk or expected losses", each with the rule it assumes.
  - Missing authority ("never counted as zero").
  - With the bound detail: concentration by asset, strategy, side and cluster, then positions. Identity-blocked positions are marked and stated as "still counted in every risk figure above".
- **Research:**
  - Production strategy authority comes from the deployed checkout's policy, separately from evidence.
  - Latest successful production evidence carries its own time, age and current/mismatch/last-known-good state. Without it, the committed record is explicitly the Reviewed Phase 9 baseline.
  - The current reviewed outcome remains 24 candidates, ≥ 199 known trials, incomplete census and zero PIT overlap/qualified trades/requalified strategies; these are evaluation values, not hardcoded future outcomes.
  - The evaluation matrix never grants promotion; the gate, multiple testing, controls, registration, shadow ledger and provenance remain available for advanced review.
  - The earlier engines' records as historical, unqualified context, with links to the diagnostic pages.

## 9. Quality

- **Responsive:**
  - Checked at 1440, 1024, 768 and 390 px on every page.
  - No horizontal page scroll anywhere; tables scroll inside their own wrapper.
  - On mobile a card reads state, asset, direction, reason, blocker, then the trace.
- **Accessibility:**
  - skip link and landmarks;
  - one `h1` per page with section headings;
  - native `details`/`summary` disclosures and real buttons and links;
  - `aria-current` on the tab, `role="alert"` on fail-closed panels, `aria-live` status;
  - visible `:focus-visible`;
  - states carried by text and mark as well as colour;
  - muted text at #686d74 (≥ 4.5:1 on the page, card and inset colours; #959aa1 in the dark theme);
  - zoom allowed.
- **Reduced motion:** honoured. The only motion is the disclosure state.
- **Performance:**
  - Today, Funding and Portfolio summary each make one request for the decision, revalidated with `cache: no-cache`.
  - The live decision is ~0.37 MB, ~18 KB gzipped on the wire.
  - Portfolio loads the gzip audit after the summary renders.
  - Traces render on first open. No framework.
  - `desk.js` is ~30 KB gzipped.
  - Pages re-check validity every 30 s and redraw only when the authority or a section item's horizon changes, so open traces stay open. They reload every 5 minutes and on return to the tab.
- **Errors:**
  - a missing, malformed or stale decision fails closed on every desk page;
  - the core not loading fails closed;
  - an audit that is unavailable or belongs to another evaluation shows the summary only;
  - a research record that does not load still states that strategy authority gates every decision;
  - chart or CoinGecko failures degrade only the context.
- **Security:**
  - Every artifact string is escaped (`&`, `<`, `>`, `"`, `'`) before insertion, attribute values included. URLs are built with `encodeURIComponent`.
  - Page binders insert only the views' escaped HTML.
  - No keys, credentials, wallet integration, order placement or secrets.
  - Forbidden copy ("guaranteed", "risk-free" except negated, "certain", "proven profit", "guaranteed edge") is checked by a test.

## 10. Tests and checks

`tests/test_v8_phase12.py` runs `desk.js` and `analyze.js` under node on documents built by the real engine, on tampered copies and on hostile strings. The fifteen adversarial checks are `test_01` … `test_15`:

1. WATCH cannot look like TRADE, even when the file itself claims WATCH is eligible for Best trades now.
2. AVOID cannot look like WATCH or TRADE.
3. A stale decision, or a TRADE past its own horizon, is not actionable.
4. A missing or malformed decision has no legacy fallback.
5. A swing "Proven" record cannot make a trade.
6. A smart-money "Proven" record cannot make a trade.
7. A legacy holdover never looks requalified, even with a tampered research state.
8. `LIMIT_BREACHED`, `WITHIN_LIMITS` and `UNEVALUABLE` are shown truthfully. The identity-blocked position is marked, and a foreign audit is refused.
9. Zero TRADE shows no fallback card.
10. The trace is rendered verbatim (rules, effects, results and codes, row by row).
11. A degraded funding leg never appears qualified.
12. At most five are shown, a tampered seven included.
13. The Analyzer and Today show the same state.
14. `valid_until` fails closed with no local TTL.
15. Optional external failures keep the core decision.

The same file also checks:

- escaping;
- forbidden copy;
- navigation;
- that the core loads first;
- that the core decides nothing;
- the published file set;
- accessibility foundations.

`tools/v8/desk_check.js` renders one published decision through the core and checks the screen against the file:

- every card's state;
- the sections;
- the zero-TRADE empty state;
- healthy funding legs;
- the portfolio chip;
- one trace row per trace entry;
- Analyzer and Today agreement for every asset.

CI runs it on an engine-built document. Research runs it on the exact head's live decision.

## Parity

The legacy parity golden for this branch is `tests/fixtures/v8/legacy_parity_golden_phase12.json`. Against the Phase 11 golden:

- the decisions are identical;
- the only changed legacy files are the twelve published pages pinned in `tests/fixtures/v8/phase12_expected_deltas.json`, each to its exact base and head digest:
  - changed: `index.html` (now Today), `analyze.html`, `analyze.js`, `picks.html`, `quant.html`, `smart.html`, `radar.html`;
  - new: `desk.js`, `desk.css`, `funding.html`, `portfolio.html`, `research.html`;
- the Phase 9 record is published as audit files under `data/v8/research/phase9/`.

`tools/v8/delta_parity.py` against the base `0efcf72` reports 0 universe, DEX status, note or decision deltas and 12 pinned file deltas.

## Known limitations

### Research-publication correction

The committed `research/phase9/` files are the **Reviewed Phase 9 baseline**, not current evidence. The historical
`b74d630c…` → `4d69e56f…` difference includes later history and the accepted final Phase 9 closure (method identity,
explicit zero gate fields and runtime binding). The regression authority is final Phase 9 `19596979…`, whose runtime,
method and policy files remain unchanged through this correction.

Research runs daily at **03:17 UTC (08:47 IST)** on default/main. This keeps the expensive evidence evaluation separate
from 20-minute scans. It uses the existing governed process and a current-time production cutoff; review runs keep
their exact-head cutoff. Phase runs write only the generic `research` review branch. Only successful main schedule/
manual runs may write `research-production`, guarded by the exact ref/event/default branch and by checkout == current
remote main, checked again immediately before publication. Full unit tests and mandatory Phase 9/10/11/12 checks must
succeed. A complete validated `snapshot.json` is committed with the prior production snapshot as parent and pushed
without force: either the whole new snapshot replaces the tip, or the previous tip remains. No policy file is written.

The snapshot binds main SHA/tree, strategy policy, exact runtime implementation, research-method identity, trial census,
history cutoff/head/view, dataset, adjudication and all curated evidence files. It includes generated time and workflow
run/attempt. Scan reads **only** `research-production`, validates the bundle, then publishes
`data/v8/research/current/snapshot.json` and `data/v8/research/authority.json`. This step is informational and cannot
change the decision artifact; its failure does not stop Today or Analyzer. Browser code reads only these same-site
files and the labelled baseline, never the generic review branch.

Research shows production policy first, independently from evaluation results. States are CURRENT,
LAST_KNOWN_GOOD (a later failed main run or more than 36 hours old), AUTHORITY_MISMATCH, BASELINE_ONLY and UNAVAILABLE.
Full hashes sit behind Advanced detail. A changed main SHA, tree, policy, runtime or method prevents the current label.
An old valid snapshot may still be viewed with its mismatch/age; missing or malformed evidence falls back only to the
historical baseline. A newer successful evidence result, even requalified, never grants runtime eligibility. Reviewed
main policy remains the only promotion path.

`tests/test_v8_research_publication.py` exercises production/review isolation, exact bindings, failed checks, atomic
publication to a local bare Git fixture, unchanged policy, browser states, escaping and Today/Analyzer independence.
The existing Phase 12 authority tests remain required. Parity fixtures change only the exact `desk.js` Research
presentation and `research.html` digests; engine outputs and other page digests remain unchanged.

After this correction is reviewed and merged, the production channel still needs its first successful main run.
Until then the correct Research state is BASELINE_ONLY. This PR does not perform a production Research dispatch,
merge, promotion or deployment.

- The diagnostic pages still show their own scores and calls (labelled as not desk decisions). `data/dashboard.json` is still built, for the historical record on Research.
- The Analyzer still loads exchange candles, CoinGecko and sentiment for context. They are labelled and never decide, but they are external requests.
- A section item hidden as inconsistent or lapsed is counted, not explained further. The file is the authority and the next scan re-decides.
- The Portfolio detail needs the audit snapshot of the same scan. When the published audit and decision come from different scans, only the governed summary shows.
- Rule strings in the trace are the engine's own text and can be technical, for example a policy map. Plain words sit next to every code, not every rule.
