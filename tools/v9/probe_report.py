"""Turn the probe results (probe-results branch, sources.json) into docs/v9/data-sources.md.

    python tools/v9/probe_report.py sources.json docs/v9/data-sources.md

The status column is what the GitHub-hosted runner (where the scans run) actually got back on the probe date; the
other columns are what each source provides and how v9 uses it."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

# id -> (provides, history, access, v9 use)
NOTES = {
    "binance.fapi.exchangeInfo": ("USD-M symbols, filters, onboard dates", "live", "free, no key", "blocked for US runners (451): use the archive and other venues"),
    "binance.fapi.premiumIndex": ("mark, index, live funding", "live", "free", "blocked (451)"),
    "binance.fapi.fundingRate": ("funding settlements", "since listing", "free", "blocked (451): archive fundingRate instead"),
    "binance.futures.openInterestHist": ("OI 5m-1d", "30 days", "free", "blocked (451): archive metrics instead"),
    "binance.futures.topLongShortAccountRatio": ("top-trader L/S", "30 days", "free", "blocked (451): archive metrics instead"),
    "binance.futures.takerlongshortRatio": ("taker buy/sell ratio", "30 days", "free", "blocked (451): archive klines taker volume instead"),
    "binance.spot.data-api.klines": ("spot candles (market data only)", "full", "free, no key", "spot reference prices, Coinbase premium"),
    "binance.vision.s3.list.um.monthly.klines": ("listing of every USD-M symbol ever traded", "2019+", "free, no key", "point-in-time universe incl. delisted"),
    "binance.vision.um.monthly.klines.1d": ("candles 1m-1mo, quote and taker volume", "2019/2020+", "free, no key", "evidence engine (survivorship-free history)"),
    "binance.vision.um.monthly.klines.delisted": ("candles of delisted symbols", "listing to delisting", "free, no key", "evidence engine: no survivorship"),
    "binance.vision.um.monthly.fundingRate": ("every funding settlement", "since listing", "free, no key", "observed funding in backtests"),
    "binance.vision.um.daily.metrics": ("5-min OI, OI value, top-trader and account L/S, taker L/S ratio", "daily files; start date per symbol to be measured", "free, no key", "positioning signals research (OI, crowding)"),
    "binance.vision.um.monthly.premiumIndexKlines": ("premium index candles (basis)", "since listing", "free, no key", "basis/premium signals"),
    "binance.vision.um.daily.bookDepth": ("order-book depth snapshots by % band", "recent years", "free, no key", "slippage model calibration"),
    "bybit.v5.tickers": ("tickers, OI, funding", "live", "free", "blocked for cloud IPs (403 CDN)"),
    "bybit.v5.open-interest": ("OI history", "limited", "free", "blocked (403)"),
    "bybit.v5.account-ratio": ("account L/S", "limited", "free", "blocked (403)"),
    "bybit.bytick.tickers": ("alternate domain", "live", "free", "blocked (403)"),
    "bybit.public.archive": ("daily trade files per symbol", "2020+", "free, no key", "trade-level history (heavy); optional"),
    "okx.instruments.swap": ("swap instruments", "live", "free, no key", "venue universe"),
    "okx.funding-rate-history": ("funding settlements", "3 months", "free, no key", "multi-venue funding"),
    "okx.history-candles": ("candles", "years", "free, no key", "cross-venue price check"),
    "okx.rubik.oi-history": ("OI history", "days to months by period", "free, no key", "OI signals (live)"),
    "okx.rubik.long-short-account-ratio-contract": ("account L/S per contract", "1,440 points", "free, no key", "crowding signals (live)"),
    "okx.rubik.taker-volume-contract": ("taker buy/sell volume", "1,440 points", "free, no key", "order-flow signals (live)"),
    "okx.liquidation-orders": ("public liquidation orders", "recent", "free, no key", "liquidation signals (live, record forward)"),
    "hl.meta": ("Hyperliquid perps incl. isDelisted", "live", "free, no key", "execution venue universe"),
    "hl.metaAndAssetCtxs": ("mark, OI, funding, premium, volume per perp", "live", "free, no key", "execution venue state"),
    "hl.candleSnapshot.BTC.1d": ("candles (last 5,000 per interval)", "1d since 2022; 4h ~830 days", "free, no key", "execution-venue backtests (delisted included)"),
    "hl.fundingHistory.BTC": ("hourly funding", "since listing (500/page)", "free, no key", "execution-venue funding"),
    "hl.predictedFundings": ("predicted funding across venues (HL, Binance, Bybit)", "live", "free, no key", "cross-venue funding without Binance/Bybit access"),
    "hl.perpsAtOpenInterestCap": ("perps at OI cap", "live", "free, no key", "crowding flag"),
    "hl.leaderboard": ("trader leaderboard (8 MB)", "live", "free, no key", "smart money"),
    "gate.contracts": ("contracts, funding, OI", "live", "free, no key", "venue data"),
    "gate.contract_stats": ("OI, L/S, liquidations per contract", "months", "free, no key", "positioning + liquidations history"),
    "gate.liq_orders": ("liquidation orders", "recent", "free, no key", "liquidations"),
    "gate.candles.1d": ("candles", "years", "free, no key", "cross-venue history"),
    "mexc.contract.detail": ("contracts", "live", "free, no key", "venue data"),
    "mexc.funding.history": ("funding settlements", "long", "free, no key", "funding history"),
    "bitget.tickers": ("tickers, funding", "live", "free, no key", "venue data"),
    "bitget.history-fund-rate": ("funding settlements", "long", "free, no key", "funding history"),
    "bitget.open-interest": ("OI", "live", "free, no key", "OI"),
    "bitget.account-long-short": ("account L/S", "recent", "free, no key", "crowding"),
    "kucoin.futures.contracts": ("contracts, funding, OI", "live", "free, no key", "venue data"),
    "htx.linear.contract_info": ("contracts", "live", "free, no key", "venue data"),
    "htx.linear.his_open_interest": ("OI history", "recent", "free, no key", "OI"),
    "htx.linear.elite_account_ratio": ("top-account L/S", "recent", "free, no key", "crowding"),
    "kraken.futures.tickers": ("tickers, funding, OI", "live", "free, no key", "venue data"),
    "deribit.dvol": ("DVOL implied-volatility index", "years", "free, no key", "volatility regime"),
    "deribit.book_summary.options": ("options book summary (IV, OI)", "live", "free, no key", "options positioning, put/call"),
    "deribit.funding_rate_history": ("perp funding", "long", "free, no key", "BTC/ETH funding"),
    "dydx.perpetualMarkets": ("markets, OI, funding", "live", "free, no key", "venue data"),
    "dydx.historicalFunding": ("funding history", "long", "free, no key", "funding"),
    "aster.premiumIndex": ("mark, funding", "live", "free, no key", "execution venue"),
    "aster.openInterestHist": ("OI history", "-", "free", "not available (404)"),
    "bitfinex.status.deriv": ("perp funding, OI", "live", "free, no key", "venue data"),
    "bitfinex.stats.pos.size.long": ("BTC margin longs/shorts", "years", "free, no key", "BTC positioning signal"),
    "coinbase.spot.candles": ("Coinbase spot candles", "years", "free, no key", "Coinbase premium (US demand)"),
    "coinbase.intl.instruments": ("Coinbase International perps", "live", "free, no key", "venue data"),
    "upbit.market.all": ("Upbit markets (new KRW listings)", "live", "free, no key", "listing events, Korea premium"),
    "upbit.ticker.btc": ("Upbit ticker", "live", "free, no key", "Korea premium"),
    "bithumb.ticker.all": ("Bithumb tickers", "live", "free, no key", "Korea premium"),
    "coingecko.global": ("total market cap, dominance", "live", "free demo key (secret present)", "regime"),
    "coingecko.markets": ("market cap, supply, ATH", "365 days on demo", "free demo key", "fundamentals, unlock proxy"),
    "coingecko.derivatives": ("derivatives tickers across exchanges incl. Binance/Bybit funding and OI", "live", "free demo key", "cross-venue funding/OI where Binance/Bybit APIs are blocked"),
    "coinpaprika.global": ("global market data", "live", "free, no key", "backup fundamentals"),
    "coinpaprika.tickers": ("tickers", "live", "free, no key", "backup fundamentals"),
    "coinlore.tickers": ("tickers", "live", "free, no key", "backup fundamentals"),
    "cryptocompare.histoday": ("history", "-", "key required", "not used (401)"),
    "defillama.oi.overview": ("open interest across protocols", "years", "free, no key", "DEX perp OI"),
    "defillama.derivatives.overview": ("perp volumes", "-", "pro only (402)", "not used"),
    "defillama.dexs.overview": ("DEX volumes", "years", "free, no key", "on-chain activity"),
    "defillama.stablecoincharts.all": ("total stablecoin supply", "years", "free, no key", "liquidity regime (stablecoin flows)"),
    "defillama.coins.current": ("token prices", "live", "free, no key", "backup prices"),
    "defillama.emissions": ("token unlocks", "-", "pro only (402)", "not used; CoinGecko supply growth instead"),
    "dexscreener.boosts": ("boosted/trending tokens", "live", "free, no key", "early-trend discovery (context only)"),
    "geckoterminal.trending": ("trending pools", "live", "free, no key", "early-trend discovery (context only)"),
    "polymarket.markets": ("prediction-market odds", "live", "free, no key", "event risk context"),
    "alternative.fng": ("Crypto Fear & Greed", "since 2018", "free, no key", "sentiment regime"),
    "cnn.fear-greed": ("stock Fear & Greed", "-", "blocked (418)", "not used"),
    "apewisdom.crypto": ("social mention ranks", "live", "free, no key", "sentiment"),
    "stocktwits.btc": ("Stocktwits stream", "live", "free, no key", "sentiment"),
    "reddit.cryptocurrency": ("Reddit posts", "-", "blocked (403)", "not used without OAuth"),
    "cryptopanic.posts": ("news with votes", "recent", "free key (developer plan)", "news events (needs CRYPTOPANIC_API_KEY)"),
    "rss.coindesk": ("news RSS", "recent", "free", "news"),
    "rss.cointelegraph": ("news RSS", "recent", "free", "news"),
    "rss.theblock": ("news RSS", "recent", "free", "news"),
    "rss.decrypt": ("news RSS", "recent", "free", "news"),
    "mempool.fees": ("BTC fee market", "live", "free, no key", "on-chain activity"),
    "mempool.hashrate": ("BTC hashrate", "years", "free, no key", "on-chain context"),
    "blockchain.charts.hashrate": ("BTC charts", "years", "free, no key", "on-chain context"),
    "farside.btc.etf": ("US spot BTC ETF daily flows (HTML table)", "Jan 2024+", "free page (no stated terms)", "institutional flow regime"),
    "yahoo.dxy": ("DXY", "years", "free (unofficial)", "macro regime"),
    "yahoo.spx": ("S&P 500", "years", "free (unofficial)", "macro regime"),
    "fx.open-er-api": ("FX rates", "live", "free, no key", "KRW for Korea premium"),
    "tardis.free.derivative_ticker": ("tick-level funding/OI/mark (1st of each month free)", "2019+", "free sample days", "model validation only"),
    "tardis.free.liquidations": ("liquidations (1st of each month free)", "2019+", "free sample days", "liquidation model validation"),
    "coinalyze.future-markets": ("aggregated OI, funding, predicted funding, liquidations, L/S across exchanges; daily history kept", "intraday ~1,500-2,000 points; daily unlimited", "free with a key (40 calls/min)", "the best free liquidation history: needs COINALYZE_API_KEY"),
    "cmc.global-metrics": ("global metrics", "live", "free key", "optional"),
    "fred.dgs10": ("US 10y yield and macro series", "decades", "free key", "macro regime (optional)"),
    "etherscan.ethsupply": ("ETH on-chain data", "full", "free key", "optional"),
    "ipinfo": ("runner location", "-", "free", "the probe ran from a US (Azure) runner"),
}


def main():
    src, out = sys.argv[1], sys.argv[2]
    d = json.load(open(src))
    when = datetime.fromtimestamp(d["run_at"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = ["# v9 data sources (verified from the GitHub Actions runner)", "",
         f"Every source below was called by `tools/v9/probe_sources.py` from a GitHub-hosted runner (US, Azure), where the "
         f"scans run, on {when}. Status is what came back. Re-run the probe (push to a v9 branch, or Actions > Data source "
         "probe) to refresh; results land on the `probe-results` branch.", "",
         "Rules: official free public endpoints first; respect rate limits and terms; never scrape behind a login; a "
         "source that needs a key is used only when its key is a repository secret.", "",
         "| Source | Group | Status | Provides | History | Access | v9 use |", "|---|---|---|---|---|---|---|"]
    for r in d["results"]:
        n = NOTES.get(r["id"], ("", "", "", ""))
        st = r.get("status")
        mark = "OK" if r.get("ok") else ("needs key" if st == "NEEDS_KEY" else f"blocked/failed ({st})")
        L.append(f"| `{r['id']}` | {r['group']} | {mark} | {n[0]} | {n[1]} | {n[2]} | {n[3]} |")
    ex = d.get("extra", {})
    hl, bn = ex.get("hyperliquid_delisted") or {}, ex.get("binance_archive") or {}
    L += ["", "## Survivorship-free history", "",
          f"- Binance archive: {bn.get('symbols')} USD-M symbols listed in the archive, {bn.get('usdt_perpetual')} USDT "
          "perpetuals, including delisted ones (sample first/last months in sources.json).",
          f"- Hyperliquid: {hl.get('total')} perps in `meta`, {hl.get('delisted')} flagged `isDelisted`; their daily candles "
          "still load (e.g. " + ", ".join(f"{k} {v.get('n')} days" for k, v in (hl.get('delisted_candles') or {}).items()) + ").", ""]
    open(out, "w").write("\n".join(L) + "\n")
    print(f"wrote {out}: {len(d['results'])} sources")


if __name__ == "__main__":
    main()
