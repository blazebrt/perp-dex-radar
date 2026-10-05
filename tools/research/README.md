# Research engine

The code behind `quant_research.json` and the three strategies in `quant.py`. Needs Python 3.11+ with numpy,
pandas and numba (`pip install numpy pandas numba`). Not used by the scans.

1. Get the data: run the **Market data** workflow (Actions tab, or push a branch whose name starts with `data`).
   It saves a year of 1h candles, three years of 4h candles and funding on the `market-data` branch. Then
   `git fetch origin market-data && mkdir md && git archive origin/market-data | tar -x -C md`.
2. `python test_qsim.py` checks the trade simulator (stop first, gaps, trailing stops, funding, shorts).
3. `python qrun.py --md md` runs every strategy on the last year (first 8 months vs last 4), with random twins.
4. `python qrun3y.py md out` runs the 4h and daily strategies over three years, per year.
5. `python qgrid.py md out` shows how the three live strategies hold up when their settings change.
6. `python parity.py md` and `python parity_sim.py md` check that `quant.py` (the live code) gives the same signals
   and the same trade results as this engine on the same candles.
7. `python qexport.py md ../../quant_research.json` rebuilds the file the page reads.

Rules used everywhere: signals on closed bars only, entry at the next open, stop checked before the target in the
same bar, trailing stops moved at the close and applied from the next bar, gaps exit at the open, taker fee 0.045%
each way, slippage by liquidity, MEXC funding while held (longs pay positive funding).

## Coin picks (version 7)

The code behind `picks_research.json` and the swing scores in `picks.py`:

- `pk_data.py` builds daily bars from the 4h data and the coin checks (90-day low and high, RSI, Bollinger squeeze,
  ATR, 30-day return, higher low, volume, VWAP, 4h trend, relative strength) plus what happened next.
- `pk_trades.py` trades every coin on every day with the plan shown on the page (next open, stop 2 ATR between 5% and
  25%, trailing stop 3 ATR fixed at entry, 30 days at most, costs) and records R multiples.
- `pk_score.py` holds the long ("coiled bottom") and short ("downtrend bounce") scores and an account simulation.
- `pk_day.py` repeats the work on hourly candles for day trades (1.5 ATR stop, 2.5 ATR trail, 24 hours at most).
- `python picks_export.py md` rebuilds `../../picks_research.json` (score bands by year, account simulations, the
  day-trade results and the findings shown on the page).
- `python parity_picks.py md` checks that `picks.py` (standard library) gives exactly the same scores as `pk_score.py`
  on the same candles.
- `python pk_extra.py md` tests the live extra checks (funding, open interest, liquidations, top-trader and crowd
  ratios, supply growth, market cap, volume against market cap) where history exists: Gate.io statistics since
  April 2026 and a year of CoinGecko data (downloaded by `tools/fetch_extra.py` in the Market data workflow).
  `picks_export.py` also writes `../../picks_seed.json`, the last 45 days of circulating supply per coin.

How the score was chosen: about 25 checks were tested one by one and in combinations on every coin with $5M+ a day
from late 2023 to October 2026, year by year and in rising and falling markets. Kept were the ones that improved the
trade result in every year: for longs, being within 30% of the 90-day low *together with* RSI above 45 and a
volatility squeeze; for shorts, a bounce (RSI above 50) inside a downtrend while still well above the 90-day low.
Checks that only worked in one year (30-day momentum, breakouts, relative strength) or never (distance from the
all-time high on its own) were left out or kept small. A model trained on the first two years and tested on the
third (linear and gradient-boosted trees) did no better out of sample than these simple rules.

## Smart money (version 7.2)

The test behind `smart_research.json` and the signal `smart.py` trades (standard library only):

1. Get the data: the **Smart money research** workflow runs `smart_collect.py` on GitHub (the Hyperliquid API is not
   reachable from everywhere) and saves the leaderboard, 380 traders' account histories, 90 days of their trade fills
   and hourly candles on the `smart-data` branch (addresses hashed). Then
   `git fetch origin smart-data && mkdir sd && git archive origin/smart-data | tar -x -C sd`.
2. `python smart_backtest.py sd` compares the methods on the whole window; `--clean` leaves out the traders picked
   for last month's results and judges only the last 30 days (no hindsight in who is looked at).
3. `python smart_backtest.py sd --export ../../smart_research.json` rebuilds the file the page reads: the clean test
   of the rule the live engine trades (`CHOSEN`), the same rule on the whole window, the long side, and every method
   compared.

Rules: who counts as proven is decided from each trader's PnL history up to that day; positions come from the fills
(the API's own "position before" of the next fill; fills in the same second are put back in the order they link up);
entries are new or added positions of $25k+ and 5%+ of the account; a signal is entered at the next hourly open and
judged 24 hours later after 0.09% costs, against the average move of every coin over the same hours.

