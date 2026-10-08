# v8 Phase 3: identity coverage hardening, discovery separated from execution

Phase 3 is a narrow correctness phase. It **intentionally changes legacy behaviour** in one scope: which coins may
reach a crypto engine or become a production signal (radar, quant, swing, day and smart money). It changes no strategy, threshold, score, stop, target, trailing rule, paper-trade rule,
top-N limit, history requirement, liquidity gate ($1M DEX, $5M reference), strategy authority (`FINAL`, `ORDER`) or
data source, and it adds no API. Every output difference from the Phase 2 base (main `82f8d35`) is proven to be an
approved one (see [Differential parity](#differential-parity)).

## The defect

Phase 2 fixed ticker collisions but kept one legacy rule on purpose, because it was out of its scope:

```text
no tradfi evidence  +  no crypto evidence  =  crypto        (exposure reason DEFAULT_CRYPTO)
```

On the Phase 2 live scan (`gh-37605801796-1`, commit `25bf518`) 147 of the 613 coins the engines treated as crypto
were crypto only by that default (146 only by default; `PRL` partly). They include an index at $2.0B a day
(Variational `US100S`), another index (`US500S`), a cocoa contract (`COCOAP`), Korean, Chinese and US stocks listed
without a label (`SAMSUNGUSD`, `SKHYNIXUSD`, `HYUNDAIUSD`, `TENCENT`, `BYD`, `ACN`, `ADBE`, `TQQQ`, `KO`, `V`, ...),
a US 10-year rate (`US10Y`) - and real but unlabeled small coins. Ten of them passed the $1M liquidity gate, and the
live coin picks published one as a swing pick (`龙虾`, short, score 83). Nothing proved any of them was crypto.

## Four identity states

| State | Meaning | Discovery | Crypto execution identity |
|---|---|---|---|
| `VERIFIED_CRYPTO` | positive crypto evidence in the coin's exposure (a venue crypto label, the known-crypto list) and no contrary evidence | yes | **yes** |
| `VERIFIED_TRADFI` | positive tradfi evidence (venue RWA / stock / FX label, the tradfi list or an FX pair, a tradfi name, a parsed venue symbol, or inherited inside a price-coherent exposure) | yes | no |
| `AMBIGUOUS` | conflicting or unrecognised evidence, or unlabeled markets of a ticker that is tradfi elsewhere | yes | no |
| `UNVERIFIED` | no positive evidence either way | yes | no |

Every coin record of the universe carries `identity` (one of the four). `UNVERIFIED` is **not** tradfi (the coin
keeps `tradfi: false`, is never reported with a tradfi reason, and is listed apart: `coverage.unverified`), and it is
**not** crypto-authorized. There are no probabilities: the evidence is listed, not scored.

## Evidence hierarchy

Contract evidence, from the contract's own data (rule 1 of `v8/identity.py`):

| Source field | Venue | Evidence | Authority | Why it is trusted |
|---|---|---|---|---|
| `category` = `RWA`, or a `_24_5` market | Extended | tradfi | `VENUE_METADATA` | the venue's own asset class; every live RWA market is a stock, FX, commodity or index |
| `category` = `Crypto` | Extended | crypto | `VENUE_METADATA` | the venue's own asset class |
| any other `category` (`L1`, `L2`, `Infra`, ...) | Extended | ambiguous | `VENUE_METADATA` | unrecognised label: not guessed |
| `underlyingType` other than `COIN` | Aster | tradfi | `VENUE_METADATA` | the venue's own underlying type |
| `underlyingType` = `COIN` | Aster | **none** | - | Aster sends `COIN` for the stocks it lists too (all ten Phase 1 stock collisions) |
| `underlyingSubType` contains `STOCK`, `ETF`, `Commodities`, `Semiconductor` or `USD1-RWA` | Aster | tradfi | `VENUE_METADATA` | Phase 3 venue field census of the exact-head live scan `gh-37782095629-1`: on 0 markets of a verified crypto exposure (`STOCK`: 98 tradfi, 19 unverified or ambiguous; the other four: 54 tradfi, 8 unverified) |
| `underlyingSubType` `Top`, `Meme`, `AI`, `AOS2`, `pre-launch` | Aster | **none** (recorded) | - | not clean: `Meme` was on a tradfi market, `AOS2` on both; crypto direction would grant authority, so it waits for review |
| market name starts with `Swap on ` (ticker not known crypto) | Variational | tradfi | `CONTRACT_NAME` | Variational's name for its tradfi swaps (`Swap on Gold Spot`, `Swap on US 500`): 9 tradfi, 4 unverified, 0 crypto in the census |
| contract name matches the tradfi name pattern (`Inc`, `Holdings`, `ETF`, ...), ticker not known crypto | Variational, Extended | tradfi | `CONTRACT_NAME` | the legacy `is_tradfi()` rule |
| symbol ends in `USD` on a base-only-symbol venue and the parsed candidate is on the tradfi list or an FX pair | Hyperliquid, Lighter, Variational | tradfi | `PARSED_SYMBOL` | these venues write the base asset only (`BTC`, `ETH`); a trailing quote code names the underlying: `SAMSUNGUSD` -> `SAMSUNG` |
| ... or the candidate ticker has a `TRADFI` exposure within 20% of the contract's price (one hop) | same | tradfi | `PARSED_SYMBOL` | same name and same price as a verified tradfi instrument: `SKHYNIXUSD` -> `SKHYNIX#1` |

Ticker lists (unchanged, not expanded): the repository's `TRADFI` list and FX pairs settle a ticker as tradfi;
`KNOWN_CRYPTO` makes an exposure without contract evidence crypto. Exposures (unchanged from Phase 2): tradfi and
crypto evidence together are `AMBIGUOUS`; tradfi evidence makes the exposure tradfi and its unlabeled contracts
inherit it; crypto evidence makes it crypto; unlabeled exposures of a ticker that is tradfi or ambiguous elsewhere
are `AMBIGUOUS`. **New in Phase 3:** an exposure with none of this is `UNVERIFIED` (reason
`NO_POSITIVE_IDENTITY_EVIDENCE`), never crypto.

Not identity evidence, by design: "not marked tradfi", volatility, price level, 24/7 trading, volume, funding,
popularity, a CEX listing, several unlabeled venues agreeing on a price, and a listing on Hyperliquid's own market
list (Hyperliquid lists `PAXG`, which the repository classes as tradfi, so the venue's list is not crypto-only).

### Symbol parsing, without blind suffix stripping

A parsed candidate is computed only at the venue boundary for venues whose symbols name the base asset only
(`BASE_ONLY_SYMBOL_VENUES`), only for the quote codes in `QUOTE_SUFFIXES` (`USD`), and only when at least two
characters remain. It never changes the contract's ticker (`SAMSUNGUSD` stays its own asset; `HYUNDAIUSD` is not
merged into `HYUNDAI`), it is recorded with its rule on the contract (`parsed`, `link`), and it is evidence in one
direction only: tradfi. A parsed name never grants crypto authority (`BTCUSD` next to `BTC` stays `UNVERIFIED`).
Aster, Extended, dYdX, Paradex and edgeX already split base and quote in their payloads, so they are not parsed.

## Discovery is not execution

* **Discovery:** every active supported perp stays visible whatever its state: in the contract registry
  (`venue:raw_symbol`, with `exp_state`, `evidence`, `parsed`, `link` and the raw venue fields `vmeta`), the asset
  registry (`assets[t].identity`: state, decision, authority, reason, every piece of evidence, links,
  `discovery_eligible`, `execution_identity_eligible`, `promotion`), the universe returned by
  `scanner.build_universe()` (the future discovery universe), the snapshot and every engine's ledger.
* **Execution identity:** `scanner.crypto_authorized(coin)` (`v8.identity.execution_identity_eligible`) is true only
  for `VERIFIED_CRYPTO`; a coin record without an identity fails closed. The radar (scan and study), the quant desk,
  the coin picks (swing and day) and the research coin selection (`tools/fetch_history.py`) apply it before they
  evaluate a coin, so an `UNVERIFIED` coin is never analysed, ranked, paper-traded or published. Its final record in
  every engine is `IDENTITY_UNVERIFIED` (`INSUFFICIENT_DATA`, health `MISSING`) with the evidence path and the
  promotion condition. Identity is a separate gate: liquidity, history and strategy gates are unchanged and still
  apply after it.
* **Smart money** (which reads Hyperliquid positions, not the universe) applies the same authority at its source;
  see [Smart money](#smart-money-the-same-scan-identity-authority). No production signal source - radar, quant, swing,
  day or smart money - confers actionable crypto authority on a coin that is not `VERIFIED_CRYPTO`.
* A price-separated `UNVERIFIED` exposure next to a `VERIFIED_CRYPTO` exposure of the same ticker is not merged into
  the crypto coin (contract state `UNVERIFIED_EXPOSURE_NOT_ADMITTED`, step `UNVERIFIED_EXPOSURE_KEPT_OUT`).

Decision Trace (what `assets[t].identity` and the ledger record show), for a new unknown DEX coin:

```text
raw symbol: aster:NEWCOINUSDT          venue fields: underlyingType COIN (no evidence), baseAsset NEWCOIN
crypto evidence: none                  tradfi evidence: none          ticker lists: none
rule: NO_POSITIVE_IDENTITY_EVIDENCE    result: UNVERIFIED (decision IDENTITY_UNVERIFIED)
discovery: included                    crypto execution identity: blocked
promotion: positive identity evidence on a price-coherent contract
```

and for a stock under a quote-suffixed symbol:

```text
raw symbol: lighter:SAMSUNGUSD         parsed: SAMSUNG (QUOTE_SUFFIX:USD)
tradfi evidence: PARSED_SYMBOL_TRADFI_LIST:SAMSUNG (authority PARSED_SYMBOL)
result: VERIFIED_TRADFI (TRADFI_CLASSIFIED)   discovery: included   crypto execution: blocked
```

## Smart money: the same-scan identity authority

Smart money (`smart.py`) does not build the coin universe: it reads proven Hyperliquid traders' positions and
canonicalises each position's coin. It gets its coins' identity from the scanner of the same scan, never from a second
classifier, a ticker list or the fact that Hyperliquid lists a market:

* **Mechanism.** At the end of `scanner.run()` (next to `latest.json`) the scanner writes
  `data/v8/identity_authority.json` (`v8.identity.write_authority`): every coin of the universe it just resolved,
  `[identity state, decision]`, with the scan id, the scan time and the identity version. In the Scan and Research
  workflows `smart.py` runs right after the scanner in the same job and the same output folder, so it reads that file
  (`v8.identity.load_authority`) instead of rebuilding the universe.
* **Same scan, or nothing.** The file is accepted only when its identity version is this code's and it belongs to
  this scan: in GitHub Actions the scan ids (`gh-<run>-<attempt>`) must be equal; offline (local scan ids, the parity
  harness and tests) the file must be within 6 hours of the smart run. Anything else - no file, an unreadable file,
  another scan, another identity version, a stale file - gives an authority with no states.
* **The gate, at the source.** A crowd on a coin whose state is not `VERIFIED_CRYPTO` (or that no usable same-scan
  authority names) is not a signal, not an information-only crowd, not tested or proven, has no side and opens no
  paper trade. The row stays in `smart.json` as an observation - traders, long and short counts, new positions,
  money, the crowd's text - with `identity` and `identity_block` (`reason`, `state`, the crowd side and whether it
  would have been a signal). Every row carries `identity`; `smart.json` names the authority it used
  (`identity_authority`: ok, why, scan id, time, coins, source).
* **Fail closed.** Without a same-scan authority no crowd gets authority (`IDENTITY_AUTHORITY_MISSING`); the
  observations are still published.
* **Downstream.** The dashboard's signal aggregation and the Smart Money page use `signal` / `info`, which a blocked
  row never has. The Analyzer (`analyze.js`) also checks, as defense in depth, that a smart signal's row is
  `VERIFIED_CRYPTO` before `testedSignals()` or `signalCoins()` accept it, and explains a blocked crowd as a note.
* **Audit.** The smart ledger records a blocked crowd with its identity reason - `IDENTITY_UNVERIFIED`,
  `TRADFI_CLASSIFIED` / `TRADFI_EXPOSURE_EXCLUDED`, `AMBIGUOUS_EXPOSURE` or `IDENTITY_AUTHORITY_MISSING` - and the
  step `SMART_CROWD_IDENTITY_BLOCKED`, never as `SMART_NO_CROWD`; the smart part's stages count rows by identity and
  list the blocked crowds. For a `VERIFIED_CRYPTO` coin nothing changes: crowd detection, signal side, tested /
  promising / proven reading, paper trade, stop, holding period and statistics are the same (differential parity:
  `smart.json` and `smart_journal.json` differ from the base only by additive identity and provenance fields).

### Entry-time identity of smart paper trades (the live evidence record)

> **Current identity controls NEW execution authority.**
>
> **Entry-time identity provenance controls whether a historical smart paper trade belongs to the production live
> evidence record.**

The gate above keeps a non-verified crowd from opening a paper trade. The live record (`accuracy.live`, `live_info`
and, after 40 live trades, the verdict that the page, the dashboard and the Analyzer read) must also be built only
from trades that had that authority. Whether a trade belongs to it is decided once, when it is opened, never later:

* **New trades carry their proof.** Every paper trade the engine opens records, once and immutably (`stamp_identity`):
  `identity_state_at_entry` (`VERIFIED_CRYPTO`), `identity_qualified` (`true`), `identity_version`
  (`v8.identity/2`), `identity_scan_id` (the same-scan authority it was opened under) and `identity_decision`.
* **Only proven trades count.** `trade_qualified()` requires all of it: `identity_qualified` true,
  `identity_state_at_entry` `VERIFIED_CRYPTO`, a scan id and an identity version. `accuracy()` builds `live`,
  `live_info` and the verdict from qualified closed trades only. `kind == "signal"` alone no longer qualifies a trade.
* **Legacy trades are kept, not trusted.** A trade written before Phase 3 has none of these fields. The engine keeps
  it as it is - prices, stop, times, kind, return, R - and marks it `identity_qualified: false`,
  `identity_unqualified_reason: LEGACY_NO_IDENTITY_PROOF`, `identity_state_at_entry: null` (`mark_legacy`, right
  after the journal is loaded, so before `proven_rule` is decided). Its validity is never inferred from the coin's
  current identity. An open legacy trade is still followed to its stop or time limit and closed for continuity (it
  keeps its coin's one paper-trade slot until then, at most 24 hours); its result never enters the live record.
* **No hindsight in either direction.** A trade opened under `VERIFIED_CRYPTO` stays qualified when a later scan
  makes the coin `UNVERIFIED`, `VERIFIED_TRADFI` or `AMBIGUOUS`, or when that later scan has no authority file: the
  current identity blocks a new signal and a new Analyzer call, never the historical fact. A legacy trade is never
  re-qualified by a later scan either.
* **The boundary is inspectable.** `smart.json` `accuracy` adds `evidence` (qualified and unqualified trades, open
  and closed, signal and information side, with the reasons) and `legacy_unqualified` (the unqualified closed trades'
  statistics, apart). Trade records in `open` / `closed` carry their provenance. The audit's smart part (and the
  snapshot's `coverage.engines.smart.journal`) lists every unqualified trade with its reason; a coin with an open
  legacy trade gets the step `PAPER_LEGACY_NO_IDENTITY_PROOF`. Trade-level codes: `IDENTITY_QUALIFIED`,
  `LEGACY_NO_IDENTITY_PROOF`, `NOT_VERIFIED_AT_ENTRY`, `IDENTITY_PROOF_INCOMPLETE` (taxonomy `TRADE_IDENTITY`).

The published journal when this closure was built (the `journal-data` copy of 2026-10-08 15:03 UTC, read-only:
`tools/v8/smart_journal_evidence.py`) holds 36 trades, none with entry-time proof: 11 open (5 signal: UNI, ETH, SOL,
NEAR, XRP; 6 information: HYPE, TAO, ZEC, PUMP, ENA, BTC) and 25 closed (10 signal, 15 information). Under these
rules the production live record drops from 10 trades (R 0.829) to 0; all 36 stay in the journal and on the page,
reported as `legacy_unqualified`. The verdict stays "Promising": 10 was below the 40 trades needed for the live
record to decide anyway. Each Research run repeats this accounting on the latest published journal
(`research_smart_journal.json`).

The same two rules - current identity for actionability, entry-time proof for evidence - were extended to the quant
desk and to live radar paper trades by the production-evidence closure after the first production scan of merged
Phase 3: see [phase3-production-evidence-closure.md](phase3-production-evidence-closure.md).

## How identity changes over time

An `UNVERIFIED` asset resolves when positive evidence appears: a venue labels it, it is added to a repository list,
or a verified exposure links to it. Each scan records what was known then. The snapshot writes
`data/v8/identity_state.json` (asset -> [state, since]) and reads the previous scan's copy from the site; every state
change is listed in `coverage.summary.identity.transitions` (asset, from, to, since). Nothing earlier is rewritten:
older snapshots keep their states, and older snapshots that show `DEFAULT_CRYPTO` stay readable
(`RETIRED_IDENTITY_REASONS`).

## Live inventory

The market lists of the live Research scan of this branch (`gh-37782095629-1`, 2026-10-08: 11,463 raw contracts,
2,016 active perps kept by the adapters, 852 assets with a coin record), re-resolved with the final Phase 3 rules
(`tools/v8/rescore_identity.py` on that scan's snapshot, which keeps the raw venue fields; reproducible). The Phase 2
column is the Phase 2 identity on the same lists (recorded per asset as `identity.phase2`):

| | Phase 2 | Phase 3 |
|---|---|---|
| crypto (`VERIFIED_CRYPTO`) | 615 | **467** |
| tradfi (`VERIFIED_TRADFI`) | 236 | **262** |
| ambiguous | 1 (XIAOMI) | **0** |
| unverified | - | **123** |
| execution identity | 615 | **467** |
| discovery-visible | 852 | **852** |

Default-crypto inventory: Phase 2 admitted **149** assets with `DEFAULT_CRYPTO` on these lists (148 only by default;
`PRL` also had an Extended `Crypto` exposure). Now: **123 UNVERIFIED**, **25 VERIFIED_TRADFI**, **1 VERIFIED_CRYPTO**
(`PRL`, its Extended `Crypto` label), 0 ambiguous. The 25 tradfi: `ACN`, `ADBE`, `AGPU`, `COCOAP`, `CXMT`, `FUTU`,
`GASOLP`, `HYUNDAI`, `HYUNDAIUSD` (link to `HYUNDAI`), `KUAISHOU`, `LYTE`, `MEITUAN`, `MOONSHOT`, `MUU`, `NOW`,
`POPMART`, `SAMSUNGUSD` (tradfi list), `SDEV`, `SKHYNIXUSD` (link to `SKHYNIX`), `SNXX`, `TENCENT`, `TQQQ`, `US100S`,
`US500S`, `V` (Aster `STOCK` / `ETF` subtypes, Variational `Swap on` names, parsed symbols). One more asset changed
state: `XIAOMI`, `AMBIGUOUS` -> `VERIFIED_TRADFI` (Aster tags its USD market `STOCK`; it stays out of every engine).
No verified-crypto asset lost or gained authority beyond the default-crypto inventory. The unverified markets are on
Aster (110), Lighter (13), Hyperliquid (7) and Variational (6); a coin can be on several. Unverified assets above the
$1M gate (Phase 2 could trade them): `龙虾`, `AIN`, `GRIFFAIN`, `UP`.

All 123: 龙虾, AIN, GRIFFAIN, UP, MARSCOIN, STABLECOINX, 牛来, SKR, STONK, RESOLV, AI, SYN, DOS, 币安人生, BANANA,
CLO, BSV, CT, ANSEM, XAI, NIGHT, APR, BANK, SI, MEME, AEON, BONER, BULLA, PAID, CATE, ZEST, OPN_OPINION, LAPTOP, EDEN,
DRV, SCR, SLX, SKYAI, ZCAT, TAKE, XDP, ASTEROID, 4STOCK, ARGUS, PROS, NOM, ARX, SIREN, AT, TMX, BLUAI, 哈基米, AIO,
OPN, SPACE, FUN, FORM, BREW, NULLMASK, AVAAI, STAR, US10Y, PAIR, FONE, TOSHI, ROBO, GSTOCK, HANA, FIGHT, SENT, CARDS,
AIW3, BIRB, BASECAT, ZKP, ACU, RATS, RIF, FLORK, FRAX, RAIL, H100, CTR, SOLV, PIPPIN, MAX, JCT, BAY, POD, APM, G,
RE_ETH, LIGHT, COAI, THE, 我踏马来了, SHROOM, GUN, MANTRA, APRO, RONIN, KO, ZZZ, DELTA, TROLL, PUNDIAI, STONKBROKER,
STONKS, BLEND, USD1, AWE, BTCDOM, VERONA, AVL, LISTA, CHEEMS, NEX, BCHSV, RTX, B-MONEY, NES, VARIATIONAL, BYD.

On the older Phase 2 live lists (`gh-37605801796-1`, whose snapshot predates the raw venue fields, so only the
parsed-symbol rules apply) the same resolver gives 467 crypto, 238 tradfi, 1 ambiguous, 144 unverified out of the 147
default-crypto assets (2 tradfi: `SAMSUNGUSD`, `SKHYNIXUSD`; `PRL` crypto).

Each Research run of this branch (`research_identity.json` / `.txt` on the `research` branch) recomputes the
inventory on fresh market lists, with the venue field census and every production output the identity gate removes
compared with the phase base run on the same live data.

## Differential parity

`tools/v8/delta_parity.py` with `tests/fixtures/v8/phase3_expected_deltas.json` (CI, every run), base main
`82f8d35` (tree `06d80f7`), as in Phase 2, plus:

* the parity fixture declares its fake coins known crypto (`fixture_known_crypto`: the fixture world's identity
  authority; alone it changes no Phase 2 output - verified against `legacy_parity_golden_phase2.json`) and adds the
  Phase 3 cases: `MOONX` (unknown, liquid, with candles and a strong trend so every later gate can pass, on
  Hyperliquid and Aster), `NEWCOIN` (new, tiny, no candles), `US100S` (Variational `Swap on ...`), `ADBE` (Aster
  `STOCK` subtype), `SAMSUNGUSD`, `SKHYNIX`/`SKHYNIXUSD`, `HYUNDAI`/`HYUNDAIUSD` (without a subtype: the link that
  decides nothing), `US10Y`, `BYD` and `PRLX` (an Extended `Crypto` coin with a price-separated unlabeled Lighter
  market);
* `legacy_parity_golden_phase3_base.json` holds main `82f8d35`'s digests on that fixture (CI rebuilds the base and
  checks it), `legacy_parity_golden_phase3.json` this branch's;
* the manifest pins every coin's identity state (`identity_states`) and lists the derived field
  `execution_identity` for every coin that loses it (none gains it);
* the counterfactual (base code, this branch's universe) hands every coin without execution identity to the base
  code as tradfi - the base code's only exclusion - so the only code deltas left are the published lists that now
  tell tradfi from unverified (`coverage.tradfi` as a set, `coverage.unverified`).

Result: 14 universe deltas (`execution_identity` true -> false for `ADBE`, `BYD`, `HYUNDAI`, `HYUNDAIUSD`, `MOONX`,
`NEWCOIN`, `SAMSUNGUSD`, `SKHYNIXUSD`, `US100S`, `US10Y`; `tradfi` false -> true for `ADBE`, `SAMSUNGUSD`,
`SKHYNIXUSD`, `US100S`), 4
DEX crypto-count deltas, 1 price-conflict note no longer emitted (`PRLX`), 2 code deltas plus the 2 matching
decision-summary deltas; with the smart-money closure, 4 additive `smart.json` fields (`identity` on the three smart
rows, all `VERIFIED_CRYPTO`, and `identity_authority`) and `analyze.js` pinned to its exact base and head digests
(`files`); and, with the journal closure, the five entry-time provenance fields on each of the fixture's two fresh
paper trades (`FAKE02` signal, `FAKE03` information; both `VERIFIED_CRYPTO`, qualified) in `smart.json` and
`smart_journal.json` (20 values, each pinned by trade id and field) plus `accuracy.evidence` and
`accuracy.legacy_unqualified`; 0 unexpected. Every other smart value - signals, information crowds, entries, prices,
stops, holding periods, `live`, `live_info`, the verdict - is unchanged. On the fixture the base code opened quant TSMOM and XSMOM positions on the
unknown `MOONX`; Phase 3 does not, and with `MOONX` out of the cross-section `FAKE27` enters the XSMOM top set - the
unchanged XSMOM ranking responding to a smaller universe, as the counterfactual proves.

## Known remaining identity gaps

* **Real coins are blocked until evidence appears.** Most of the 144 are genuine small coins listed only on Aster,
  Lighter, Variational or Hyperliquid and not on the known-crypto list. They stay visible but cannot be published.
  That is the intended trade-off; promotion needs positive evidence, not a larger hand-maintained list.
* **Crypto-direction venue fields are not used.** Aster's `Top`, `Meme`, `AI` subtypes and Lighter's
  `strategy_index` / insurance fund index (seen differing between crypto and stock markets in single-market reads)
  are recorded per contract (`vmeta`) and counted in the Research venue field census. Using any of them would grant
  execution authority, so that decision is left to review (Phase 4 candidate). The tradfi-direction values used here
  were chosen from one live census; a venue renaming them makes those markets `UNVERIFIED` again, never crypto.
* **Instruments with no label anywhere** (`US10Y` and `BYD` on Lighter; Aster stocks without a subtype; pre-launch
  tokens like `VARIATIONAL`) stay `UNVERIFIED`: no pattern is guessed. That blocks them, but does not call them
  tradfi.
* **One-hop links only.** A parsed-symbol link is not followed further, and it never moves a contract to another
  ticker.
* The legacy row field `tradfi_reason` still says `DEFAULT_CRYPTO` for an unlabeled row: it mirrors the legacy
  `is_tradfi()` and decides nothing since Phase 2 (`exp_reason` and `identity` do).
