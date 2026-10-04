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
