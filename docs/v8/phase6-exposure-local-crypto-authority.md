# Phase 6: exposure-local positive crypto authority (`v8.identity/4`)

## The defect

The repository's known-crypto list (`scanner.KNOWN_CRYPTO`) names tickers. The universe is built from price-coherent
exposures: the contracts of one ticker within 20% of an anchor price form one exposure, and a ticker can carry several
of them, such as a coin and a stock that share a symbol. Up to `v8.identity/3`, every otherwise-unlabeled priced exposure
of a listed ticker received the list's crypto authority. Two exposures 300x apart could both be "the" known crypto
asset.

That was safe only while some deterministic negative evidence removed every non-crypto exposure:
* QNT: Extended RWA.
* PURR: Extended RWA.
* BB: Lighter token-list RWA and Extended RWA.

A future stock, RWA or unrelated token under a known-crypto ticker, listed on a venue that sends no asset class, would
have inherited crypto authority from the ticker alone. This was item 33 of
[known-legacy-behavior.md](known-legacy-behavior.md).

## The rule (rule 4a of `v8/identity.py`)

The ticker-level assertion and its exposure binding are now separate steps.

1. **Input.** A ticker on the list means one crypto asset exists under it. The audit keeps this as the evidence row
   `ticker:<T> CRYPTO TICKER_KNOWN_CRYPTO TICKER_LIST`.
2. **Deterministic evidence first.** Each exposure's contract evidence classifies it:
   * Tradfi: Extended RWA, `_24_5`, Aster underlyingType or tradfi subtypes, Lighter token-list RWA, Variational
     `Swap on`, tradfi names, parsed-symbol links.
   * Ambiguous: conflicting or unrecognized evidence.
   * Direct crypto: none exists today; `QUALIFIED_CRYPTO_RULES` is empty.

   None of these exposures is a binding candidate.
3. **Set aside, never candidates:**
   * An exposure all of whose contracts are on a venue whose exposure check did not run this scan. It stays
     `EXPOSURE_CHECK_UNAVAILABLE`, as in Phase 5.
   * An exposure without a price. It becomes `UNPRICED_NO_CONTRACT_EVIDENCE`.

   Neither kind takes the binding or competes for it.
4. **Candidates** are the priced exposures left. One exposure is one candidate, however many venues it spans.
5. **Result:**

   | Candidates | Exposure class / reason | `ticker_authority.result` |
   |---|---|---|
   | exactly 1, no direct-crypto exposure | `CRYPTO` / `TICKER_KNOWN_CRYPTO_BOUND`, authority `TICKER_LIST` | `BOUND` |
   | more than 1 | each `UNVERIFIED` / `TICKER_CRYPTO_EXPOSURE_UNBOUND` | `UNBOUND_MULTIPLE_CANDIDATES` |
   | 1 or more beside a direct-crypto exposure | each candidate `UNVERIFIED` / `TICKER_CRYPTO_EXPOSURE_UNBOUND` | `UNBOUND_DIRECT_CRYPTO_EVIDENCE` |
   | none | nothing bound | `NO_BINDABLE_EXPOSURE` |

6. **Asset state (rule 5, unchanged).**
   * Any CRYPTO exposure makes the asset `VERIFIED_CRYPTO`, and only the crypto exposures form the coin record.
   * Otherwise, any UNVERIFIED exposure makes it `UNVERIFIED`. The coin record is the record of its UNVERIFIED
     exposures, exactly as before.
   * Otherwise the asset is `VERIFIED_TRADFI` or `AMBIGUOUS`.

Lack of a binding is `UNVERIFIED`, never `AMBIGUOUS`. `AMBIGUOUS` still means trusted economic evidence that conflicts.

**Nothing chooses.** Rule 4a reads no volume, venue count, open interest, spread, Hyperliquid presence, age, market-list
order or majority. The outcome depends only on how many candidates are left. `tests.test_v8_phase6` checks this:
every permutation of volumes, open interests and market-list order gives the same result. Liquidity and popularity are
not identity.

**What did not change.** All Phase 5 negative evidence and its fail-closed exposure check are unchanged, as are
`QUALIFIED_CRYPTO_RULES = ()` and the known-crypto list itself. No new external data is used: no CoinGecko, no
CoinMarketCap, no model, no third-party token database.

## Stage A: the live census before the rule

`tools/v8/ticker_binding.py` takes v8 audit snapshots and does the following:
* Resolves every contract under the v3 rules (reproduced exactly first).
* Takes a census of every known-crypto ticker: its exposures, contracts, venues, prices per coin, direct economic
  evidence, wrapper evidence, exposure checks, class, authority, category, and whether the list is what verifies it.
* Computes models 1-3 and the projected impact, with open positions and published outputs from the journal-data
  branch.
* Audits the known-crypto list.
* Recomputes model 2 independently, from the v3 exposure classes alone, and compares it with this checkout's
  `v8.identity/4`. `v4_check` must report 0 differences.

Two live observations were used. The first reproduced with 0 differences.
* `gh-37984238598-1`: Research on Phase 5 head `bf88b17`, which has the same tree as main `f7aa7f6`. 854 assets.
* `gh-38064191210-1`: the latest production scan on `f7aa7f6`. Lighter token list OK, 213 of 213 markets.

| | `gh-37984238598-1` | `gh-38064191210-1` |
|---|---|---|
| Known-crypto tickers with a live market (list: 436) | 434 | 433 |
| … with a single priced exposure | 431 | 430 |
| … with several priced exposures | 3 (BB, PURR, QNT) | 3 (BB, PURR, QNT) |
| … with explicit tradfi evidence | 3 | 3 |
| … with an unverified or unchecked exposure | 0 | 0 |
| … with more than one bindable unlabeled exposure | **0** | **0** |
| Unpriced only | 0 | 0 |
| Verified only by the list | 434 | 433 |
| All live exposures tradfi | 0 | 0 |
| No live market | 2 (BLAST, HFUN) | 3 |

Every known-crypto asset in the live universe depends on the list: no other positive crypto authority exists.

**Model 1** (`v8.identity/3`) verifies every candidate.

**Model 2** (single-candidate binding) gives 434 / 433 `BOUND` and **0 transitions**:
* QNT binds `QNT#1`. `QNT#2` (Extended RWA, about 41 against 243) is removed by its own evidence.
* PURR binds `PURR#1`. `PURR#2` (Extended RWA) is removed the same way.
* BB binds `BB#2` (BounceBit, about 0.009). `BB#1` (BlackBerry, about 8.9; Lighter RWA and Extended RWA) is removed.

No open position is on a projected transition. The journal-data snapshot of 2026-10-10T15:39Z has 37 assets with an
open position, none of them projected to change.

**Model 3** (heuristic winner) was evaluated only. With the BlackBerry exposure's negative evidence withheld:
* "highest volume" picks BlackBerry (BB#1) over BounceBit;
* "highest open interest" picks BounceBit, but only because venues report open interest in different units
  (contracts or USD). Converted to USD, it also picks BlackBerry;
* "most venues" is a 2-2 tie, broken by list order;
* "on Hyperliquid" picks nothing, because neither BB exposure is on Hyperliquid.

The heuristics disagree with one another, and the one most likely to be used would have made BlackBerry the crypto
BB. Model 3 is unsafe and is not implemented.

**A zero-transition live outcome is expected.** It is not a reason to skip the phase: the general path is closed for
future collisions, and the synthetic and fixture tests prove the rule. The parity fixture has a known-crypto coin with a
second, 30%-away market (FAKE07), and it moves `VERIFIED_CRYPTO -> UNVERIFIED` exactly as the rule says.

## Audit

* **Per asset:** `identity.ticker_authority` records the following fields:
  * `ticker` and `known_crypto`;
  * `bindable_exposures`, with their `candidate_prices`;
  * `selected_exposure` and `result`;
  * `excluded`, giving each other exposure with its reason: `TRADFI_EVIDENCE`, `AMBIGUOUS_EVIDENCE`,
    `EXPOSURE_CHECK_UNAVAILABLE`, `UNPRICED` or `DIRECT_CRYPTO_EVIDENCE`;
  * `direct_crypto_exposures`, `check_blocked_exposures`, `tradfi_exposures`, `ambiguous_exposures` and
    `unpriced_exposures`;
  * `statement` and `effect`.

  Each exposure carries `binding`: `SELECTED`, `UNBOUND`, `CHECK_BLOCKED` or `UNPRICED`.
* **Decision Trace:** `exposure_trace.binding` records:
  * input: `KNOWN_CRYPTO ticker = true`;
  * the candidates;
  * one rule line per exposure, plus the conclusion, for example "2 candidates are price-separated; ticker-level
    identity cannot distinguish them";
  * result: `NO UNIQUE EXPOSURE BINDING` or `UNIQUE EXPOSURE BINDING`;
  * effect.

  Nothing is rejected silently.
* **Counts:** `registry.counts.ticker_authority`, summarised in `coverage.summary.identity.ticker_authority`:
  * `known_crypto_assets`, `ticker_crypto_bindings`, `ticker_crypto_unbound_assets`,
    `ticker_crypto_unbound_exposures` and `ticker_crypto_no_bindable_exposure`;
  * `ticker_crypto_blocked_by_exposure_check`, `ticker_crypto_with_tradfi_collision` and
    `ticker_crypto_with_direct_crypto_evidence`;
  * `by_result`, `unbound` and `multi_exposure`;
  * `binding_candidates` and `unaccounted`, where `unaccounted` = candidates − bound − unbound, plus known assets
    without exactly one result. It is always 0.
* **List audit:** `registry.counts.known_crypto_list` gives `entries`, `in_live_universe`, `one_priced_exposure`,
  `multiple_priced_exposures`, `unpriced_only`, `all_live_exposures_tradfi` and `no_live_market`. It is
  observability only; the list is not changed.
* **Before/after:** `previous` is now the `v8.identity/3` result on the same contracts.
  `exposure_safety.transitions_vs_previous` lists every asset the binding moved.

## Version and compatibility

* `v8.identity/4`, with `PREVIOUS_VERSION = v8.identity/3`.
* `VERSION_RULES` makes rule selection explicit: v2 → 2, v3 → 3, v4 → 4. `identity.resolve_version(version, ...)`
  reproduces any of them. The census, exposure-safety and ticker-binding tools replay each snapshot by the version
  that recorded it, and historical snapshots are never rewritten.
* The identity config hash changes because `rules`, `previous_version` and `ticker_binding` were added.
* A same-scan identity authority file written by v3 (or v2) fails a v4 consumer with
  `OTHER_IDENTITY_VERSION:v8.identity/3`. Smart money then qualifies nothing from it.
* New paper trades stamp `identity_version = v8.identity/4`. Trades entered under v2 or v3 with complete
  `VERIFIED_CRYPTO` proof stay historically qualified (no hindsight). If v4 downgrades such a coin:
  * the trade keeps its proof and its paper lifecycle;
  * current actionability follows v4 (quant `blocked_open`; dashboard, Analyzer and smart money blocked; radar,
    swing and day never evaluate it).
* Audit `v8.audit/4` (unchanged; no new contract column) and `audit_version` `v8-phase6.0`.

## Fallback universe

Unchanged: the built-in list is used only when every DEX market list failed (`any_ok` false). A partly degraded scan
resolves the venues that answered through rule 4a. `tests.test_v8_phase6.Fallback` tests both paths.

## Residual limits (see also [known-legacy-behavior.md](known-legacy-behavior.md), items 36-37)

* **Availability cost (item 36).** A known-crypto coin with a stray venue more than 20% away is `UNVERIFIED` and
  blocked for that scan. The stray venue might be stale, mispriced, a different contract size not normalised by the
  symbol, or a different asset. The legacy record would have dropped that venue as a price conflict and kept the
  coin. Live: 0 known-crypto tickers in both observations. Fixture: FAKE07.
* **Exposure-check outage (item 37).** As the brief requires, an exposure blocked by a failed exposure check does not
  compete for the binding. Take a known-crypto ticker that has, besides its unlabeled exposure, a price-separated
  Lighter-only exposure that the token list does not label RWA. With the token list OK, the ticker has two candidates
  and is unbound. During a token-list outage the Lighter exposure is blocked, so the other one binds. That outage
  binding never grants more than `v8.identity/3` granted. It is visible as `ticker_crypto_blocked_by_exposure_check`
  and in `check_blocked_exposures`. Live: 0 such tickers.
* Positive crypto authority still depends on the curated known-crypto list: it is the only positive authority.

## Tests

`tests/test_v8_phase6.py` covers:
* the collision matrix of the brief: one candidate; two; one plus tradfi (each tradfi source); two plus tradfi;
  failed check (each check state); two failed checks; two plus failed check; direct crypto plus an extra exposure;
  tradfi only; unpriced only; true conflict; QNT; PURR; BB, including BB under outages and without negative evidence;
* ZKNOWN;
* same-price multiple venues;
* "nothing chooses" (the permutation test);
* the positive and negative controls;
* the Decision Trace;
* the counts, with unaccounted 0;
* the list audit;
* v4 with v3 as `previous`, and v2/v3 replay;
* the Stage A tool's model 2 agreeing with the resolver on every matrix shape;
* the config hash;
* v3 authority files failing a v4 consumer;
* entry proofs;
* the downgrade reaching every gate (radar, quant, dashboard, the Analyzer through `analyze.js`, smart money);
* the fallback universe.

`ScanGateInvariants` runs in the scheduled-scan gate. `tests.test_v8_audit.test_ticker_binding_end_to_end` and
`test_phase6_manifest_is_the_phase_base` check the parity fixture end to end.

## Differential parity

`tests/fixtures/v8/phase6_expected_deltas.json` has base production main `f7aa7f6` (tree `aff2774`) and base golden
`legacy_parity_golden_phase5.json`; the head golden is `legacy_parity_golden_phase6.json`. It allows exactly these
deltas:
* FAKE07 `execution_identity` true → false and `identity` `VERIFIED_CRYPTO` → `UNVERIFIED`
  (`TICKER_CRYPTO_EXPOSURE_UNBOUND`);
* the three DEX crypto counts that follow (dYdX 2 → 1, Hyperliquid 40 → 39, Variational 34 → 33);
* the published unverified/tradfi lists (FAKE07 joins `coverage.unverified`);
* the identity version v3 → v4 on the entry-time proof of the trades the run opens.

There are 0 unexpected deltas. Every other BASE → HEAD output difference is the unchanged engines responding to FAKE07
leaving the crypto universe: radar and quant counts, and picks lists without FAKE07.
