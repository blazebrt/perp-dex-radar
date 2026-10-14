"""Trade alerts (v9): a Telegram and/or Discord message when the desk's decision gains a TRADE.

    python -m v9.alerts --decision site/data/v8/decision.json [--pages-url URL]

Reads only the published decision (v8.decision/1). A candidate that is TRADE now and was not in the previous published
decision (the document's own change explanation, `changes`) is announced once: the coin, the side, the strategy, the
authority tier, the plan exactly as the engine's proposal states it, the archive expectation of a probation side and
the decision's valid-until time. Nothing is announced when the previous decision is unknown (no alert storm after a
reset), and at most five per scan (the section maximum).

Channels, from repository secrets: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, DISCORD_WEBHOOK_URL. With none set, nothing
is sent. Never raises, never places an order, never changes the decision."""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

SCHEMA = "v8.decision/1"
MAX_ALERTS = 5
STRATEGY_NAMES = {"XSMOM": "momentum rotation", "TSMOM": "daily trend rider", "TREND_EMA": "4-hour trend crossover"}


def _num(x):
    return not isinstance(x, bool) and isinstance(x, (int, float)) and math.isfinite(x)


def _price(x):
    if not _num(x):
        return "–"
    a = abs(x)
    d = 1 if a >= 1000 else 2 if a >= 100 else 4 if a >= 1 else min(12, int(math.ceil(-math.log10(a))) + 4) if a > 0 else 2
    return f"{x:,.{d}f}".rstrip("0").rstrip(".")


def _pct(x, d=2):
    return f"{x * 100:.{d}f}%" if _num(x) else "–"


def _hold(h):
    """The proposal's time exit (hours) in words, or None when the engine states none."""
    if isinstance(h, bool) or not isinstance(h, int) or h <= 0:
        return None
    return f"{h} hours" if h % 24 else "1 day" if h == 24 else f"{h // 24} days"


def new_trades(doc):
    """The candidates that became TRADE since the previous published decision (none when it is unknown)."""
    ch = doc.get("changes") or {}
    if not ch.get("previous_available"):
        return []
    ids = []
    for c in ch.get("changes") or []:
        if not isinstance(c, dict) or c.get("current_state") != "TRADE":
            continue
        if c.get("change") == "NEW_CANDIDATE" or c.get("previous_state") != "TRADE":
            ids.append(c.get("id"))
    by = {c.get("id"): c for c in doc.get("candidates") or [] if isinstance(c, dict)}
    out = [by[i] for i in ids if i in by and by[i].get("state") == "TRADE"]
    return out[:MAX_ALERTS]


def message(c, doc, pages_url=None):
    side = {1: "LONG", -1: "SHORT"}.get(c.get("direction"), "?")
    sid = c.get("strategy") or "?"
    tier = c.get("authority_tier")
    p = c.get("proposal") or {}
    lines = [f"Perp Decision Desk: new TRADE",
             f"{c.get('asset')} {side} · {sid} ({STRATEGY_NAMES.get(sid, 'strategy')})"
             + (" · probation, reduced size" if tier == "PROBATION" else " · requalified" if tier == "FULL" else "")]
    if _num(p.get("mark")) and _num(p.get("stop")) and p["mark"] > 0:
        lines.append(f"Enter near {_price(p['mark'])} · stop {_price(p['stop'])} ({_pct(abs(p['mark'] - p['stop']) / p['mark'], 1)} away)"
                     + (f" · risk {_pct(p['risk_fraction'])} of the account" if _num(p.get("risk_fraction")) else ""))
    if _num(p.get("trailing_stop_pct")) and p["trailing_stop_pct"] > 0:
        lines.append(f"Trailing stop {_pct(p['trailing_stop_pct'])} behind the best close")
    if _hold(p.get("time_exit_hours")):
        lines.append(f"Exit at the stop or {_hold(p['time_exit_hours'])} after you enter, whichever comes first")
    exp = ((c.get("probation") or {}).get("expectation") or {})
    if _num(exp.get("out_of_sample_mean_R")):
        lo, hi = exp.get("out_of_sample_lower_95"), exp.get("out_of_sample_upper_95")
        lines.append(f"Archive: {exp['out_of_sample_mean_R']:+.2f}R per trade out of sample"
                     + (f" (95% {lo:+.2f} to {hi:+.2f})" if _num(lo) and _num(hi) else "") + "; past results do not promise future ones")
    vu = c.get("valid_until")
    if _num(vu):
        lines.append(f"Valid until {datetime.fromtimestamp(vu, timezone.utc):%Y-%m-%d %H:%M} UTC. You decide and place every order.")
    if pages_url:
        lines.append(pages_url.rstrip("/") + "/analyze.html?coin=" + urllib.parse.quote(str(c.get("asset") or "")))
    return "\n".join(lines)


def post_json(url, body, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "perp-dex-radar/v9"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def send(text, env=None, post=post_json):
    """Send to every configured channel. Returns {channel: "SENT" | "FAILED: ..."}; empty when none is configured."""
    env = os.environ if env is None else env
    out = {}
    token, chat = env.get("TELEGRAM_BOT_TOKEN"), env.get("TELEGRAM_CHAT_ID")
    if token and chat:
        try:
            post(f"https://api.telegram.org/bot{token}/sendMessage",
                 {"chat_id": chat, "text": text, "disable_web_page_preview": True})
            out["telegram"] = "SENT"
        except Exception as e:  # noqa: BLE001 - an alert never stops the scan (the token never appears in the log)
            out["telegram"] = f"FAILED: {type(e).__name__} {getattr(e, 'code', '')}".strip()
    hook = env.get("DISCORD_WEBHOOK_URL")
    if hook:
        try:
            post(hook, {"content": text[:1900]})
            out["discord"] = "SENT"
        except Exception as e:  # noqa: BLE001
            out["discord"] = f"FAILED: {type(e).__name__} {getattr(e, 'code', '')}".strip()
    return out


def run(doc, pages_url=None, env=None, post=post_json):
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        return {"status": "NO_DECISION", "alerts": []}
    trades = new_trades(doc)
    sent = []
    for c in trades:
        text = message(c, doc, pages_url)
        sent.append({"id": c.get("id"), "channels": send(text, env, post), "text": text})
    configured = bool((env or os.environ).get("DISCORD_WEBHOOK_URL")) or bool(
        (env or os.environ).get("TELEGRAM_BOT_TOKEN") and (env or os.environ).get("TELEGRAM_CHAT_ID"))
    return {"status": "OK" if configured else "NO_CHANNEL_CONFIGURED", "alerts": sent}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--decision", required=True)
    ap.add_argument("--pages-url", default=None)
    a = ap.parse_args(argv)
    try:
        doc = json.load(open(a.decision))
    except Exception as e:  # noqa: BLE001
        print(f"alerts: no decision to read ({type(e).__name__})")
        return 0
    r = run(doc, a.pages_url)
    print(f"alerts: {r['status']}, {len(r['alerts'])} new TRADE(s)"
          + "".join(f"\n  {x['id']}: {x['channels'] or 'no channel'}" for x in r["alerts"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
