"""The v8 Phase 3 production-evidence closure on the PUBLISHED journals, read-only (the Research workflow runs it).

    quant: the published quant journal replayed by this branch's quant.py and by the base's (each with live data,
           nothing published), then compared: actionable and identity-blocked open positions, current identity of every
           open position, qualified vs legacy closed trades, the live record before and after, dashboard signals and
           (with node) the Analyzer's signals for every blocked coin.

        python tools/v8/closure_evidence_report.py quant --head out_pubq --base out_pubq_base \\
            --journal published_quant_journal.json [--json out.json]

    radar: the published radar journal (journal.json) under the base's learning (every row counted) and this branch's
           (legacy live rows quarantined): evidence classes, twins and pair integrity, the identity of the coins of
           legacy rows (this scan's identity authority), strategy statuses and live records before and after.

        python tools/v8/closure_evidence_report.py radar --journal published_journal.json --base-root BASE \\
            [--authority out_new/data/v8/identity_authority.json] [--json out.json]

The input journals are never written: every computation runs on a copy."""
from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _load(p):
    try:
        with open(p) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------- quant
def _analyzer(quant_path, coins, now):
    node = shutil.which("node")
    if not node or not coins:
        return None
    js = r"""
const TA = require(process.argv[2]); const fs = require("fs");
const quant = JSON.parse(fs.readFileSync(process.argv[3], "utf8")), coins = JSON.parse(process.argv[4]);
const out = {tested: {}, signal_coins: TA.signalCoins({quant}, Number(process.argv[5])).map((x) => [x.coin, x.side, x.tier])};
for (const c of coins) { const r = TA.testedSignals(c, {quant});
  out.tested[c] = {signals: r.signals.map((s) => [s.src, s.side, s.tier]), notes: r.notes.filter((n) => n.src === "quant").map((n) => n.text)}; }
console.log(JSON.stringify(out));"""
    p = os.path.join(os.path.dirname(os.path.abspath(quant_path)), "_closure_analyzer.js")
    with open(p, "w") as fh:
        fh.write(js)
    try:
        r = subprocess.run([node, p, os.path.join(ROOT, "analyze.js"), quant_path, json.dumps(sorted(coins)),
                            str(int(now))], capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(p)
    return json.loads(r.stdout) if r.returncode == 0 else {"error": r.stderr[-500:]}


def quant_report(head, base, journal):
    sys.path.insert(0, ROOT)
    import dashboard as D
    import quant as Q
    from v8 import evidence as EV
    qh, qb = _load(os.path.join(head, "data", "quant.json")), _load(os.path.join(base, "data", "quant.json"))
    jh = _load(os.path.join(head, "data", "quant_journal.json"))
    J0 = _load(journal) or {}
    if not qh or not jh:
        return {"error": "the branch quant run wrote no quant.json / quant_journal.json"}
    ids0 = {t["id"] for t in (J0.get("open") or []) + (J0.get("closed") or [])}
    ids1 = {t["id"] for t in jh["open"] + jh["closed"]}
    sig_h = {c: [x for x in v if x["src"] == "quant"] for c, v in D.signals(None, qh, None, None).items()}
    sig_b = {c: [x for x in v if x["src"] == "quant"] for c, v in D.signals(None, qb or {}, None, None).items()}
    act_h = sorted({o["c"] for o in qh.get("open") or []})
    act_b = sorted({o["c"] for o in (qb or {}).get("open") or []})
    blocked = qh.get("blocked_open") or []
    dist = {}
    for o in (qh.get("open") or []) + blocked:
        dist[o.get("identity") or "NONE"] = dist.get(o.get("identity") or "NONE", 0) + 1
    out = {
        "published_journal": {"open": len(J0.get("open") or []), "closed": len(J0.get("closed") or []),
                              "scans": J0.get("scans"), "updated": J0.get("updated"),
                              "with_entry_proof": sum(1 for t in (J0.get("open") or []) + (J0.get("closed") or [])
                                                      if "identity_qualified" in t)},
        "journal_after": {"open": len(jh["open"]), "closed": len(jh["closed"]),
                          "published_trades_kept": ids0 <= ids1, "lost": sorted(ids0 - ids1)},
        "actionable_open": {"n": len(qh.get("open") or []), "coins": act_h},
        "blocked_open": [{k: b.get(k) for k in ("id", "c", "s", "d", "t_in", "r_now", "exit_stop", "exit_time",
                                                 "identity", "identity_reason", "identity_qualified",
                                                 "identity_unqualified_reason")} for b in blocked],
        "current_identity_of_open": dist,
        "evidence": qh.get("evidence"),
        "qualified_closed": sum(1 for t in jh["closed"] if EV.qualified(t)),
        "legacy_closed": sum(1 for t in jh["closed"] if not EV.qualified(t)),
        "live_all": {"head": qh.get("live_all"), "base": (qb or {}).get("live_all")},
        "live": {"head": qh.get("live"), "base": (qb or {}).get("live")},
        "legacy_unqualified": qh.get("legacy_unqualified"),
        "base_actionable_open": {"n": len((qb or {}).get("open") or []), "coins": act_b},
        "removed_actionable": sorted(set(act_b) - set(act_h)), "added_actionable": sorted(set(act_h) - set(act_b)),
        "dashboard_quant_signals": {"head": sorted(sig_h), "base": sorted(sig_b),
                                    "removed": sorted(set(sig_b) - set(sig_h)), "added": sorted(set(sig_h) - set(sig_b))},
        "blocked_in_dashboard": sorted({b["c"] for b in blocked} & set(sig_h)),
        "rule": Q.journal_evidence.__doc__.split("\n")[0],
    }
    out["analyzer"] = _analyzer(os.path.join(head, "data", "quant.json"), {b["c"] for b in blocked},
                                qh.get("generated") or 0)
    if out["analyzer"] and "tested" in out["analyzer"]:
        out["analyzer_blocked_signals"] = {c: v["signals"] for c, v in out["analyzer"]["tested"].items() if v["signals"]}
        out["analyzer_blocked_in_signal_coins"] = sorted({c for c, _, _ in out["analyzer"]["signal_coins"]}
                                                         & {b["c"] for b in blocked})
    return out


# --------------------------------------------------------------------------- radar
def learn_state(root, journal, now, mark):
    """Run in a subprocess per checkout: that checkout's scanner.learn() on a copy of the journal."""
    r = subprocess.run([sys.executable, os.path.abspath(__file__), "radar-learn", "--root", root, "--journal", journal,
                        "--now", str(now)] + (["--mark"] if mark else []), capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        return {"error": (r.stdout[-800:] + r.stderr[-800:])}
    return json.loads(r.stdout.strip().splitlines()[-1])


def radar_learn(root, journal, now, mark):
    sys.path.insert(0, root)
    import scanner as sc
    with open(journal) as fh:
        J = json.load(fh)
    user, _ = sc.load_user_strategies(os.path.join(root, "strategies.json")) if os.path.exists(
        os.path.join(root, "strategies.json")) else ([], None)
    sc.USER_SPECS[:] = user
    sc.load_specs(J)
    if mark:
        from v8 import evidence as EV
        EV.mark_legacy(t for t in J["open"] + J["closed"] if not t.get("bt"))
    L = sc.learn(J, now)
    out = {sid: {"status": v["status"], "why": v["why"], "n": v["stat"].get("n"), "live_n": (v.get("live") or {}).get("n"),
                 "live_exp": (v.get("live") or {}).get("exp"), "live_days": (v.get("live") or {}).get("days"),
                 "edge_live": (v.get("edge_live") or {}).get("edge"), "bt_n": v["stat"].get("bt_n")}
           for sid, v in L["strat"].items()}
    print(json.dumps({"strategies": out, "lessons": len(L.get("lessons") or []), "cool": sorted(L.get("cool") or {}),
                      "tp_r": sorted(L.get("tp_r") or {})}, default=str))


def published_compare(head_latest, base_latest):
    """The scanner's published output with the published journal, branch vs base: picks, watch list, strategy
    statuses and live counts (what the quarantine changes in production)."""
    h, b = _load(head_latest), _load(base_latest)
    if not h or not b:
        return None

    def view(x):
        j = x.get("journal") or {}
        return {"picks": sorted(p["coin"] for p in x.get("picks") or []),
                "watch": sorted(w["coin"] for w in x.get("watch") or []),
                "strategies": {s["id"]: [s["status"], s.get("live_n"), s.get("n")] for s in j.get("strategies") or []},
                "counts": j.get("counts"), "live_picks": ((j.get("picks") or {}).get("all") or {}).get("closed")}
    vh, vb = view(h), view(b)
    return {"head": vh, "base": vb,
            "picks_removed": sorted(set(vb["picks"]) - set(vh["picks"])),
            "picks_added": sorted(set(vh["picks"]) - set(vb["picks"])),
            "watch_removed": sorted(set(vb["watch"]) - set(vh["watch"])),
            "watch_added": sorted(set(vh["watch"]) - set(vb["watch"])),
            "status_changes": {k: [vb["strategies"].get(k, [None])[0], v[0]] for k, v in vh["strategies"].items()
                               if vb["strategies"].get(k, [None])[0] != v[0]},
            "legacy_unqualified": (h.get("journal") or {}).get("legacy_unqualified"),
            "minutes_apart": round(abs((h.get("scan_t") or 0) - (b.get("scan_t") or 0)) / 60, 1)}


def radar_report(journal, base_root, authority, head_latest=None, base_latest=None):
    sys.path.insert(0, ROOT)
    import scanner as sc
    from v8 import evidence as EV
    J0 = _load(journal)
    if not J0:
        return {"error": f"no readable journal at {journal}"}
    J = copy.deepcopy(J0)
    EV.mark_legacy(t for t in J["open"] + J["closed"] if not t.get("bt"))
    auth = _load(authority) if authority else None
    ident = {t: v[0] for t, v in ((auth or {}).get("states") or {}).items()} if auth else None
    ev = sc.journal_evidence(J, ident)
    now = int(J0.get("updated") or 0)
    rows = J0["open"] + J0["closed"]
    out = {"journal": {"open": len(J0["open"]), "closed": len(J0["closed"]), "scans": J0.get("scans"),
                       "created": J0.get("created"), "updated": J0.get("updated"),
                       "with_entry_proof": sum(1 for t in rows if "identity_qualified" in t)},
           "rows": {"total": len(rows), "backtest": sum(1 for t in rows if t.get("bt")),
                    "live": sum(1 for t in rows if not t.get("bt")),
                    "twins": sum(1 for t in rows if sc.is_twin(t["s"])),
                    "live_twins": sum(1 for t in rows if sc.is_twin(t["s"]) and not t.get("bt")),
                    "copies": sum(1 for t in rows if t.get("dup"))},
           "evidence": ev, "identity_authority": {"scan_id": (auth or {}).get("scan_id"),
                                                  "version": (auth or {}).get("identity_version")} if auth else None}
    out["before"] = learn_state(base_root, journal, now, mark=False) if base_root else None
    out["after"] = learn_state(ROOT, journal, now, mark=True)
    if out["before"] and "strategies" in out["before"] and "strategies" in out["after"]:
        out["status_changes"] = {sid: [out["before"]["strategies"][sid]["status"], v["status"]]
                                 for sid, v in out["after"]["strategies"].items()
                                 if sid in out["before"]["strategies"]
                                 and out["before"]["strategies"][sid]["status"] != v["status"]}
        out["passed_before"] = sorted(s for s, v in out["before"]["strategies"].items() if v["status"] == "passed")
        out["passed_after"] = sorted(s for s, v in out["after"]["strategies"].items() if v["status"] == "passed")
    if head_latest and base_latest:
        out["published_outputs"] = published_compare(head_latest, base_latest)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quant")
    q.add_argument("--head", required=True)
    q.add_argument("--base", required=True)
    q.add_argument("--journal", required=True)
    q.add_argument("--json", default=None)
    r = sub.add_parser("radar")
    r.add_argument("--journal", required=True)
    r.add_argument("--base-root", default=None)
    r.add_argument("--authority", default=None)
    r.add_argument("--head-latest", default=None, help="latest.json of this branch's scan with the published journal")
    r.add_argument("--base-latest", default=None, help="latest.json of the base's scan with the published journal")
    r.add_argument("--json", default=None)
    rl = sub.add_parser("radar-learn")
    rl.add_argument("--root", required=True)
    rl.add_argument("--journal", required=True)
    rl.add_argument("--now", type=int, required=True)
    rl.add_argument("--mark", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "radar-learn":
        radar_learn(os.path.abspath(a.root), a.journal, a.now, a.mark)
        return 0
    rep = quant_report(a.head, a.base, a.journal) if a.cmd == "quant" else radar_report(
        a.journal, a.base_root, a.authority, a.head_latest, a.base_latest)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=1, sort_keys=True, default=str, ensure_ascii=False)
    print(json.dumps(rep, indent=1, sort_keys=True, default=str, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
