# Perp DEX Radar

A dashboard that scans every crypto perp listed on the major decentralised perp exchanges every hour with nine
strategies, paper-trades every signal after trading costs, learns from the results, and invents and tests new
strategy variants every day:

**Hyperliquid, Variational, Aster, edgeX, Lighter, dYdX, Paradex and Extended.**

Each pick comes with an entry zone, stop-loss, three targets, a conviction score out of 100, the DEXs it trades on
(with symbol, multiplier and 24h volume on each), where Hyperliquid's most profitable traders are positioned, the
4-hour trend, a written technical case, and your position size for the balance and risk you set on the page.
Strategies that make money after costs pass; losing ones are rejected and stop being published; the mistakes behind
losing trades change how new signals are scored. A goal tracker shows whether your balance is on the path to your
target and what the journal's own results say about reaching it.

It runs for free on GitHub: GitHub Actions runs `scanner.py` every hour and publishes the result to GitHub Pages.
Nothing runs on your computer.

## Files

| File | What it does |
| --- | --- |
| `scanner.py` | Pulls the data, runs the strategies, the journal, the backtest and strategy discovery, writes the site (Python standard library only) |
| `index.html` | The dashboard page |
| `.github/workflows/scan.yml` | The hourly schedule and the publish step |

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

**Upgrading from version 3?** Replace all four files. The first version-4 run starts a new journal by itself
(older journals were measured without trading costs, so their results can't be mixed with the new ones) and
backtests the last 30 days.

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
- **Strategy tournament.** A strategy is *testing* until it has 15 closed trades. It *passes* with a clearly
  positive R per trade, a profit factor of 1.2 or more and either a 45%+ win rate or winners 1.5x the size of its
  losers. It is *rejected* when it clearly loses money (negative R per trade or a profit factor under 0.8): it is
  no longer published but keeps being paper-traded, so it can come back. Everything in between is *on watch*
  (published with a penalty). Only the last 30 days count.
- **Lessons from mistakes.** Closed trades are grouped by traits they had at entry (RSI 75+, low volume, chasing
  far above EMA21, risk-off market, against the 4-hour trend, thin liquidity, crowded funding, smart money short,
  weak trend, time of day...). When a trait keeps losing compared with everything else, with a clear and
  consistent difference, new signals with that trait lose points; the worst patterns are blocked from the picks.
  Traits that keep winning earn points. Every losing trade is also tagged with what went wrong (stop hunted, failed
  breakout, BTC fell, chased...).
- **Cool-downs.** A coin that stopped out in the last 4 hours loses 6 points; after two separate stop-outs in 24
  hours it is not published for 12 hours.
- **Tuning.** Once a strategy has 30 closed trades, its targets move toward the levels its trades actually reach.
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

Once a day the scanner creates 16 new variants of its strategies: one or two changes to a rule setting, an extra
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
