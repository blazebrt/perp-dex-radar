# v8 Phase 3: identity coverage hardening, discovery separated from execution

Phase 3 is a narrow correctness phase. It **intentionally changes legacy behaviour** in one scope: which coins may
reach a crypto engine. It changes no strategy, threshold, score, stop, target, trailing rule, paper-trade rule,
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

## How identity changes over time

An `UNVERIFIED` asset resolves when positive evidence appears: a venue labels it, it is added to a repository list,
or a verified exposure links to it. Each scan records what was known then. The snapshot writes
`data/v8/identity_state.json` (asset -> [state, since]) and reads the previous scan's copy from the site; every state
change is listed in `coverage.summary.identity.transitions` (asset, from, to, since). Nothing earlier is rewritten:
older snapshots keep their states, and older snapshots that show `DEFAULT_CRYPTO` stay readable
(`RETIRED_IDENTITY_REASONS`).

## Live inventory

The market lists of the Phase 2 live scan (`gh-37605801796-1`: 11,118 raw contracts, 2,022 active perps kept by the
adapters, 850 assets with a coin record), re-resolved with the Phase 3 identity (`tools/v8/rescore_identity.py` on the
research branch's snapshot; reproducible):

| | Phase 2 | Phase 3 |
|---|---|---|
| crypto (`VERIFIED_CRYPTO`) | 613 | 467 |
| tradfi (`VERIFIED_TRADFI`) | 236 | 238 |
| ambiguous | 1 (XIAOMI) | 1 (XIAOMI) |
| unverified | - | 144 |

Default-crypto inventory: Phase 2 admitted **147** assets with `DEFAULT_CRYPTO` (146 only by default; `PRL` also had
an Extended `Crypto` exposure). Now: **144 UNVERIFIED**, **2 VERIFIED_TRADFI** (`SAMSUNGUSD` by the tradfi list,
`SKHYNIXUSD` by its link to the Extended RWA `SKHYNIX`), **1 VERIFIED_CRYPTO** (`PRL`, by its Extended `Crypto`
label), 0 ambiguous. No other asset changed state. The unverified markets are on Aster (128), Lighter (16),
Variational (9) and Hyperliquid (7); a coin can be on several. Unverified assets above the $1M gate (Phase 2 could
trade them): `US100S`, `US500S`, `MOONSHOT`, `GRIFFAIN`, `龙虾`, `UP`, `COCOAP`, `BSV`, `BULLA`, `ACN`.

All 144: US100S, US500S, MOONSHOT, GRIFFAIN, 龙虾, UP, COCOAP, BSV, BULLA, ACN, RESOLV, STABLECOINX, AIN, MARSCOIN,
STONK, TENCENT, NIGHT, SKR, SYN, 牛来, DOS, AI, PAID, TQQQ, CLO, SIREN, SI, ANSEM, AEON, CT, XAI, BANANA, MEME, ZEST,
NOM, SCR, APR, SKYAI, 哈基米, SNXX, BONER, ZCAT, BANK, FUN, FORM, CATE, EDEN, STAR, G, XDP, KO, SLX, LIGHT, ARX,
BASECAT, AIO, PAIR, DRV, PIPPIN, NULLMASK, SPACE, BLUAI, ARGUS, FIGHT, ASTEROID, FUTU, GSTOCK, DELTA, FONE, AT, OPN,
BREW, ROBO, ZKP, 币安人生, PROS, GUN, TMX, AVAAI, CARDS, TOSHI, MUU, FLORK, 4STOCK, POD, TAKE, COAI, SOLV, RATS, JCT,
ZZZ, RIF, RAIL, RONIN, OPN_OPINION, US10Y, BIRB, THE, FRAX, SENT, HANA, AWE, LAPTOP, ACU, AGPU, MAX, NOW, AIW3, TROLL,
MANTRA, USD1, HYUNDAIUSD, CHEEMS, ADBE, BLEND, BAY, 我踏马来了, NES, APRO, SHROOM, KUAISHOU, VERONA, CXMT, STONKS, CTR,
RE_ETH, LISTA, APM, H100, AVL, HYUNDAI, RTX, SDEV, BCHSV, STONKBROKER, V, LYTE, MEITUAN, PUNDIAI, NEX, B-MONEY,
POPMART, BTCDOM, BYD.

The exact-head live Research run of this phase (`research_identity.json` / `.txt` on the `research` branch) adds the
same inventory on fresh market lists, the venue field census, and every production output the identity gate removes
compared with the phase base run on the same live data.

## Differential parity

`tools/v8/delta_parity.py` with `tests/fixtures/v8/phase3_expected_deltas.json` (CI, every run), base main
`82f8d35` (tree `06d80f7`), as in Phase 2, plus:

* the parity fixture declares its fake coins known crypto (`fixture_known_crypto`: the fixture world's identity
  authority; alone it changes no Phase 2 output - verified against `legacy_parity_golden_phase2.json`) and adds the
  Phase 3 cases: `MOONX` (unknown, liquid, with candles, on Hyperliquid and Aster), `NEWCOIN` (new, tiny, no candles),
  `US100S`, `SAMSUNGUSD`, `SKHYNIX`/`SKHYNIXUSD`, `HYUNDAI`/`HYUNDAIUSD`, `US10Y`, `BYD` and `PRLX` (an `Extended`
  `Crypto` coin with a price-separated unlabeled Lighter market);
* `legacy_parity_golden_phase3_base.json` holds main `82f8d35`'s digests on that fixture (CI rebuilds the base and
  checks it), `legacy_parity_golden_phase3.json` this branch's;
* the manifest pins every coin's identity state (`identity_states`) and lists the derived field
  `execution_identity` for every coin that loses it (none gains it);
* the counterfactual (base code, this branch's universe) hands every coin without execution identity to the base
  code as tradfi - the base code's only exclusion - so the only code deltas left are the published lists that now
  tell tradfi from unverified (`coverage.tradfi` as a set, `coverage.unverified`).

Result: 11 universe deltas (`execution_identity` true -> false for `BYD`, `HYUNDAI`, `HYUNDAIUSD`, `MOONX`,
`NEWCOIN`, `US100S`, `US10Y`, `SAMSUNGUSD`, `SKHYNIXUSD`; `tradfi` false -> true for `SAMSUNGUSD`, `SKHYNIXUSD`), 4
DEX crypto-count deltas, 1 price-conflict note no longer emitted (`PRLX`), 2 code deltas plus the 2 matching
decision-summary deltas; 0 unexpected. On the fixture the base code opened quant TSMOM and XSMOM positions on the
unknown `MOONX`; Phase 3 does not, and with `MOONX` out of the cross-section `FAKE27` enters the XSMOM top set - the
unchanged XSMOM ranking responding to a smaller universe, as the counterfactual proves.

## Known remaining identity gaps

* **Real coins are blocked until evidence appears.** Most of the 144 are genuine small coins listed only on Aster,
  Lighter, Variational or Hyperliquid and not on the known-crypto list. They stay visible but cannot be published.
  That is the intended trade-off; promotion needs positive evidence, not a larger hand-maintained list.
* **Aster `underlyingSubType`** (`["Top"]`, `["Meme"]` on crypto markets) and **Lighter's `strategy_index` and
  insurance fund** (seen differing between crypto and stock markets in single-market reads) are undocumented. They
  are recorded per contract (`vmeta`) and counted per identity state in the Research venue field census, never used
  as evidence. A later phase can decide from that census.
* **Rates and commodities without a label** (`US10Y`, `COCOAP`, `US100S`) stay `UNVERIFIED`: no pattern is guessed.
  That blocks them, but does not call them tradfi.
* **Smart money** reads Hyperliquid positions and does not consult the universe identity at all (it never did, for
  tradfi either). It published no signal on an unverified or tradfi coin in the Phase 2 live run (`BSV` and `PAXG`
  appeared as information rows only), but nothing prevents it.
* **One-hop links only.** A parsed-symbol link is not followed further, and it never moves a contract to another
  ticker.
* The legacy row field `tradfi_reason` still says `DEFAULT_CRYPTO` for an unlabeled row: it mirrors the legacy
  `is_tradfi()` and decides nothing since Phase 2 (`exp_reason` and `identity` do).
