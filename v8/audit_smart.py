"""End-of-run audit of smart.run(): trader-level selection counts and the smart-money engine's disposition for
every coin its proven traders hold. Since v8 Phase 3 a crowd on a coin without crypto execution identity is recorded
with its identity reason (IDENTITY_UNVERIFIED, TRADFI_CLASSIFIED / TRADFI_EXPOSURE_EXCLUDED, AMBIGUOUS_EXPOSURE,
IDENTITY_AUTHORITY_MISSING) and the step SMART_CROWD_IDENTITY_BLOCKED - never as SMART_NO_CROWD. Coins of the registry the engine never saw get SMART_NOT_HELD or
SMART_VENUE_NOT_COVERED when the snapshot is assembled (this process has no registry)."""
from __future__ import annotations

from . import ledger as LG
from . import parts
from . import taxonomy as T


def trader_reasons(board, traders, snap, cfg):
    """Counts of what happened to every leaderboard row, mirroring smart.select_traders() check by check. The set
    classified as selected must equal the engine's own selection (checked on every run)."""
    import smart as S
    counts = {k: 0 for k in T.TRADER_REASONS}
    ok_addrs = []
    for r in (board or {}).get("leaderboardRows") or []:
        addr = r.get("ethAddress")
        if not isinstance(addr, str) or not addr.startswith("0x"):
            counts["TRADER_BAD_ADDRESS"] += 1
            continue
        av = S.fnum(r.get("accountValue"))
        p = S.perf(r)
        z = {"pnl": 0.0, "roi": 0.0, "vlm": 0.0}
        a, m = p.get("allTime", z), p.get("month", z)
        if av < cfg["min_account"]:
            counts["TRADER_ACCOUNT_BELOW_MIN"] += 1
        elif a["pnl"] < cfg["min_all_pnl"]:
            counts["TRADER_PNL_BELOW_MIN"] += 1
        elif m["pnl"] < -cfg["max_month_loss"] * av:
            counts["TRADER_MONTH_LOSS"] += 1
        elif m["vlm"] > cfg["mm_ratio"] * max(av, 1.0) or m["vlm"] <= 0:
            counts["TRADER_MARKET_MAKER_OR_INACTIVE"] += 1
        else:
            ok_addrs.append((a["pnl"], addr))
    ok_addrs.sort(key=lambda x: -x[0])
    sel = {addr for _, addr in ok_addrs[:cfg["max_traders"]]}
    counts["TRADER_BEYOND_MAX"] = max(0, len(ok_addrs) - cfg["max_traders"])
    read = {S.hid(a) for a in sel} & set(snap)
    counts["TRADER_SELECTED"] = len(read)
    counts["TRADER_UNREADABLE"] = len(sel) - len(read)
    consistent = sel == {t["addr"] for t in traders}
    return counts, consistent


IDENTITY_HEALTH = {"IDENTITY_UNVERIFIED": T.MISSING, "IDENTITY_AUTHORITY_MISSING": T.MISSING,
                   "AMBIGUOUS_EXPOSURE": T.CONFLICTED}


def smart_part(now, cfg, board, traders, snap, coins, open_trades, authority=None):
    import scanner as sc
    L = LG.Ledger("smart")
    held_any, held_min = {}, set()
    for tid, s in snap.items():
        for name, (szi, usd, entry, upnl) in (s.get("pos") or {}).items():
            coin, _ = sc.canon(name)
            held_any.setdefault(coin, []).append(abs(usd))
            if abs(usd) >= cfg["min_position_usd"]:
                held_min.add(coin)
    rows = {r["coin"]: r for r in coins}
    L.expect(sorted(set(held_any) | set(rows)))
    published = {r["coin"] for r in sorted(coins, key=lambda r: (not r["signal"], not r["info"],
                                                                  -(r["usd_long"] + r["usd_short"])))[:60]}
    opened = [tr for tr in open_trades if tr.get("t_in") == now]
    opened_c = {tr["coin"] for tr in opened}
    busy0 = {tr["coin"] for tr in open_trades if tr.get("t_in") != now}
    for t in sorted(set(held_any) | set(rows)):
        r = rows.get(t)
        k = [f"hyperliquid:{r['hl']}"] if r else None
        if r is None:
            L.final(t, "SMART_POSITIONS_BELOW_MIN", "positions", o={"largest_usd": max(held_any[t])},
                    th={"min_position_usd": cfg["min_position_usd"]})
            continue
        steps = []
        o = {"n_long": r["n_long"], "n_short": r["n_short"], "new_long": r["new_long"], "new_short": r["new_short"],
             "side": r.get("side"), "identity": r.get("identity")}
        th = {"rule": cfg["signal"], "min_traders": cfg["signal_min_traders"], "window_h": cfg["signal_window_h"],
              "signal_sides": list(cfg["signal_sides"])}
        if r.get("side"):
            if t in opened_c:
                steps.append("PAPER_OPENED")
            elif t in busy0:
                steps.append("PAPER_BUSY")
            elif len(open_trades) >= cfg["max_open"]:
                steps.append("PAPER_LIMIT_REACHED")
            else:
                steps.append("PAPER_NO_PRICE")
        if t not in published:
            steps.append("NOT_IN_PUBLISHED_LIST")
        blk = r.get("identity_block")
        if blk:
            # v8 Phase 3: the crowd existed; the coin's identity kept it from being a signal (never SMART_NO_CROWD)
            o.update(crowd_side=blk.get("crowd_side"), crowd_signal=blk.get("crowd_signal"),
                     crowd_info=blk.get("crowd_info"), authority=blk.get("authority"))
            L.final(t, blk["reason"], "identity", o=o, th=dict(th, identity="VERIFIED_CRYPTO"), k=k,
                    x=steps + ["SMART_CROWD_IDENTITY_BLOCKED"], src="hyperliquid",
                    h=IDENTITY_HEALTH.get(blk["reason"], T.HEALTHY))
        elif r.get("signal"):
            L.final(t, "SMART_CROWD_SIGNAL", "signal", o=o, th=th, k=k, x=steps, src="hyperliquid")
        elif r.get("info"):
            L.final(t, "SMART_CROWD_INFO", "signal", o=o, th=th, k=k, x=steps, src="hyperliquid")
        else:
            L.final(t, "SMART_NO_CROWD", "signal", o=o, th=th, k=k, x=steps, src="hyperliquid")
    part = L.to_part()
    counts, consistent = trader_reasons(board, traders, snap, cfg)
    if not consistent:
        L.problem("trader classification differs from smart.select_traders()")
        part["problems"] = L.problems
    part["traders"] = {"leaderboard_rows": len((board or {}).get("leaderboardRows") or []), "selected": len(traders),
                       "read": len(snap), "by_reason": counts}
    part["stages"] = {"coins_held": len(held_any), "coins_min_size": len(held_min), "rows": len(rows),
                      "signals": sum(1 for r in coins if r.get("signal")),
                      "info": sum(1 for r in coins if r.get("info")), "paper_opened": len(opened),
                      "published": len(published),
                      # v8 Phase 3: crypto execution identity of the rows, and the crowds it blocked
                      "identity": {st or "NONE": sum(1 for r in coins if r.get("identity") == st)
                                   for st in sorted({r.get("identity") for r in coins}, key=lambda x: x or "")},
                      "identity_blocked": sorted(r["coin"] for r in coins if r.get("identity_block")),
                      "identity_authority": authority}
    return part


def audit(out_dir, now, **kw):
    """Called once at the end of smart.run(). Writes data/v8/parts/smart.json. Never raises."""
    parts.safe_audit("smart", out_dir, smart_part, ts=now, now=now, **kw)
