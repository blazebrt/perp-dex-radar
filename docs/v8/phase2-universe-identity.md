# v8 Phase 2: universe identity and missing-liquidity semantics

Phase 2 is a narrow correction of what the coin universe contains and of what a missing 24h volume means. It
**intentionally changes legacy behaviour** in that scope only. It changes no strategy, threshold, score, stop,
target, trailing rule, paper-trade rule, top-N limit, history requirement, strategy authority (`FINAL`, `ORDER`) or
data source, and adds no API.

## The two defects (found by the Phase 1 audit)

1. **Ticker-level tradfi contamination.** `build_universe()` merged every market of a ticker and OR-ed the tradfi
   flag over all of them, then dropped markets more than 20% from the main price as "another asset" - but the flag
   they had set survived. One real-world-asset market listed under a crypto ticker hid the crypto coin from every
   engine. The live scan of 2026-10-06 (gh-37475517788-1) had 13 such collisions; QNT, PURR and BB were crypto
   coins lost that way. The other ten were real stocks that some venue listed **without** a label, so the opposite
   fix ("any venue says crypto") would have let stocks in.
2. **Missing volume read as $0.** `(liq_of(coin) or 0) >= $1M`, and a universe that kept only truthy volumes, made a
   venue reporting nothing indistinguishable from a venue reporting exactly 0.

### The 13 live collisions of the Phase 1 scan (gh-37475517788-1, 2026-10-06)

Price per coin and 24h volume as the audit recorded them; "label" is the venue's own label.

| Ticker | Markets (venue: price, volume, label) | Phase 1 | Phase 2 rule |
|---|---|---|---|
| QNT | Variational 257.89 ($1.48M), Aster 255.93 ($2.43M, COIN), Lighter 255.94 ($336k); Extended 46.03 ($386k, RWA); dYdX inactive | excluded | crypto exposure admitted (known crypto); RWA exposure out |
| PURR | Hyperliquid 0.1536 ($3.09M); Extended 12.77 ($3k, RWA, "Hyperliquid Strategies Inc.") | excluded | crypto exposure admitted; RWA out |
| BB | Variational BBIT 0.00972 ($76), Aster 0.00976 ($5.9k, COIN); Lighter 9.64 ($262k, none), Extended 9.61 ($40, RWA) | excluded | crypto exposure admitted (still below $1M: not executable); stock exposure out, Lighter inherits RWA |
| ASTS | Aster 64.46 (COIN), Extended 64.66 (RWA) | excluded | one exposure, tradfi, Aster inherits |
| COHR | Aster 339.14 (COIN), Extended 336.56 (RWA) | excluded | tradfi, inherited |
| FLNC | Variational 8.04 (name "... Inc"), Aster 7.68 (COIN), Extended 8.13 (RWA) | excluded | tradfi |
| GLW | Aster 163.66 (COIN), Extended 164.82 (RWA, $0) | excluded | tradfi, inherited |
| KIOXIA | Lighter 118.44 ($0, none), Extended 119.02 ($0, RWA) | excluded | tradfi, inherited |
| KORU | Aster 22.12 (COIN), Lighter 22.10 ($0, none), Extended 22.11 (RWA) | excluded | tradfi, inherited |
| MINIMAX | Aster 31.71 (COIN), Lighter 31.69 (none), Extended 31.68 (RWA) | excluded | tradfi, inherited |
| ONDS | Variational 7.48 ("Ondas Holdings Inc."), Aster 7.56 (COIN) | excluded | tradfi (name), Aster inherits |
| SKHYNIX | Aster 1333.93 and 1335.40 (COIN, two markets), Extended 1334.15 (RWA); Lighter inactive | excluded | tradfi, inherited |
| XIAOMI | Aster 3.114 (COIN), Lighter 3.0886 ($842k, none); Extended 24.19 (RWA, HKD) | excluded | Aster/Lighter exposure ambiguous (no crypto evidence under a tradfi collision); RWA out |

## Architecture: contract -> exposure -> asset

`v8/identity.py` is the one authority (scanner, quant and picks all get their universe from
`scanner.build_universe()`, which calls it). The adapters only pass the raw metadata on (Aster `underlyingType`,
Extended `category`).

```
raw venue contract (venue:raw_symbol)
  -> 1. contract classification from its own evidence
  -> 2. price-coherent exposures per ticker (prices per 1 coin)
  -> 3. exposure class CRYPTO / TRADFI / AMBIGUOUS
  -> 4. the legacy coin record from the admitted crypto exposure only
```

### 1. Contract evidence

| Evidence | Class | Authority |
|---|---|---|
| Extended category `RWA` (stocks, FX, commodities, indices in the live data) | TRADFI | VENUE_METADATA |
| Extended `_24_5` market | TRADFI | VENUE_METADATA |
| Extended category `Crypto` | CRYPTO (until v8.identity/2; since Phase 5, `v8.identity/3`, wrapper evidence only - see [phase5-economic-exposure.md](phase5-economic-exposure.md)) | VENUE_METADATA |
| any other Extended category (`L1`, `L2`, `Infra` were seen) | AMBIGUOUS | VENUE_METADATA |
| Aster `underlyingType` other than `COIN` | TRADFI | VENUE_METADATA |
| Aster `underlyingType` `COIN` | no evidence: Aster sends `COIN` for the stocks it lists too | - |
| contract name matches the tradfi name pattern (`Inc`, `Holdings`, `ETF`, ...) and the ticker is not on the known-crypto list (the legacy precedence of `is_tradfi`) | TRADFI | CONTRACT_NAME |
| tradfi and crypto evidence on one contract | AMBIGUOUS | VENUE_METADATA |
| nothing (Hyperliquid, Lighter, dYdX, Paradex, edgeX send no such metadata) | UNLABELED | NONE |

### 2. Price-coherent exposures

The priced contracts of a ticker are grouped deterministically: the contract with the most 24h volume (the first in
market-list order on a tie) anchors an exposure and takes every contract within 20% of its price per coin - the
legacy price-conflict tolerance; the most traded of the rest anchors the next exposure, and so on. Prices are per 1
coin, so `kPEPE`, `1000PEPE` and `PEPE` compare correctly, and an RWA quoted like the x1000 contract does not.
A contract **without a price** never joins a priced exposure and never changes one: it is its own exposure (`T#u1`).
A ticker with no priced contract at all is one exposure.

### 3. Exposure class

1. Ticker on the repository's tradfi list or an FX pair: TRADFI (unchanged legacy lists).
2. Otherwise, from the contracts **inside the exposure only**: tradfi and crypto evidence together: AMBIGUOUS;
   tradfi evidence: TRADFI, and the unlabeled contracts in it inherit it (`inherited_from`): a stock one venue forgot
   to label stays a stock; ambiguous evidence: AMBIGUOUS; crypto evidence: CRYPTO.
3. No contract evidence: CRYPTO when the ticker is on the repository's pre-existing known-crypto list
   (`KNOWN_CRYPTO`, unchanged in this phase); AMBIGUOUS when another **priced** exposure of the ticker is tradfi or
   ambiguous (`UNLABELED_UNDER_TRADFI_COLLISION`: a ticker that names a stock somewhere needs positive crypto
   evidence); otherwise CRYPTO by default, as before. (Retired in Phase 3: such an exposure is now `UNVERIFIED`, see
   [phase3-identity-coverage.md](phase3-identity-coverage.md).)

Tradfi evidence never crosses from one exposure to another; an unpriced contract never counts.

### 4. Admission and the coin record

CRYPTO exposures are admitted. Unpriced contracts without tradfi or ambiguous evidence ride along with an admitted
exposure, as they always did. The coin record is then built from the admitted contracts with the **unchanged**
legacy steps (one market per venue, the price check against the most traded market, reference price, volumes). A
ticker with nothing admitted keeps its legacy record of all its contracts with `tradfi=True`, so every engine
excludes it as before. For a ticker without tradfi evidence anywhere every contract is admitted, so its record is
exactly the legacy one (proven on random market lists in `tests/test_v8_identity.py`).

No ticker is named in the classifier (a test checks it). There is no manual override table; the only lists used
are the repository's existing tradfi and known-crypto lists, unchanged.

### Decisions made (for review)

* **Known-crypto list as positive evidence.** An unlabeled exposure of a ticker that also names a real-world asset
  is admitted only with positive crypto evidence: Extended's `Crypto` category or the existing known-crypto list.
  This admits QNT, PURR and BB and keeps XIAOMI out (its stock is quoted in HKD on Extended and USD elsewhere, so the
  price split alone would have let the USD side in).
* **Unpriced contracts never reclassify a priced exposure**, as specified, even under a ticker that is not a known
  crypto coin. No live market is affected today (the only unpriced active contracts are edgeX's, which carry no
  metadata).
* **Unrecognised Extended categories are ambiguous, not tradfi.** Same exclusion as before; honest reason.
* **Aster `COIN` is not evidence**: all ten live stock collisions carried it.

## Missing liquidity is not zero liquidity

See [data-health.md](data-health.md#missing-volume-is-not-zero-volume-phase-2). One shared evaluation
(`v8/liquidity.py`): KNOWN (an observed 0 included), MISSING, NOT_ON_TRADE_DEX. MISSING never passes the $1M gate;
its reason is `DEX_VOLUME_MISSING` (`INSUFFICIENT_DATA`), not a fabricated low volume. Stored and published values
keep `null` for missing; sorting uses 0 internally only; cost and slippage models are unchanged.

| Use | Class | Phase 2 |
|---|---|---|
| radar stage 2 and extras, radar backtest pool and study, quant universe, picks universe, research coin selection (`tools/fetch_history.py`) | eligibility | shared gate `liquid_enough()`: KNOWN and at least $1M |
| ranking by liquidity (same places, picks day-trade candidates) | sorting | `liq_rank_value()`: 0 for missing, internal only |
| radar table volume, radar pick `best_vol` / `trade_vol`, picks `liq`, paper-trade feature `liq` | stored / presentation | `null` when missing (shown as "-"), 0 only for an observed 0 |
| conviction liquidity tier | scoring | unchanged (`None` was already "unknown"; only $1M+ coins reach it) |
| `scanner.slippage`, `quant.slip_of`, `tools/research/qdata.py`, learning tag "thin" | cost model / learning | unchanged: no known volume pays the highest tier |
| picks liquidity check text | scoring | unchanged (only gated coins reach it) |

## Proving the behaviour change: differential parity

`tools/v8/delta_parity.py` with the manifest `tests/fixtures/v8/phase2_expected_deltas.json` (CI, every run):

1. the base (main 15a3794) reproduces its golden digests on the fixture;
2. the base fed its **own** dumped universe reproduces them too (injection is faithful);
3. this branch reproduces its own golden digests;
4. the universe delta base -> branch (every coin field, venue set, order, DEX status count, note) equals the
   manifest exactly;
5. the counterfactual - the base's code fed this branch's universe - equals this branch's outputs except for the
   manifest's code deltas.

So every output difference is either an approved universe delta, an approved code delta, or the unchanged legacy
engines responding to the approved universe delta. The manifest lists 13 universe deltas (QNT, PURR, BB admitted;
PURR's name; FAKE13's unpriced RWA market; observed zero volumes of ZEROV and KIOXIA), 2 DEX status counts, 4 notes
and 1 code delta (LONLY's missing volume published as null). Anything else fails.

## Fixture

The parity fixture (`tools/v8/legacy_parity.py`) now reproduces the live shapes: QNT (crypto on Variational, Aster,
Lighter; RWA on Extended at about half the price; an inactive dYdX market), PURR (crypto on Hyperliquid; RWA on
Extended), BB (crypto on Hyperliquid, Aster, Variational `BBIT`; a stock on Lighter, unlabeled, and Extended), the
stock collisions ASTS, ONDS (name evidence), KORU, KIOXIA and XIAOMI (currency split), an Extended market with an
unrecognised category (SECT), an unpriced RWA market next to a priced coin (FAKE13), an Extended-only crypto coin
(EXTONLY) and a cross-venue x1000 alias (Lighter `1000FAKE06`). `tests/test_v8_identity.py` adds the collision
matrix A-K and the stock-leakage gate on the ten live stock collisions with their recorded prices and volumes.
