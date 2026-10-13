# Phase 9: strategy authority and deployment continuity

Base: `c2d48549a8012fa77862cb57d7e706620fa85a18`, tree
`b31048c449411a48cafe6f557ba2e54b3d13e482`. No Phase 10 work is included.

## Authority

`v8/quant_strategy_policy.json` is the reviewed deployment policy. TSMOM, TREND_EMA,
and XSMOM remain in that order, all LEGACY_HOLDOVER / INSUFFICIENT_EVIDENCE.
Research never writes it. `quant.py` validates it before running; a missing or invalid
policy raises an error, with no tuple fallback. ACTIVE_REQUALIFIED requires a
hash-bound, reviewed evidence file and adjudication satisfying the current gate.
A subsequent reviewed main-branch change is required to promote or demote deployment.

Promotion binds two distinct representations using the shared canonical hash helpers
in `v8.strategy_policy`. Every adjudication row carries `runtime_definition_hash`
(the digest of `quant.STRATS[sid]`, or null when there is no runtime definition) and
`adjudicated_definition_hash` (the digest of exactly `strategy_id`, `implementation`,
`params`, `parameter_hash`, `code_hash`, and `code_files`). The trace retains both
hashes and the complete research definition; audit provenance exposes the bindings.

ACTIVE_REQUALIFIED requires the current runtime digest, adjudication runtime hash,
and reviewed runtime hash to agree, and re-runs the current gate against the exact bound
adjudicated row as its definition (so the row's own `params["sides"]` decides the side
requirements). It also recomputes the adjudicated definition
hash from the row and requires both the stored and reviewed hashes to agree with it.
The reviewed package still binds the complete artifact bytes with SHA-256. Missing
bindings fail closed with STRATEGY_POLICY_INVALID. Same-ID evidence cannot authorize
a different definition, even if its outer file checksum has been refreshed.
Runtime and research dictionaries are not compared directly: their representations
differ (for example hold_h versus hold_days). Any future semantic mapping and actual
promotion require a new reviewed package; these hashes do not establish semantic
equivalence on their own. No present strategy is promoted.

The added fields harden the existing Phase 9 promotion contract; all version labels
remain unchanged. Prior research artifacts remain diagnostic records, but cannot
authorize promotion without the required definition bindings. Synthetic tests cover
valid promotion, the former look=30 adjudication / look=31 runtime acceptance, same-ID
research substitution, missing fields, independent tampering, and a consistently
regenerated reviewed package. Statistical methods and their availability are unchanged.

The entire `qexport.verdict` ID shortcut is removed, including variant-by-ID rejection.
That exporter now labels all its historical results LEGACY_SURVIVORSHIP_UNQUALIFIED.
The old random-twin statistics remain diagnostics. Its combined portfolio follows
the policy's runtime composition only to retain a legacy diagnostic, never to adjudicate.

Inventory of old authority patterns:

* `tools/research/qexport.py`: FINAL, its unconditional live verdict, and portfolio
  selection from FINAL. Removed as research authority.
* `quant.py`: ORDER and the assertion that three strategies passed one/three-year tests.
  Replaced with policy-derived order and truthful holdover language.
* `quant_research.json`: historical stored live labels/claims. Original bytes preserved
  because the file is copied into runtime output and participates in existing provenance.
  `research/legacy/quant_research_diagnostic.json` contains the same historical numbers
  with explicit diagnostic labels and retained `legacy_verdict` / `legacy_why` fields.
  The audit exposes the raw labels separately as `legacy_stored_verdicts`, alongside
  the governed diagnostic classification. Neither gives research authority.
* `tools/research/pit_research.py`: QUANT selects three strategies for the Phase 8
  diagnostic comparison. It assigns no requalification verdict. Kept frozen;
  the separate Phase 9 job evaluates all 24 candidates.
* Older phase documents/fixtures describe historical FINAL/ORDER behavior. They remain
  historical records, superseded by this document, rather than being rewritten as if
  Phase 9 had existed then.

## Predeclared gate

`v8/strategy_authority.py:GATE` is fixed before the Phase 9 data run. Required:
180 PIT calendar days, 100 fully qualified closed trades, positive net mean R and
day-clustered 95% lower bound, positive matched edge and its lower bound, full matching
for 90% of signals with at least 50 controls each, DSR >= .95, PBO <= .20,
SPA p <= .05, White RC p <= .10, BY q <= .05, positive chronological last-third OOS
mean and positive 1.5x-cost mean. 2x cost is diagnostic. Funding credits are not
amplified as benefits by stress; fees, slippage, and adverse funding are stressed.

Concentration gates use positive-profit contribution denominators: top 1 <=20%,
top 5 <=50%, top 10 <=75%, largest month <=50%, and every leave-one-asset-out mean >0.
Which sides need evidence comes from the adjudicated definition itself:
`adjudicate(evidence, definition)` reads the canonical expanded `params["sides"]`
("both", "long" or "short"; every current catalog candidate is "both"). Each required side
needs at least `minimum_side_trades` (20) trades with available inference; a mean below
`side_mean_floor_R` (-.05R) with its 95% upper bound below `side_upper_95_max_R` (0) fails.
An evidence `both_sides` flag is informational: if present it must agree with the
definition, otherwise the verdict is INSUFFICIENT_EVIDENCE
(BOTH_SIDES_FLAG_DISAGREES_WITH_DEFINITION); a definition without a side value fails closed
(STRATEGY_SIDE_DEFINITION_UNAVAILABLE). Runtime metadata (`quant.STRATS`, which carries no
sides) and the strategy ID never decide sides. Unavailable/incomplete inputs block the pass.
No strategy ID participates in the gate. No parameter tuning is performed.

`GATE` is the single numerical source: `CHECKS` names, for every compared evidence key,
its GATE field, comparison and failure kind, and adjudicate() reads `GATE[field]` at call
time. The leave-one-asset-out floor is the named field `leave_one_asset_out_min_mean_R`
(0) and the side upper bound `side_upper_95_max_R` (0), both with their former values.
The method settings (`oos_fraction`, `bootstrap_replications`, `block_days`,
`cscv_segments`, `cscv_min_segment_days`) are passed from GATE by the research job.
No numerical standard changed. Tests tighten every GATE value and require the verdict
(or the method call) to change, so a duplicated literal cannot hide.

The gate also requires a complete historical census and trial-return universe,
complete feature/slice authority, and valid prospective registration. The current
repository does not satisfy these conditions. A plan is not registration.

## Trial census

The census inspects qexport, qstrat, qgrid, qrun, qrun3y and their complete Git history
reachable from the frozen base, plus historical result-file history and a file inventory.
The repository is not shallow. Those source files were introduced together in
`85924aa983cf53c4efc4bb2c8eb5eb0ef8be0877`; saved results appeared in
`79cd6390aabfce8576697755ca0e7d87bac29c63` before that source import.

The current grid encodes 18 + 135 + 27 = 180 settings. Expanding function defaults and
deduplicating implementation + parameter hash + relevant code hash across grid,
LIBRARY, and TESTED gives 199 provable combinations. The saved 24 result records prove
reported runs, but not their exact historical source binding; they are not falsely
counted twice as distinct trials. Aliases preserve XSMOM_14D/XSMOM_14D_7 correspondence.
Classification distinguishes PROVEN_CONSIDERED, ENCODED_SEARCH_SPACE, PROVEN_RUN and
UNKNOWN_HISTORICAL_STATUS. The lower bound is 199; the upper bound is unknown.
Unrecorded pre-import trials and command-line window overrides cannot be reconstructed.
TRIAL_CENSUS_INCOMPLETE is an authority blocker, never a manufactured complete census.

## Statistical definitions and references

All method outputs are research only. Missing or degenerate inputs yield
UNAVAILABLE_INSUFFICIENT_DATA, not zero, a passing probability, or a dropped method.

* DSR follows Bailey and López de Prado, [The Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf).
  It uses daily SR, sample length, observed third/fourth moments, and the expected
  maximum SR from trial count and across-trial SR variance. The latter is required;
  ordinary Sharpe is never substituted. Incomplete historical return columns cannot
  establish that variance for authoritative inference.
* CSCV/PBO follows Bailey et al., [The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).
  Sixteen chronological blocks, minimum 14 days each, all 12,870 half/half combinations.
  IS SR selects only for this diagnostic. OOS rank uses average ties and denominator
  N+1; lambda <=0 counts as overfit. Every split, winner, rank and lambda is saved.
  PBO does not select a deployment winner. Insufficient or zero-variance splits fail closed.
* White RC and Hansen SPA use 5,000 common circular block resamples, fixed 7-day
  blocks, and a deterministic provenance seed. All candidate columns share indices.
  RC uses the centered maximum mean. SPA studentizes with the long-run standard
  deviation of bootstrap sqrt(T) means and retains clearly inferior negative means
  using Hansen's consistent sqrt(2 log log T) threshold. See the maintained primary
  implementation documentation for [SPA / Reality Check](https://bashtage.github.io/arch/multiple-comparison/multiple-comparisons.html).
  Monte Carlo probabilities use (exceedances+1)/(replications+1).
* BH and BY cover every supplied candidate, never just the holdovers. BY multiplies
  the monotone BH correction by the harmonic-number dependence factor. Raw p, BH q
  and BY q are all reported when calculable. Missing historical trial-return columns
  remain a blocker even if a current-candidate-only diagnostic succeeds.

The common daily series is summed closed-trade R, including zeros on fully observed
days, not a newly invented portfolio/account return model. Daily gaps are not compressed
into adjacent bootstrap dates. These diagnostics do not solve Phase 10 portfolio realism.
Independent tests use arithmetic moments, known BH/BY values, finite bootstrap
enumeration, and a two-block anti-correlated CSCV example; synthetic tests include
random families, a lucky selected winner, and a real injected edge.

## PIT matching and robustness

The candidate adapter uses the existing Phase 8 verified history, eligibility and cost
qualification. Only closed rows with all universe, identity, liquidity, funding and
cost components enter aggregates. Funding-sensitive candidate signals use observed
settlements; missing funding cannot determine the carry ranking. Existing signal
parameters and live quant mathematics are unchanged.

Matching considers the same timestamp/direction and only then-eligible assets, excludes
the candidate asset, prohibits duplicates, and ranks deterministically by normalized
distance then asset ID. Normalization uses the same timestamp's pre-entry cross-section.
Numeric features use only closed preceding bars and governed liquidity/funding;
trend/regime match categorically. Controls use the candidate's trade geometry and
the same PIT simulator and qualification. Control outcomes cannot affect matching.

No governed PIT market-cap history or genuine listing-inception source was found.
Neither current cap/FDV/rank/volume nor first observed candle is substituted.
MATCHED_CONTROL_MARKET_CAP_MISSING and FULL_MATCHED_CONTROL_UNAVAILABLE block full
matching. Partial matching and its signal-day-clustered edge remain explicitly diagnostic.
Regime tables include unknown buckets rather than pretending missing age is known.
The implementation's full-feature authority remains false until a separately reviewed
governed source adapter and its validation are supplied.

## Reproduction, cutoffs and workflow

Run `python tools/research/strategy_adjudication.py --md <export> --history <export>
--cutoff <unix> --out <folder>`. It saves census, adjudication, multiple-testing, matching,
registration-plan and summary artifacts. Statistical seeds bind cutoff arrays, viewed
history, source/method hashes and census hash; source newline normalization is LF.
Performance measurements are separate from deterministic research artifacts.

Research's Phase 9 step is mandatory and records an explicit exit code. Saved results
run even after failure; a green optional Phase 8 step is not Phase 9 qualification.
Both workflow tests and saved output schema/counts are checked. Research writes only
its existing research-results branch; runtime policy, shadow ledger and history are untouched.

The registration plan freezes parameters/code, trial family, corrections and thresholds,
and requires evaluation to begin after authoritative main registration. It has no start
timestamp and appends nothing. The ledger remains one genesis, zero experiments, authority NONE.

## Runtime implementation binding

`runtime_definition_hash` covers only the runtime metadata `STRATS[sid]`; a change to
`sig_tsmom`, `sig_trend_ema`, `xs_scores`, `_stop` or trade management leaves it unchanged.
A third binding, `runtime_implementation_hash`, is the digest of
`{path: sha256(exact bytes)}` over `v8.strategy_policy.RUNTIME_IMPLEMENTATION_FILES`.
The adjudication row (and its trace), the reviewed evidence and the code running now must
agree three ways on both the metadata hash and the implementation hash; anything else is
STRATEGY_POLICY_INVALID. Rows for candidates without a runtime definition carry null.

Dependency manifest: `quant.py` - STRATS, indicators, `sig_tsmom`, `sig_trend_ema`,
`xs_scores`, `trend_feats`, `daily_feats`, `_stop`, `slip_of`, `eligible`, `sim_trade` and the
run loop's entry/exit rules all live there. Any byte change to it invalidates every promotion
until a review is regenerated (fail closed). Excluded, with reasons:
`scanner.py` (market-data acquisition, bar cleaning and the shared universe, identity and
liquidity gates of every engine, versioned and hashed by the audit as `config_hash` /
`identity_config_hash`; it decides which coins and bars exist, not how a strategy trades
them), `v8/evidence.py` (the shared identity execution gate and entry-time proof stamps),
and `v8/strategy_policy.py` / `v8/quant_strategy_policy.json` (the deployment authority
itself, hashed separately as `runtime_policy_hash`). Tests alter each of those functions in
a fixture copy of `quant.py`, prove the metadata hash is unchanged and the implementation
hash differs, and require validation to fail.

The committed `research/phase9/` snapshot predates this binding, so its rows have no
`runtime_implementation_hash` (the audit reports null); it cannot authorize promotion.
Exact-head Research artifacts carry the binding.

## Deployment state on the published pages

`quant.json` carries `deployment_state` and `research_state` for every enabled strategy and
`strategy_authority` (`runtime_policy_schema`, `runtime_policy_hash`, `runtime_order`), all
from the policy `quant.py` validated. The dashboard (`dashboard.quant_authority`) and
`quant.html` (`authority()`, `stateLabel()`) derive every label from those states:
all LEGACY_HOLDOVER keeps the exact "Legacy holdover" text; all ACTIVE_REQUALIFIED shows
"Requalified"; a mix shows "Mixed authority" and states that the desk as a whole is not
requalified; no enabled strategy shows "Disabled" / "No deployment-enabled strategies".
A missing or unknown state is never shown as requalified.

## Empty portfolio

`qexport.portfolio()` takes the deployment-enabled order from `quant.RUNTIME_ORDER` (the
validated policy). With no enabled strategy it emits a deterministic diagnostic -
`status=NO_ENABLED_STRATEGIES`, `strategies=[]`, `all_trades.n=0`, `taken.n=0`, other fields
empty or null - with no placeholder strategy, no account simulation and no growth planner
(`NO_PORTFOLIO_TRADES` covers enabled strategies with no closed 3-year trades). A non-empty
portfolio is computed exactly as before; a test compares it with the pre-correction code.
The dashboard and `quant.html` render the diagnostic without the planner or account curves.

## Limits retained

Short/sparse PIT history, zero current market overlap, v1 liquidity precision unqualified,
historical funding gaps and funding edge cases, constant fees, missing market-cap and
listing-inception history, incomplete historical search/return matrix, legacy holdovers,
edgeX availability, and curated KNOWN_CRYPTO remain explicit. No paid infrastructure,
account-risk redesign, correlation, MTM, margin or portfolio funding model is introduced.

Audit is v8.audit/8 / v8-phase9.0. Identity/4, discovery/1, history/2, pit/2,
pit-cost/2, pit-research/3 and shadow-ledger/1 remain unchanged.

## Authorized research-label exception

The user explicitly authorized research-label changes to the published quant page and
 dashboard. These are the only published-file parity exceptions: `quant.html`,
`index.html` (from `dashboard.html`), seven string fields in `data/dashboard.json`, and
(GOVERNANCE_METADATA_ONLY) the per-strategy `deployment_state` / `research_state` and the
`strategy_authority` object added to `data/quant.json`.
The exact hashes/field transitions are pinned in the Phase 9 delta manifest. Historical
numbers, signal ordering, Top N, and all other published files must remain identical.

The quant page identifies deployed rows from the policy-derived `Q.strategies`, rather
than historical `verdict=live`. It labels holdovers and all historical results truthfully.
The dashboard removes the quant proven badge and unsupported success claim. Its legacy
serialized `signals[].proven` priority bit remains unchanged solely for ranking
compatibility; it is not a research verdict, and the quant UI never renders it as one.
The legacy risk planner retains its calculations, explicitly marked NOT STRATEGY AUTHORITY.

## Reproducible implementation snapshot

The committed `research/phase9/` artifacts use cutoff 1791840000, market-data commit
`df20b574025b6260c7404dba5cc374c97d131b19` and history commit
`7f69205db89cdd69188a68a6efcfb4ee1c0e8525`. They bind cutoff data, actual history record
hashes and research method source hashes. They are a local implementation snapshot,
not an exact-head CI run. The Research workflow emits separate exact-head provenance
and saves the actual reports on `research`; the independent-review handover records
that run and its hashes. Operational timing is separate from deterministic evidence.

Local Linux differential validation reproduced the base golden and Phase 9 golden:
`a2cebdb88441f2a5e9b7ebfc5c326667e00f7032b64aa8bcc0f117158e5c07f2`
and `c41c6c7fa6c1be028e8aefb8da335c082e45ee4e900cb1cc959cfbd16eb2f12a`.
Zero unexpected deltas; exactly seven dashboard strings, two HTML hashes and seven
quant.json governance metadata values changed.
Windows system-math differences reproduce in the frozen base as well; Linux is the
golden authority. The end-to-end synthetic test exercises qualified closed trades
and byte-identical old-cutoff artifacts after future candle, funding and history appends.
