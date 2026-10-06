# Perp DEX Radar

A dashboard that scans every crypto perp listed on the major decentralised perp exchanges with nine strategies,
paper-trades every signal after trading costs next to a random twin, and publishes only the strategies that prove
an edge on live trades:

**Hyperliquid, Variational, Aster, edgeX, Lighter, dYdX, Paradex and Extended.**

Each pick comes with an entry zone, stop-loss, three targets, a conviction score out of 100, the DEXs it trades on
(with symbol, multiplier and 24h volume on each), where Hyperliquid's most profitable traders are positioned, the
4-hour trend, a written technical case, and your position size for the balance and risk you set on the page.
Every signal is paper-traded next to a **random twin** (the same order on another coin at the same moment), and a
strategy is published only once its live trades make money after costs and clearly beat their twins. Nothing long
is published while the market is risk-off or BTC's 4-hour trend is down. A goal tracker shows whether your balance
is on the path to your target and what the journal's own results say about reaching it.

## Dashboard (version 7.2): everything in one look

The front page (`dashboard.html`, served as `index.html`) shows the three versions side by side with smart money
and one accuracy scorecard, and every page has the same tab bar (Dashboard, Coin picks, Quant desk, 15m radar,
Smart money, Analyzer), so each version is one tap away, on a phone too:

- **Market now**: the daily trend (coin picks), the last 3 hours (15-minute radar), Fear & Greed and how Hyperliquid's
  proven traders lean, in one sentence ("Uptrend with a soft patch: swing longs keep the wind; fast 15-minute longs
  wait"), so the versions no longer seem to contradict each other.
- **The three versions**: what each says now (ready picks, open positions, standing aside) and its accuracy.
- **Where the signals line up**: coins that two or more versions point at, with conflicts marked "mixed".
- **Accuracy scorecard**: every version in one unit, **the average result per trade for each $100 risked, after
  fees**, next to the share of winners and the number of trades, tested and live, with a plain verdict:

| Version | Verdict | Tested | Per $100 risked | Winners |
|---|---|---|---|---|
| Coin picks, swing (scores 80+) | Proven | 5,453 trades, Oct 2023 to Oct 2026 | +$29 | 48% |
| Quant desk | Proven | 4,514 trades, Dec 2023 to Oct 2026 | +$9 | 41% |
| 15m radar | Not proven | 2,230 picks, last 30 days | +$1 | 51% |
| Coin picks, day trades (80+) | No edge | 25,046 trades, Oct 2025 to Oct 2026 | −$6 | 35% |

`dashboard.py` builds `data/dashboard.json` from the files the scan has just written (nothing is fetched); if it
fails, the front page stays the coin picks page. Each pick on the coin picks page also carries its own tested
accuracy badge (Proven, Mixed or No edge) for its score band.

## Smart money (version 7.2): tested without hindsight

The smart money page (`smart.html`, from `smart.py`) follows **Hyperliquid's proven traders**: $100k+ made over their
whole account history, at most 15% of the account lost over the last 30 days, a $25k+ account, and a real
directional trader (market makers and high-frequency books are left out); the 200 most profitable that pass. Every
scan reads their open positions (public data), compares them with the last scan, and shows per coin how many are
long and short (one vote each, weighted by size against their own account, so one whale cannot outvote everyone),
what they opened in the last 24 hours, and the trades as they happen. Addresses are shown as a short code.

**How it was tested.** `tools/research/smart_collect.py` (the Smart money research workflow) saved 90 days of trade
fills of 380 traders (950,748 fills), their account and PnL histories and hourly candles of 174 coins. A signal at
time t is entered at the next hourly open and judged 24 hours later after 0.09% costs; "vs market" removes the
average move of all coins over the same hours. Who counts as proven is decided only from what was known at that
moment. The clean test also leaves out every trader who was picked for last month's results (the pool itself would
otherwise carry hindsight) and judges only the last 30 days:

| Method (clean test, next 24 hours) | Side | Signals | Right | vs market | Per $100 risked |
|---|---|---|---|---|---|
| Old method: biggest money among last month's top traders | long | 1,207 | 51% | +0.1% | +$12 |
| Old method | short | 641 | 46% | +0.1% | −$9 |
| What proven traders hold (one vote each) | long | 632 | 49% | -0.1% | +$11 |
| What proven traders hold | short | 493 | 46% | +0.0% | −$11 |
| Every new position of a proven trader | long | 944 | 49% | -0.2% | +$6 |
| Every new position of a proven trader | short | 509 | 56% | +1.2% | +$3 |
| **2+ proven traders opening the same side within 24 h** | long | 108 | 52% | +0.1% | +$16 |
| **2+ proven traders opening the same side within 24 h** | short | 31 | 63% | +2.3% | +$14 |

**What it means.** Following proven traders' longs did no better than the market's own drift, whichever way it
was measured, and the old method (the biggest money among last month's top traders, which the radar used) had no
edge either; the radar's own records agree (its long trades did worse when top traders were 65%+ long). The one
result that stands out: **when 2 or more proven traders open shorts on the same coin within 24 hours**, the coin
went their way 63% of the time and did +2.3% against the market over the next day (31 trades on
11 coins, Sep 05 to Oct 02 2026); on the whole window, where the trader pool has some hindsight, 66% and
+1.9% on 48 trades. That is the signal the page trades on paper (stop 1.5 typical daily moves, at least
1.5%; out after 24 hours), and the coin picks use it as a small nudge (±2). It is marked **Promising**, not Proven:
31 trades is too few. After 40 live paper trades the live record decides on its own: Proven when it makes money
with a t-statistic of 2+, No edge when it does not. Long crowds are shown as information, and paper-traded apart so
their record is visible too. Several short signals at once usually mean one bet on the market falling: size them
together. (A test that let hindsight pick the traders showed 61% right and +$36 per $100 risked; that number is not
used anywhere.)

## Coin picks (version 7)

The coin picks page (`picks.html`) scores **every coin on your DEXs from 0 to 100** for a
swing trade (days to weeks) and a day trade (hours), long or short, and shows the **Top 5 and Top 10** with the
reasons for each coin, an entry, a stop, reference targets and your position size. The 15-minute radar is at
`radar.html`.

Each swing pick shows 18 checks with a tick or a cross and the actual number behind it:

| Group | Checks | Weight |
|---|---|---|
| Chart setup (tested) | Long "coiled bottom": near the 90-day low, daily RSI back above 45, Bollinger squeeze, tight 90-day range, calm daily moves, up over 30 days, higher low, Bitcoin above its 50-day EMA, volume waking up. Short "downtrend bounce": below the 50-day EMA, down over 30 days, bounced (RSI above 50), not on its low, lower high, 4-hour trend down, weaker than Bitcoin, heavier selling volume, below the 30-day VWAP | 100 points |
| Smart money (live) | Proven Hyperliquid traders shorting together (see Smart money); Gate.io open interest over 7 days (leverage piling in), liquidations over 3 days (longs flushed out) and top traders' long/short ratio; funding on your DEXs | up to ±10 points together with the next two rows |
| Fundamentals (live, CoinGecko) | Supply unlocks (30-day growth of the circulating supply), volume against market cap, market cap, distance from the all-time high | |
| Liquidity | Daily volume on your DEXs | |

The extra checks follow what the history showed where it exists (futures statistics since April 2026, a year
of CoinGecko and funding data): longs did worse when open interest jumped 5%+ in a week while the price rose
(+0.09R per trade against +0.39R) and when unlocks added 2%+ supply in a month (-0.13R against +0.03R); the same
unlocks helped shorts, and shorts did worse when funding was above 0.01% per 8 hours (-0.05R against +0.18R).
Smart money comes from the proven-trader engine (`smart.py`): its short signal tested promising but not yet proven,
so it only nudges the score (±2).

**How good is it?** Tested on every coin with $5M+ a day, every day from late 2023 to October 2026, trading the
plan on the card (enter at the next daily open, stop 2 daily ATRs away, trail 3 ATRs behind the best price, out
after 30 days at the latest, after fees and slippage):

| Score | Longs per trade | Longs winners | Shorts per trade | Shorts winners |
|---|---|---|---|---|
| 90 to 100 | +4.4% | 55% | +5.1% | 53% |
| 80 to 89 | +2.8% | 46% | +2.5% | 47% |
| 70 to 79 | +2.3% | 41% | +2.6% | 50% |
| 60 to 69 | -0.3% | 36% | +2.0% | 45% |
| every coin, every day | -1.6% | 34% | +0.7% | 42% |

Scores of 80+ made money in each of 2024, 2025 and 2026 on both sides. Longs scoring 80+ had about the same
chance of a +50% month as any coin (14% vs 15%) and half the chance of a 30% fall (16% vs 29%). Taking every
90+ pick, long and short, with up to 5 open at once and 2% risk each turned $500 into about $1,190 from January
2024 to September 2026 (worst drop 21%); with 3% risk about $1,700 (worst drop 30%).

What did **not** work: buying a coin only because it is near its low (it lost money unless the turn had started);
picking the 2x months in advance (WLD in May 2026 and NIL in April 2026 never scored above 65 before their runs:
those moves started from coins that were still falling, and the same picture usually kept falling); and day
trades: on hourly candles every selection rule lost money after fees (the best about -0.06R per trade), so the day
list is shown with that warning. The live swing scores match the research code exactly
(`tools/research/parity_picks.py`), and every 80+ swing pick and 85+ day pick is paper-traded on the page.

## Coin analyzer (version 7.3): the call comes only from tested signals

**The analyzer** (`analyze.html`, linked from every page, every pick, every quant desk position and every smart-money
coin) takes any coin you type and answers one question: is there a trade on it that has made money in our tests,
and exactly how is that trade run?

**The call.** LONG or SHORT only when one of these is live on the coin. Otherwise it is WAIT, with what would make it
a trade:

| Signal | Record after fees | Size | Exits, as tested |
|---|---|---|---|
| Coin picks swing score of 80+ | Proven: +$29 per $100 risked over 5,453 trades, Oct 2023 to Oct 2026 (the page shows the record of the coin's own score band) | Your risk (half when its band's record is mixed) | In at the daily open, stop 2 daily ATR (5% to 25%), trailing stop 3 ATR behind the best price, out after 30 days |
| A quant desk position | Proven: +$9 per $100 risked over 4,514 trades, Dec 2023 to Oct 2026 (the page shows the strategy's own record) | Your risk | The desk's own stop, trailing stop and time limit |
| 2+ proven Hyperliquid traders opening shorts on the coin within 24 hours | Promising: +$14 per $100 risked over 31 trades in a 30-day test without hindsight | Half your risk, until 40 live trades decide | Stop 1.5 typical daily moves (at least 1.5%), out 24 hours after the signal |

- **The plan is the tested trade.** You join each trade as it stands: the same stop level, the same trailing stop and
  the same time limit, so the trade on the page is the one its record counts; the stop distance and the size are
  worked out from the current price. There are no profit targets, because the tested exits let the winners run and
  the winners pay for the losers. A trade already stopped out, or with most of its window gone, is not offered.
- **Conflicts.** Proven signals on both sides mean WAIT. When several agree, the plan follows the one with the
  strongest record. A weaker signal against a proven one is shown but does not change the call (on the first live
  data, the quant desk was long BTC, ETH and XRP while proven traders were shorting them: the call stays long).
- **What decides the call** is a table on the page: every tested signal on the coin with its state and record, and
  the chart read marked as context. Next to the plan: the signal's win rate and the losing run that is normal for it
  ("runs of about 6 losses in a row are normal over 20 trades" for 41% winners), so a losing streak is no surprise.
- "Tested calls now" under the search box lists the coins with a call right now, one tap each.

**The chart read is context, and two tests decided that.** The read on four timeframes (trend, swing structure,
support and resistance zones from swing points, volume profile and last week's range, RSI, MACD, divergences,
squeezes, volume, funding, open interest and long/short ratios) stays on the page for where the price sits and
which levels matter.

On its own (`tools/research/analyzer_backtest.js`: a year of hourly candles for 118 coins, each plan traded as the
page described it, after 0.12% round-trip costs) it was about break-even before costs:

| Chart | Trades | Before costs | After costs | Winners |
|---|---|---|---|---|
| 1 hour | 29,039 | +0.04% per trade | -0.08% per trade (-0.04R) | 42% |
| 4 hours | 8,400 | +0.08% per trade | -0.04% per trade (-0.02R) | 42% |

As a confirmation of the tested swing signals (`tools/research/analyzer_gate.py`): every swing signal of 80+ of the
last three years, traded with the tested swing plan and split by what the analyzer read on the 4-hour and daily
charts at that day's close (it saw only those candles, without the score, sentiment or market mood):

| Swing signals of 80+, Oct 2023 to Oct 2026 | Trades | Per $100 risked |
|---|---|---|
| All | 5,453 | +$29 |
| The 4-hour read agreed | 1,150 | +$27 |
| The 4-hour read disagreed | 1,363 | +$38 |
| The daily read agreed | 1,381 | +$18 |
| The daily read disagreed | 1,157 | +$45 |
| Shorts, the 4-hour read agreed | 446 | -$1 |
| Shorts, the 4-hour read disagreed | 874 | +$27 |

Waiting for the chart to agree would have made the results worse, not better. Taking only the trades where it
disagreed is no rule either: for longs that group made nothing in the first half of the period and all of its gain
in the second. So the read neither confirms nor blocks a call. More indicators would not change this; the read
already uses the usual ones.

## Free sentiment (version 7.1)

Each scan adds a 0-100 sentiment score per coin from free sources only (X/Twitter has no free
access in 2026, and scraping it is against its rules). Crypto crowds lean bullish on almost everything (in a live
run 69% of coins looked bullish on the raw numbers), so each source is ranked against the other coins of the same
scan and 50 means a typical coin today. Small samples are pulled toward neutral, and a coin needs two sources for a
score:

| Source | What it gives | Weight in the score |
|---|---|---|
| Stocktwits (public streams) | Bullish and bearish tags on the latest posts, posts a day, watchers | 35 |
| Hyperliquid top traders | Share of their money that is long | 25 |
| CoinGecko | Community votes (and trending searches, shown next to it) | 20 |
| News (CoinDesk, Cointelegraph, The Block, CryptoSlate, Bitcoinist) | Headlines naming the coin in the last 3 days and their tone | 20 |
| Reddit and 4chan (ApeWisdom) | Mention counts and their change, shown next to the score | - |
| Fear & Greed (alternative.me) | The whole market's mood | - |

There is no free history to test sentiment on, so it is shown next to the tested score and moves the analyzer's
chart read by 4 points at most; it never changes the call. Each scan saves a daily snapshot per coin (`sent_hist` in the picks journal), so it can be
tested once a few months of history exist.

**Optional: a free CoinGecko key.** Without a key the scan uses CoinGecko's public API, which is slower and limited.
A free Demo key makes it faster and more reliable:

1. Create a free account at [coingecko.com/en/api](https://www.coingecko.com/en/api/pricing) and choose the
   **Demo** plan, then copy your API key from the developer dashboard.
2. In your repository: **Settings > Secrets and variables > Actions > New repository secret**. Name it
   `COINGECKO_API_KEY`, paste the key, **Add secret**.
3. The next scan uses it: the market card on the front page then says "(your CoinGecko key)". Never paste the
   key into a chat or a file in the repository.

**Optional: a free Gemini key for AI desk notes.** With a Gemini key from [Google AI Studio](https://aistudio.google.com)
(free tier) saved as a repository secret named `GEMINI_API_KEY` (same place as the CoinGecko key), each scan:

- writes a short desk note on each of the top 5 swing picks (Gemini 3.8 Flash, falling back to 3.5 Flash-Lite),
  shown on the pick cards and in the analyzer. A note is rewritten only when its pick changes side, moves 5+ points
  or is 12 hours old, with at most 3 requests a scan. A note that comes back cut off (without its closing line) is
  never shown; the other model is asked, or the next scan tries again. When a note quotes the tested record, it names
  the chart-score band the record is for, because the record does not cover the live extra points;
- rates the tone of new news headlines in one batched request at most every 3 hours (instead of the word list).

That keeps it to a few dozen requests a day. Google does not publish fixed free-tier limits (AI Studio shows yours);
when a limit is reached the scan keeps the last notes, uses the word list for headlines and tries again next scan.
The note in the analyzer for any coin and timeframe uses a key you save in your browser instead (Gemini or Claude),
because a page cannot read repository secrets.

## Quant desk (version 6): long and short, tested on three years

`quant.html` is a second dashboard for slower trades that go **long or short**. 24 strategies were built and tested
on a year of hourly candles and three years of 4-hour candles from the coins that trade on your DEXs, after fees,
slippage and funding, each trade next to a random twin. Three passed and run live on paper every scan:

| Strategy | Bars | Last year, R per trade (trades) | 3 years, R per trade (trades) | vs random | Winners | Profit factor |
|---|---|---|---|---|---|---|
| Daily trend rider | 1d | +0.10R (490) | +0.06R (1,181) | +0.10R | 41% | 1.16 |
| 4-hour trend crossover | 4h | +0.13R (690) | +0.09R (2,424) | +0.06R | 38% | 1.20 |
| Momentum rotation | 1d | +0.10R (364) | +0.14R (909) | +0.07R | 48% | 1.35 |

Together: +0.09R per trade over 4,514 trades in three years, +0.07R ± 0.03 better than
random entries, a Sharpe ratio of about 1.5. The other 21 lost money after costs, worked in only part of the
year, or were no better than random entries; the page lists every one with its numbers and the reason. Short-term
(1-hour) ideas all lost to fees; the edge is in multi-day trends and momentum, both directions.

**What it means for an account.** Replaying the three strategies on the real three years from $500 with up to 60
positions at once: 0.5% risk per trade ended at $2,043 (worst drop 30%), 1% at $3,264 (worst drop
54%), and 2% at only $688 (worst drop 89%): too much risk per trade destroys growth. The growth
planner bootstraps those trades into thousands of two-year paths from $500:

| Risk per trade | Typical result | Reach $10K | Reach $1M | Drop 50% on the way | Lose 90% |
|---|---|---|---|---|---|
| 0.5% | $1,751 | 1.5% | 0.0% | 11% | 0.0% |
| 0.75% | $2,837 | 13% | 0.0% | 45% | <0.1% |
| 1% | $4,225 | 28% | <0.1% | 78% | 0.2% |
| 1.5% | $7,398 | 44% | 1.4% | 99% | 3.2% |
| 2% | $9,412 | 49% | 5.2% | 100% | 11% |
| 3% | $3,779 | 42% | 11% | 100% | 33% |
| 5% | $50 | 16% | 6.7% | 100% | 76% |

Growth peaks near 1.5% per trade (the Kelly level); half of it keeps a 90% loss very unlikely. These
odds assume the next two years look like the last three; live results usually fall short, and the page has a
switch for "half as good". Paper trading only, not financial advice.

How it works: `quant.py` runs after `scanner.py` in every scan. It fetches 4-hour candles for every coin with $1M+
a day on your DEXs, builds daily bars from them, computes the signals on closed bars only, and paper-trades each one
from the next hour's open with its stop, trailing stop and time limit, after fees, slippage and MEXC funding. Its
record lives in `data/quant_journal.json` on the site. The research code is in `tools/research/` (numpy, pandas,
numba) and the market data comes from the **Market data** workflow (`tools/fetch_history.py`, saved on the
`market-data` branch). The live code matches the research engine signal for signal and trade for trade on the same
candles.

## What changed in version 5

An audit of version 4 found that its signals did no better than random entries once costs were counted: the
Studio's own tests matched a random-walk market almost exactly, and trading costs took 10-30% of the risk on every
trade. Version 5 changes how strategies are judged rather than adding more of them:

- **Closed candles only.** Live scans read the same closed candles as the backtest. The live price only decides
  the kind of order (in the zone, a pullback, a buy-stop) and the paper fill, so a spike inside an unfinished
  candle no longer counts as a breakout.
- **Market gate.** No long is published in a risk-off market or while BTC's 4-hour trend is down (in the
  version 4 journal those trades averaged -0.20R against -0.04R for the rest). Gated signals are still paper-traded
  with a flag, so the Strategies tab shows what the gate kept out.
- **Cheaper trades.** Stops are at least 1.5% away and coins need $1M+ a day on a DEX you trade (`trade_dexes` in
  `CFG`: Hyperliquid, Lighter, Aster and Variational). That roughly halves the share of each trade lost to costs.
- **Random twins and honest statistics.** A strategy passes only on live trades: 40+ of them on 10+ days, making
  money after costs and beating their twins before costs, both by two standard errors, with each day counted as one
  block of evidence because trades of the same hours move together. Backtest trades never decide a pass.
- **Only proven strategies are published.** Lesson points, automatic target and stop tuning and strategy discovery
  are switched off (`lesson_points`, `auto_tune`, `discovery` in `CFG`) until something has an edge. Expect few or
  no picks for the first weeks: that is the scanner refusing to publish coin flips.
- **Checks.** `tests/` holds unit tests and a full scan on a fake exchange (`python -m unittest discover -s tests`);
  `tools/no_edge_check.py` runs the strategies on a market where profit is impossible and fails if any change lets
  the backtest see the future. Pushing to a branch named `v5...` runs `.github/workflows/research.yml`, which tests
  the new code and the code on `main` side by side on live exchange data and saves the results to the `research`
  branch. Each scan also saves `latest.json` and `journal.csv` to the `journal-data` branch.

It runs for free on GitHub: GitHub Actions runs `scanner.py` every hour and publishes the result to GitHub Pages.
Nothing runs on your computer.

## Files

| File | What it does |
| --- | --- |
| `scanner.py` | Pulls the data, runs the strategies, the journal, the backtest and strategy discovery, writes the site (Python standard library only) |
| `index.html` | The dashboard page |
| `quant.py` | The quant desk: long and short trend and momentum strategies, paper-traded every scan (standard library only) |
| `quant.html` | The quant desk page: signals with your position size, the strategies, the growth planner, the live record |
| `quant_research.json` | One-year and three-year test results of all 24 strategies, used by `quant.html` |
| `picks.py` | The coin picks: every coin scored for swing and day trades with its reasons, plans and a paper record (standard library only) |
| `picks.html` | The coin picks page (`picks.html`; the radar moves to `radar.html`) |
| `dashboard.py` | Builds the dashboard data (`data/dashboard.json`) from the scan's files and publishes the front page |
| `dashboard.html` | The dashboard, published as the front page (`index.html`) |
| `smart.py` | Smart money: Hyperliquid's proven traders, their entries and positions per coin, signals and a paper record |
| `smart.html` | The smart money page: accuracy, signals, fresh moves, paper trades, every coin they hold |
| `smart_research.json` | The smart-money test results shown on the page (`tools/research/smart_backtest.py`) |
| `picks_research.json` | The test results behind the scores, shown on the picks page (`tools/research/picks_export.py`) |
| `picks_seed.json` | The last 45 days of each coin's circulating supply, so the unlock check works from the first run |
| `analyze.html` | The coin analyzer page: the call from tested signals, the tested plan and size, the chart read on four timeframes, sentiment |
| `analyze.js` | The analyzer engine: the call (`decide`), the chart read (`analyze`) and the candle loaders (also runs in node for the tests and the research scripts) |
| `.github/workflows/scan.yml` | The schedule and the publish step (runs `scanner.py`, `smart.py`, `quant.py`, `picks.py`, then `dashboard.py`, and publishes the analyzer) |
| `.github/workflows/smart_research.yml` | Collects 90 days of Hyperliquid trader history for the smart-money test to the `smart-data` branch |
| `.github/workflows/backtest.yml` | Strategy tests started from the Studio tab |
| `.github/workflows/research.yml` | Tests a `v5...` / `v6...` / `v7...` / `v8/phase-...` branch on live exchange data (nothing published) |
| `.github/workflows/ci.yml` | Blocking checks on every pull request and push to main: all tests, legacy parity, simulator and no-edge checks |
| `v8/` | v8 Phase 1 audit (observes, never changes a decision): every DEX contract, why each coin was or was not shown by each engine, data health and provenance, published as `data/v8/audit_latest.json`. See `docs/v8/` |
| `tools/v8/legacy_parity.py` | Runs the whole pipeline offline on a fixed fake market and proves the legacy outputs are unchanged |
| `.github/workflows/data.yml` | Downloads a year of 1h and three years of 4h candles, funding, futures statistics and CoinGecko fundamentals to the `market-data` branch |
| `tests/` | Unit tests and full runs on a fake exchange |
| `tools/no_edge_check.py` | The strategies on a random market: shows costs and catches look-ahead bugs |
| `tools/fetch_history.py` | The market data download used by `data.yml` |
| `tools/fetch_extra.py` | Futures statistics (Gate.io) and fundamentals (CoinGecko) history for the coin-score research |
| `tools/research/` | The research engine behind `quant_research.json` and `picks_research.json` (needs numpy, pandas, numba), the smart-money test behind `smart_research.json` (`smart_collect.py`, `smart_backtest.py`: standard library), and the test of the chart read as a confirmation (`analyzer_gate.py` with `analyzer_gate.js`) |
| `strategies.json` | Your own strategies (written by the Studio tab; created when you add the first one) |

## Setup (about 10 minutes, works from a phone browser)

1. Sign in to [github.com](https://github.com) (a free account is enough).
2. Create a repository: **+ > New repository**, name it `perp-dex-radar`, set it to **Public**, tick
   **Add a README file**, then **Create repository**. GitHub Pages on a free account needs a public repository.
   (Already running an earlier version? Use the same repository and just replace the files.)
3. Upload the files: **Add file > Upload files**, pick `scanner.py`, `index.html` and `README.md`, then
   **Commit changes**.
4. Add the workflow: **Add file > Create new file**. In the name box type exactly
   `.github/workflows/scan.yml` (the slashes create the folders), paste the contents of `scan.yml`, then
   **Commit changes**. (Updating? Open the existing file, click the pencil, replace everything, commit.)
5. Turn on Pages: **Settings > Pages**, and under **Build and deployment > Source** choose **GitHub Actions**.
6. Run the first scan: **Actions** tab > **Scan** > **Run workflow** > **Run workflow**. The first run takes about
   10 to 15 minutes because it downloads 30 days of candles and backtests every strategy on them (see below). If
   GitHub asks you to enable workflows first, confirm it.
7. Open your dashboard at `https://YOUR-USERNAME.github.io/perp-dex-radar/` and add it to your home screen.
8. On the page's **Picks** tab, tap **Your plan** and enter your balance, risk per trade, open-risk limit and
   maximum leverage. Open the **Goal** tab to set your target. Both are saved in your browser only.

The page is split into tabs at the top (Picks, Goal, Strategies, Lessons, Journal, Smart money, All coins,
Guide), so each part is one tap away. On the Picks tab, tap a coin in the list to open its full card, or switch to
**All** to see every card in a row. Links such as `.../#goal` open a tab directly.

After that it updates by itself every hour at minute 7 (UTC). The page checks for a new scan every 3 minutes.
Once a day one run takes a few minutes longer: that is strategy discovery.

**Upgrading from version 4?** Replace `scanner.py`, `index.html`, `README.md` and `.github/workflows/scan.yml`,
and add `.github/workflows/research.yml`, `tests/` and `tools/`. The first version-5 run starts a new journal by
itself (version 4 results were measured under other rules, so they can't be mixed with the new ones) and backtests
the last 30 days.

## The strategies

| Code | Strategy | Idea |
| --- | --- | --- |
| BRK | Range breakout retest | 15m close above the 8-hour range high on strong volume; buy the retest |
| SQZ | Squeeze break | Tightest Bollinger width of the day at the top of a rising range; buy the break |
| PB | EMA21 trend pullback | Bullish EMA stack; buy the dip into EMA9-EMA21 with RSI 42-66 |
| MOM | Trend continuation | ADX 22+, RSI 58-80 near the 24h high; buy dips to EMA9 |
| VWAP | VWAP reclaim | Dipped under the 24h VWAP and closed back above it on volume |
| MR | Oversold bounce in an uptrend | 1h trend up, 15m RSI 32 or lower near a swing low, candle turning up |
| SMF | Smart-money follow | 70%+ of Hyperliquid's top traders' money in the coin is long; buy near EMA21 |
| HI24 | 24-hour high breakout | 15m close above the prior 24h high on 2x+ volume; buy the retest |
| XOVER | EMA9/21 bull cross | Fresh EMA9/21 cross up with +DI over -DI and price above VWAP |

Each strategy sets its own entry zone, a stop under the level that proves it wrong (0.9 to 3.5 ATR, never more
than 5% away) and three targets in R (multiples of the risk). The numbers in the rules (RSI bands, volume needed,
distance to the EMA...) are settings that strategy discovery can change; they are in `PARAMS` in `scanner.py`,
and the exact rules are on the page's **Strategies** tab.

Every signal also gets the **4-hour trend** (from the 1-hour candles): up when price is above the 4h EMA20 and the
EMA20 is above the EMA50, down when both are the other way round, mixed otherwise. Longs against a 4-hour downtrend
lose 4 points, and the journal learns whether that trait keeps losing.

## The journal and how it learns

- **Every signal is paper-traded**, published or not. An order must fill within 3 hours (in the zone, on the
  trigger close for squeezes, or as a buy-stop for reclaims); then a third comes off at each target, the stop
  moves to breakeven after TP1, a candle touching both stop and target counts as the stop, and whatever is left is
  closed after 12 hours. If a setup is published again with new levels before the old order filled, the newer
  order replaces it.
- **Trading costs.** Every result is after costs: a 0.045% taker fee plus slippage (0.05% on coins trading $1M+ a
  day on a DEX, 0.1% above $200K, 0.2% below) for market entries, buy-stops, stop-losses and closes at market; a
  0.015% maker fee for limit entries and take-profits; and the coin's funding for the hours the trade is open (longs
  pay positive funding). These are Hyperliquid's base-tier fees; change them in `CFG` if your DEX differs.
- **Strategy tournament.** Every signal gets a random twin: the same order (zone, stop and targets, scaled to the
  price) on another coin of the same scan at the same moment. A strategy *passes* only on live trades: at least 40
  on 10+ different days, R per trade after costs more than two day-clustered standard errors above zero, the same
  margin above its twins before costs, and a profit factor of 1.2 or more. It is *rejected* when it clearly loses
  (30+ trades, backtest included). Everything else is *testing* or *on watch* and is paper-traded only. Signals
  taken while the market gate was closed don't count. Only the last 30 days count.
- **Lessons from mistakes** (shown for information only while `lesson_points` is off). Closed trades are grouped by traits they had at entry (RSI 75+, low volume, chasing
  far above EMA21, risk-off market, against the 4-hour trend, thin liquidity, crowded funding, smart money short,
  weak trend, time of day...). When a trait keeps losing compared with everything else, with a clear and
  consistent difference, new signals with that trait lose points; the worst patterns are blocked from the picks.
  Traits that keep winning earn points. Every losing trade is also tagged with what went wrong (stop hunted, failed
  breakout, BTC fell, chased...).
- **Cool-downs.** A coin that stopped out in the last 4 hours loses 6 points; after two separate stop-outs in 24
  hours it is not published for 12 hours.
- **Tuning** (off while `auto_tune` is off). Once a strategy has 30 closed trades, its targets move toward the levels its trades actually reach.
  Its stop widens by 10% when 35%+ of recent stops were hunted (price hit the stop, then the target), and tightens
  when winners rarely dip.

## The 30-day backtest

A new journal starts by downloading 30 days of 15-minute candles for the 150 most traded coins and walking
through them hour by hour. At each hour it does what a live scan does, using only the candles that had closed by
then: rank the coins, analyse the leaders' charts with the 4-hour trend, run every strategy, and paper-trade the
signals with the same rules and costs. So the tournament, the lessons and the goal projection have about a month
of trades from the first hour. Smart-money follow needs live positions that don't exist for the past, so it
starts from zero. Backtest trades are marked in the journal and stop counting after 30 days, when live trades have
taken over.

## Strategy discovery

Paused in version 5 (`discovery` in `CFG`): mutating strategies that have no edge only produces more variants
without one. When it is switched on, once a day the scanner creates 16 new variants of its strategies: one or two changes to a rule setting, an extra
filter (only in risk-on markets, only in a 4-hour uptrend, minimum volume, maximum RSI, minimum ADX, above VWAP,
BTC calm...), different targets or a wider or tighter stop. Each variant is backtested over the last 30 days next
to its parent. The few that clearly beat their parent after costs (at least 40 trades, a positive R per trade even
after allowing for luck, a profit factor of 1.3+) go to a live forward test, up to 12 at a time.

Trying many variants on the same history always finds some that look good by luck, so the backtest only
nominates. A variant in its live test is paper-traded but not published. It is **promoted** (published like the
other strategies) only after it passes the tournament on at least 20 live trades it had never seen, spread over at
least 5 days (one market move can produce 20 look-alike trades in a few hours), and does at least as well as its
parent over the same days. It is **retired** when it loses money live or has not passed within 21 days. A variant
starts with its parent's current targets and stop and keeps them fixed (unless changing them was its mutation),
so the backtest compares the two on equal terms. Up to 16 promoted variants are kept; the
weakest is retired when a better one arrives. The page shows all of it on the **Strategies** tab under Strategy discovery.

## Your plan, position sizes and the goal tracker

- **Plan**: your balance, risk per trade (% of the balance lost if the stop is hit), the most you want at risk
  across open trades, and your maximum leverage. Every pick then shows the position size
  (balance x risk / (distance to the stop + fees and slippage in and out), capped by your leverage, so a stop-out
  loses about the amount you chose), the amount at risk, what all three targets would make after fees, and the
  contract count on DEXs that list the coin as a multiple (1000PEPE, kPEPE).
- **Taking this trade**: tick it on the picks you enter and the plan adds up your open risk, with a warning when it
  goes over your limit. Crypto longs usually fall together when BTC drops, so several of them act like one bigger
  bet.
- **Goal**: your start balance, target and time frame. The tracker shows the daily growth the goal needs, where
  you should be today, your logged balances on a chart against that path, and the pace needed from here.
- **Projection**: the journal's own closed trade results (live published picks once there are 30, the backtest's
  picks until then), replayed at random 800 times for your remaining trades at several risk levels. It
  shows the typical outcome, the chance of reaching the goal and the chance of the balance falling to half of its
  high on the way. Higher risk raises both the chance of a big result and the chance of a deep drop, and the page
  shows both.

The plan and the goal are saved in your browser only (per device) and never leave it.

## Scan now and the Strategy studio

Both buttons start work on your GitHub from the page, so the page needs a GitHub token once, per device:

1. Open **github.com > Settings > Developer settings > Personal access tokens > Fine-grained tokens >
   Generate new token** (the Studio tab has a direct link).
2. Name it `radar`, pick an expiry (90 days is fine), **Repository access: Only select repositories >
   perp-dex-radar**.
3. **Permissions > Repository permissions**: **Actions: Read and write** and **Contents: Read and write**.
4. Generate it, copy it, and paste it into the dashboard's **Studio** tab under **Connect GitHub**.

The token is saved in that browser only and sent only to GitHub. Don't paste it anywhere else; to revoke it,
delete it on the same GitHub page.

- **⟳ Scan now** (top right) starts a full-market scan right away (about 2 minutes) and loads the result
  when it is published. Use it whenever the hourly schedule is late.
- **Studio tab**: build a strategy and test it on past candles.
  - **Build from rules**: pick the chart (15m, 1h or 4h), add conditions (RSI, ADX, volume, distance from
    EMAs or VWAP, Bollinger squeeze, position in the range, breakouts, EMA cross, 4h/1h trend, BTC's move...),
    an entry (at market, a pullback to EMA9/21/50 or VWAP, or a break of the 96-bar high), a stop (ATR
    multiple, under the last swing low, or a percentage), three targets, the fill window, the longest hold and
    the widest stop you accept.
  - **Tune a built-in strategy**: change every setting of one of the eight built-in strategies, add filters,
    change targets and the stop.
  - **Run backtest** tests it on the most traded coins (or your own list): up to 60 days on 15m, a year on 1h,
    two years on 4h, with the scanner's own fill, exit and cost rules. The result shows trades, win rate, R
    per trade, profit factor, drawdown, an equity curve, months, best and worst coins, and whether it would
    pass the tournament. Tuned strategies are compared with the default version on the same data.
  - **Add to my scan** writes the strategy to `strategies.json` in your repository; from the next scan it is
    scanned and paper-traded like the others (1h and 4h strategies check every coin; 15m ones the ~56 most
    active). Pause or delete it any time from the same tab.
  - Tests run as the **Backtest** workflow (`.github/workflows/backtest.yml`) and save their results on a
    separate `results` branch.

**Why not TradingView data?** TradingView has no public data feed and its terms forbid pulling data from it.
The tests use the same exchange candles that TradingView charts for these perps (MEXC, Gate.io, Bitget,
Hyperliquid, Aster). Every pick has an **Open in TradingView** link for charting.

## Alerts (optional)

Each scan can send the new picks scoring 62 or more (at most 5) to Telegram and/or Discord. Without the secrets
below nothing is sent.

**Telegram**

1. In Telegram, open **@BotFather**, send `/newbot` and follow the steps. It gives you a token like
   `123456789:AA...`.
2. Open your new bot and send it any message (a bot can only write to people who wrote to it first).
3. In a browser open `https://api.telegram.org/botYOUR-TOKEN/getUpdates` and find `"chat":{"id":123456789` in the
   reply. That number is your chat id.
4. In the repository: **Settings > Secrets and variables > Actions > New repository secret**. Add
   `TELEGRAM_BOT_TOKEN` (the token) and `TELEGRAM_CHAT_ID` (the number).

**Discord**

1. In your server: **Server Settings > Integrations > Webhooks > New Webhook**, choose the channel, then
   **Copy Webhook URL**.
2. Add it as the repository secret `DISCORD_WEBHOOK_URL`.

The score threshold and the number of picks per message are `alert_min_score` and `alert_max` in `CFG`. Secrets
are never printed in the logs; if sending fails, the page says so on the **All coins** tab under Coverage and data
health.

## Changing how often it runs

In `.github/workflows/scan.yml` change the cron line and the matching `SCAN_EVERY_MIN` value:

- every hour: `cron: "7 * * * *"` and `SCAN_EVERY_MIN: "60"` (default)
- every 30 minutes: `cron: "7,37 * * * *"` and `SCAN_EVERY_MIN: "30"`

Public repositories get unlimited free Actions minutes, so 30 minutes costs nothing extra.

To force a scan at any time: **Actions > Scan > Run workflow**. To wipe the journal and start over (a new
backtest, all strategies back to testing, discovered variants forgotten), tick **Start a new journal** before
clicking **Run workflow**.

Settings such as the number of coins deep-dived, the pass/reject thresholds, the minimum score for a pick, the
costs, the backtest length and the discovery settings are in the `CFG` block at the top of `scanner.py`.

## Good to know

- The journal is stored on your published site (`data/journal.json`) and read back at the start of each run. If
  that read fails for any reason other than "not there yet", the run stops without publishing, so a good journal
  is never overwritten; the next run tries again. If it keeps failing with "unreadable", run the workflow once with
  **Start a new journal** ticked.
- Paper-trading results are a guide, not a promise: the costs are estimates, real fills can be worse in fast
  markets, and a strategy that worked for a month can stop working. A backtest that looks good is a reason to test
  live, not proof. The backtest also uses today's most traded coins, which flatters it a little (coins that moved
  recently are the ones trading most now), and it has no smart-money or funding data for the past.
- No tool can promise a return. Risking a small, fixed share of the account per trade is what keeps a losing
  streak survivable; the goal projection shows what bigger risk does to the odds of losing most of the account.
- Chart prices come from the most liquid source (usually MEXC futures) and differ slightly from each DEX's own
  price. Check the live price on your DEX before placing an order.
- If a DEX's API is down or blocks GitHub's servers, the scan carries on without it and says so under
  Coverage and data health on the page's **All coins** tab. The same goes for any exchange used for candles.
- GitHub sometimes starts scheduled runs a few minutes late at busy times.
- GitHub pauses schedules in repositories with no activity for 60 days. The workflow tries to keep itself switched on;
  if the page ever says the last scan is old, open **Actions > Scan** and click **Enable workflow** or
  **Run workflow**.

This is an educational tool, not financial advice. Perpetual futures are leveraged and can lose more than you put in.
