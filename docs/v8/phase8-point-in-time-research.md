# v8 Phase 8: point-in-time historical universe and research correctness

> Historical research may use only information that was actually knowable at that historical time.

Phase 8 makes the system *remember what it saw*, scan by scan, in an append-only history, and gives research a
point-in-time view of that history with time-varying costs. It changes no live engine, no identity (`v8.identity/4`,
config hash `96a10dc2...`), no discovery (`v8.discovery/1`), no strategy, gate, stop, target, sizing or Top-N, and it
does not overwrite `quant_research.json` or `picks_research.json`. Versions: `v8.audit/6`, `v8-phase8.0`,
`v8.history/1`, `v8.pit/1`, `v8.pit-cost/1`, `v8.pit-research/1`, `v8.shadow-ledger/1`.

## Stage A: what history existed before Phase 8

| Source | What it is | Classification |
|---|---|---|
| `market-data` branch (`universe.json`, `h1/`, `h4/`, `fund_mexc/`, `fund_hl/`) | One orphan commit (`df20b57`, 2026-10-04 08:48Z), replaced by every Market data run (`data.yml` force-pushes). `universe.json` is the coin list *at fetch time*: today's identity and today's trade-DEX volume, applied to three years of candles | Candles and funding settlements: contemporaneous exchange records. Coin list and `trade_vol`: **current-only** (survivorship: coins delisted before the fetch are absent; every past trade pays today's slippage tier) |
| Legacy funding fill (`qdata.Panel._funding`) | 0.01% per 8 hours before a coin's first settlement and for coins without a series | **Assumed** (never observed) |
| `pk_trades.COST` | 0.19% per trade (fees and 0.05% slippage both ways), no funding | **Assumed** constant |
| Production audit snapshots (`v8-audit-<run>-<attempt>` Actions artifacts, 14-day retention) | The whole `v8.audit` snapshot of each scan: every contract, asset identity, venue health, volumes, with scan id, commit, identity version and config hash; 34 from 2026-10-06 19:12Z on when Stage A ran (the oldest expire around 2026-10-20) | **Contemporaneous, immutable** (an artifact cannot be edited): the only allowed backfill source |
| `data/v8/audit_latest.json` on the site | The latest snapshot only, overwritten every scan | Current-only |
| `data/v8/first_seen.json` | contract -> [first seen, last seen], carried from the published site to the next scan, pruned 400 days after last seen; resets to "now" if the site cannot be read | Mutable carried state: **not** a listing record (first seen by v8, which started in October 2026, and resettable) |
| `data/v8/identity_state.json` | asset -> [state, since], carried the same way | Mutable carried state |
| `journal-data`, `research` branches | One commit each, force-replaced every scan / Research run | Current-only |
| `journal-v4-archive`, `smart-data`, `results`, `data-fetch`, `data-extra` | One-off archives and code branches | Not a universe record |
| Listing / delisting records | None existed: no venue listing date was ever stored | **Missing** |
| DEX volume history | None: only the volume of the latest scan | **Missing** before the first archived snapshot |

Conclusion: before Phase 8 nothing recorded which perpetuals existed, what they were or how liquid they were at any
past time, except the 14-day audit artifacts. Nothing is reconstructed for earlier times: they stay unknown.

## The history (`v8/history.py`, `v8.history/1`)

The Scan workflow's snapshot step, after the audit snapshot is assembled, appends one observation per scan to the
**`v8-history` branch** (separate from the code). One gzip JSON file per observation,
`obs/<YYYY>/<MM>/<DD>/<seq:08d>-<scan_id>.json.gz` (the UTC day it was appended), written with git plumbing in a
temporary index on top of the fetched branch and pushed **without `--force`**: a non-fast-forward is rejected by git,
and the capture refetches and retries (3 attempts). A file is never modified or deleted.

What one observation holds - only what research needs, nothing that is not observed:

| Part | Contents |
|---|---|
| header | `scan_id`, `observed_at` (the scan's time), `git_sha` (the exact commit that ran), `versions` (audit schema and version, identity version and config hash, discovery and liquidity versions, engine config hashes), `venues` (each venue's market-list state: `OK`, `VENUE_UNAVAILABLE`, `NO_MARKETS`, `ZERO_ACTIVE_MARKETS`), `coverage` (venues expected / ok / failed, fallback universe), `trade_dexes`, `source` (`SCAN`, or `ARCHIVED_SCAN_ARTIFACT` with the artifact's id, name, run, creation time, digest and the sha256 of the zip and of the snapshot file) |
| `contracts` | every perpetual: `[id, venue, asset, active, state, exposure, exp_state]` (the venue's listing flag, the registry state - SELECTED, NOT_TRADING, DELISTED, ... - and the price-coherent exposure) |
| `assets` | `[asset, universe, identity, decision, reason, authority]` as decided at that scan |
| `liquidity` | about every 4 hours (`LIQUIDITY_EVERY_S`) and in every backfilled observation: `[asset, state, trade_vol]` - the largest 24h volume of the asset's selected markets on the trade DEXs (`KNOWN`, an observed 0 included), `MISSING` (none reported) or `NOT_ON_TRADE_DEX` (v8.liquidity semantics); `null` in the other observations (payload intentionally omitted; never zero) |
| `liquidity_content_hash` | on **every** observation: sha256 of the deterministic full liquidity table from `state_from_snapshot()`, including every asset, liquidity state and trade volume, even when the table is omitted for storage |
| chain | `seq`, `prev_hash` (the previous observation's governed `record_hash`), `content_hash` (header without provenance, full contract and asset state, full liquidity digest), `record_hash` (every persisted field except itself), `appended_at`, `stored_bytes_before`, `state_mode`, `base` (checkpoint seq and record hash), `last_liquidity` |

**Checkpoints and deltas.** An observation is a `CHECKPOINT` (the full state) or a `DELTA` (the rows that differ from
its base: the newest checkpoint before it, named by seq and hash; `removed` lists rows that disappeared). A checkpoint
is written at genesis, every 24 hours, for every backfilled observation and whenever the end of the chain cannot be
checked. Appending reads at most three observations (the last one, the one before it, the base checkpoint), and the
fetch is depth-1 and blob-less, so a scan's cost does not grow with the history.

**Tombstones.** A contract that a later scan no longer returns is recorded as `removed` in that observation (or is
absent from the next checkpoint) while its venue's state says whether the list loaded; nothing is pruned, ever (unlike
`first_seen.json`, which forgets a market 400 days after it was last seen).

**Serialization** is deterministic (sorted keys, no whitespace, ASCII, gzip with mtime 0). **Integrity:**
`python -m v8.history verify --dir <export>` walks the whole chain and recomputes **every** record hash, including
the final/head observation. It covers provenance, semantic hashes, payloads, sequence, previous hash, checkpoint
and delta metadata, byte accounting, base and last-liquidity references. Every stored liquidity table is also
hashed and checked against `liquidity_content_hash`; `content_hash` is checked against the reconstructed full
contract/asset state and that digest. One governed record hash supplies the self-check, chain link, checkpoint
reference and reported history head. The bounded append check validates the records it reads, including the head.
A changed head liquidity value or artifact provenance fails verification even without a later observation; PIT
history fails closed. Rewriting, removing or reordering observations breaks record, sequence or link checks.

Before Phase 8 merge/production qualification, **a dedicated branch ruleset for `v8-history` is required**: block
deletion and non-fast-forward/force pushes, with no bypass actors unless explicitly approved. Do not copy main's
CI status requirements onto the data branch without independent justification. Repository settings are not
changed by this correction. Hashes detect edits relative to the recorded chain; they are not signatures, and an
actor able to rewrite and rehash the whole branch is why branch protection is also required.

**Duplicates and retries.** A scan id already recorded with identical content is `IDEMPOTENT_REPLAY` (nothing
written); with different header, venue, contract, identity or liquidity authority `CONFLICTING_SCAN_ID` (nothing
written, degraded). Full liquidity participates even when its payload is omitted: $5M -> $100k for the same scan
id is a conflict. Source provenance is outside semantic equality, so a genuinely identical live scan arriving
again from its archived artifact is a replay; provenance remains inside persisted-record integrity.
A retried workflow run is a new
scan id (`gh-<run>-<attempt>`) observed at a new time: a new observation. The Scan workflow's `pages` concurrency
group means one writer at a time; a race is still handled (rejected push, refetch, retry).

**Backfill.** With `--history-backfill`, every unexpired `v8-audit-*` artifact whose scan is not yet in the chain is
downloaded (`gh api`, the run's own token, this repository only) and appended as a checkpoint citing the artifact,
oldest observation first. After the first run every live scan is captured directly, so backfill only fills scans
whose own capture failed (it heals within 14 days). Nothing is backfilled from anything else.

**Failure.** `capture()` never raises. A failure (fetch, push, broken chain) is `HISTORY_CAPTURE_DEGRADED` in the
snapshot's `history` section, in `data_health.audit_problems.history` and as a warning in the Actions run; the
scan's pages are published exactly as before. Research treats the missing time as unknown (staleness, below).

**No secrets.** Observations hold market-list facts, identity and volumes only; the token is used by `gh` and `git`
from the environment and is never written.

### Storage gate (measured)

The table below is the pre-integrity-correction baseline. The corrected format adds two fixed-size SHA-256
digests per observation, retains the 4-hour liquidity-payload cadence, and reruns the measurement in exact-head
Research (`research_history_projection.json`). No full liquidity table is added on intervening scans.

The format is corrected in `v8.history/1` before merge: no production `v8-history` branch existed when the defect
was found. Disposable Research history is regenerated from contemporaneous archived artifacts, not migrated or
accepted by the corrected verifier without the new integrity fields.

`python -m v8.history project <snapshot> --days N --scans-per-day K` writes N days of observations at production scale
(2,421 perpetuals and 1,040 assets from a production snapshot; 0.2% of contract and asset rows changing per scan,
every liquidity value changing each time it is recorded - deliberately pessimistic) into a throwaway bare repository,
one commit per observation, garbage-collects it and measures it:

| Cadence | Bytes per observation (mean) | Per day (git) | 30 days | 1 year | 3 years | Per-scan fetch after 3 years (trees) |
|---|---|---|---|---|---|---|
| 72 scans a day (the cron's nominal maximum) | ~4.2 KB (delta ~3.3 KB, checkpoint/liquidity ~14 KB) | ~356 KB | ~10.7 MB | ~130 MB | ~390 MB | ~4.1 MB (uncompressed) |
| 12 scans a day (well above the ~7 a day observed) | ~7.2 KB | ~96 KB | ~2.9 MB | ~35 MB | ~105 MB | ~0.7 MB |

The audit snapshot itself is ~375-590 KB gzip; keeping it every scan would be ~1 GB a month at 72 a day. The
history is about 1-2% of that, grows linearly with the number of scans (no rewrite, no pruning, bounded per
observation), and stays on its own branch. Network: the Scan workflow (the only frequent run) fetches it depth-1 and
blob-less (the trees plus at most three observations, last column); the CI and Research checkouts use
`fetch-depth: 0`, which downloads every branch, so they download the whole history once per run (the 1-year and
3-year sizes above), as would a plain `git clone`. The gate passes; the Research run repeats the measurement on its
own snapshot (`research_history_projection.json`). If the history ever grows enough to matter for CI, those two
checkouts can fetch `main` only.

## The point-in-time view (`v8/pit.py`, research only)

`History(store)` verifies the chain first; a chain that fails answers nothing (`HISTORY_INTEGRITY_FAILED`): research
fails closed. It then indexes every observation by `observed_at` (a late-appended backfill sits at its own time) and
answers for a time `t` only from observations with `observed_at <= t` at most `MAX_STALENESS_S` (12 hours) old:

* `universe_at(t, min_vol)`: every asset the history had seen by `t` - `KNOWN_ACTIVE` (an active perpetual on a venue
  whose market list loaded), `KNOWN_INACTIVE` (every venue it was seen on loaded and none lists it as active) or
  `UNKNOWN` (stale, before the history, a venue it was seen on unavailable, the fallback universe) - with its identity
  and liquidity then and `research_eligible` (True / False / None). An asset first observed after `t` is absent: a
  future listing never leaks back. `UNKNOWN` is never False or zero.
* `identity_at`, `crypto_identity_at`: the identity recorded then, with its version and config hash. The oldest
  archived snapshots (`v8.audit/1` and `/2`, before Phase 3) carry no identity state: there the identity is unknown,
  so research eligibility is unknown, never "not crypto".
* `liquidity_at`: the latest liquidity observation at or before `t`, at most `LIQUIDITY_MAX_STALENESS_S` (12 hours)
  old, else `LIQUIDITY_HISTORY_UNKNOWN`.
* `intervals(asset)`: `eligible_from` = first observed active (`listing_known` when an earlier observation that covered
  it saw it inactive or absent), `last_observed_active`, `first_observed_inactive`; a venue outage neither closes nor
  opens an interval; a gap longer than the staleness ends it as `UNKNOWN_GAP`; a re-listing opens a new interval.
* `exposure_at(t, contract)`: the contract's asset and exposure as recorded then.
* `window()`, `gaps()`: the supported window and every `PIT_UNIVERSE_GAP`.

The 12-hour bound: production scans have been observed up to ~7.3 hours apart; a longer silence is a gap, not a
continuation. Tests pin both edges.

Health states: `PIT_UNIVERSE_OK` / `PIT_UNIVERSE_GAP`, `LIQUIDITY_HISTORY_OK` / `LIQUIDITY_HISTORY_GAP`,
`FUNDING_HISTORY_OK` / `FUNDING_HISTORY_GAP` (research artifact), `HISTORY_CAPTURE_DEGRADED` (audit snapshot).

## Costs and corrected research (`tools/research/pit_cost.py`, `pit_sim.py`, `pit_research.py`)

* **Slippage** is a `[time, coin]` panel: the scanner's tiers (unchanged: $1M+ a day on the trade DEXs 0.05%,
  $200k-$1M 0.1%, below $200k 0.2%) of the liquidity recorded at that time. The entry pays the slippage known at the
  entry, the exit the slippage known at the exit. Unknown liquidity is `NaN` (`LIQUIDITY_HISTORY_UNKNOWN`), never a
  tier. A new observation or today's volume never changes a past trade's cost (tested).
* **Funding** per hour is `OBSERVED`, `OBSERVED_ZERO`, `NOT_DUE` or `MISSING` (before the first or after the last
  settlement, inside a gap longer than 1.5 cycles, no series). Only observed settlements count; `MISSING` is never
  filled. `ASSUMED_SCENARIO` (0.01% per 8 hours) exists only in a scenario.
* **Fees**: one governed schedule (`v8.fees/1`: taker 0.045%, maker 0.015%) with its limitation stated - one schedule
  for every venue and date, no tiers or discounts.
* **Universe**: the same strategies, with the strategy's own eligibility AND point-in-time eligibility when the
  signal's bar closes (active, verified crypto identity, a KNOWN trade-DEX volume of at least $1M - the live quant and
  picks gate). A time whose eligible assets are not all in the candle panel (a coin delisted before the market data
  was fetched) is `PIT_UNIVERSE_CANDLES_MISSING`: nothing traded then is authoritative.
* **Trades** follow the unchanged qsim / pk_trades rules (exits depend on prices only); costs are recomputed per
  trade. With full coverage and the same inputs the re-costing reproduces qsim's legacy result exactly (tested).
* **Qualification** per trade: `universe_ok`, `identity_ok`, `liquidity_ok`, `funding_ok`, `cost_ok`,
  `fully_qualified`, each failure with its reason. Partial rows are kept and counted; only fully qualified, closed
  trades enter the authoritative aggregate. Zero qualified trades is a valid answer.
* **Legacy** results (qexport's one-year run of TSMOM, TREND_EMA and XSMOM; picks_export's swing bands and pk_day's day
  trades) are shown next to the corrected ones, labelled `LEGACY_SURVIVORSHIP_UNQUALIFIED`, with why each legacy trade
  does not qualify. A scenario (unknown liquidity at the worst tier, missing funding assumed) is labelled
  `SCENARIO / NOT AUTHORITY`.
* **The qualified window** (`qualified_window`): history start and end, market-data start and end, their overlap in
  hours and days, observations, and qualified trades.

`research_pit.json` is a separate artifact of the Research run. Nothing is promoted.

**What it says today.** The market data ends on 2026-10-04 and the history begins with the oldest archived scan
(2026-10-06): no overlap, so **zero trades qualify**. Every legacy result stays `LEGACY_SURVIVORSHIP_UNQUALIFIED`.
The window opens when a Market data refresh covers time the history has recorded; it is complete only where every
asset eligible at that time has candles (today's fetch takes today's coins; fetching candles for every asset in the
point-in-time universe, delisted ones included, is a later step).

## Shadow experiment ledger (`v8/shadow_ledger.py`, `research/shadow-ledger/`)

Pre-registration with no authority. Canonical JSON records, one file each (`<seq>-<kind>-<id>.json`), chained by
`prev_hash`: a `GENESIS`, `REGISTRATION`s (experiment id, registration time and commit, name, parameters and their
hash, code files and hash, data cutoff, evaluation window - forward from the registration only -, universe-history
and cost-model versions, hypothesis, primary and secondary metrics, pass and fail rules, status `REGISTERED`,
authority `NONE`, and `multiple_testing`: family, variants tried before registration, selection, corrections planned
- DSR, PBO, SPA, FDR) and `STATUS` changes. Changed parameters need a new id; there is no FINAL, LIVE or PROMOTED
status. `tools/v8/ledger_guard.py` (CI) fails if any ledger file was modified, deleted or renamed, or the ledger does
not validate. Phase 8 commits the genesis only: an experiment is registered from the commit its code is on, which is
after this phase merges.

## Reproducing a research result

`research_pit.json` carries its provenance: the research code hash (and file list), the git head, the market-data
commit and a sha256 over every file of the export, the history head hash and verification, the versions of the
point-in-time view, cost model and fee schedule, the staleness bounds, the cutoff, and the command:

```
git archive <market-data commit> | tar -x -C md
git archive <v8-history commit> | tar -x -C hist
python tools/research/pit_research.py --md md --history hist --cutoff <unix> --out research_pit.json
```

With `--cutoff`, no observation, candle or funding settlement after it is used (tested).

## What runs where

| Where | What |
|---|---|
| Scan (`scan.yml`) | `python -m v8.snapshot ... --history-branch v8-history --history-backfill`; `tests.test_v8_phase8.ScanGateInvariants` in the core tests |
| CI (`ci.yml`) | `tests.test_v8_phase8` (stdlib parts), the ledger guard, legacy parity against `legacy_parity_golden_phase8.json` (identical digests to Phase 7), delta parity against `phase8_expected_deltas.json` (base `1609e2c`, no delta); the research-checks job runs `tests.test_v8_phase8` again with numpy, numba and pandas (cost, funding, qualification, end-to-end with qsim parity) |
| Research (`research.yml`) | verifies the production history when it exists; a dry run of the writer into a throwaway repository (this run plus every archived scan artifact; `history_dryrun.tar.gz`); the storage projection; `pit_research.py` on the market data |

## Limitations

* Before the oldest archived scan nothing is known, and nothing is invented: research before 2026-10-06 cannot be
  point-in-time qualified.
* The `v8-history` branch is append-only by construction and verifiable, not protected by a repository rule until the
  owner adds one.
* Liquidity is recorded about every 4 hours, not every scan.
* Candles for delisted coins are not fetched yet, so cross-sections that included them stay unqualified.
* One fee schedule for every venue and date.
