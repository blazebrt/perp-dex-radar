"""Read-only diagnostic view of the Phase 11 decision document (data/v8/decision.json). Not the product UI (Phase 12).

    python tools/v8/decision_report.py site/data/v8/decision.json                 # summary and the three sections
    python tools/v8/decision_report.py site/data/v8/decision.json --asset BTC     # one asset's decisions and traces
    python tools/v8/decision_report.py site/data/v8/decision.json --json out.json # the machine summary for Research

It only reads the document; every state, rank and reason shown comes from the engine (v8.decision/1)."""
from __future__ import annotations

import argparse
import json
import sys

SECTIONS = ("best_trades_now", "emerging_opportunities", "funding_opportunities")


def research_summary(doc):
    by_id = {c["id"]: c for c in doc.get("candidates") or []}

    def brief(cid):
        c = by_id[cid]
        return {"id": cid, "state": c["state"], "blocking_step": c["blocking_step"], "blockers": c["blockers"],
                "caps": c["caps"], "missing_authorities": c["missing_authorities"],
                "ranking_inputs": c["ranking_inputs"], "placement": {k: v for k, v in c["placement"].items()
                                                                     if k != "trace"}}
    directional = [c for c in by_id.values() if c["type"] == "DIRECTIONAL_STRATEGY"]
    return {"schema": doc.get("schema"), "policy_hash": doc.get("policy_hash"),
            "implementation_hash": doc.get("implementation_hash"), "authority": doc.get("authority"),
            "as_of": doc.get("as_of"), "market_summary": doc.get("market_summary"),
            "portfolio": doc.get("portfolio"), "changes": {k: v for k, v in (doc.get("changes") or {}).items()
                                                           if k != "changes"},
            "sections": {s: {"count": doc[s]["count"], "items": [brief(i["id"]) for i in doc[s]["items"]],
                             "selection_trace": doc[s]["selection_trace"]} for s in SECTIONS},
            "directional_candidates": [brief(c["id"]) for c in sorted(directional, key=lambda c: c["id"])]}


def show_asset(doc, asset, out):
    a = next((x for x in doc.get("assets") or [] if x["asset"] == asset), None)
    if a is None:
        out.write(f"{asset}: not in this decision document (not discovered this scan)\n")
        return 1
    out.write(f"{asset}: {a['state']}  identity={a['identity']}  liquidity={a['execution_liquidity']}  "
              f"blockers={a['blockers']}\n")
    for cid in a["opportunities"]:
        c = next(x for x in doc["candidates"] if x["id"] == cid)
        out.write(f"\n  {cid}: {c['state']}" + (f" (rejected at {c['blocking_step']})" if c["blocking_step"] else "")
                  + f"\n    placement: {c['placement']['reason']}\n")
        for g in c["trace"] + c["placement"]["trace"]:
            out.write(f"    {g['step']:<19} {g['result']:<15} {g['code'] or '':<42} {g['effect']}\n")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("decision")
    ap.add_argument("--asset")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    with open(a.decision) as fh:
        doc = json.load(fh)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(research_summary(doc), fh, indent=1, sort_keys=True)
    if a.asset:
        return show_asset(doc, a.asset, sys.stdout)
    m = doc["market_summary"]
    print(f"decision {doc['schema']}  policy {doc['policy_hash'][:12]}  as_of {doc['as_of']}")
    print(f"discovered {m['discovered_assets']}  opportunities {m['opportunities']}  states {m['opportunity_states']}"
          f"  portfolio {m['portfolio_state']}  zero_trade {m['zero_trade']}")
    for s in SECTIONS:
        t = doc[s]["selection_trace"]
        print(f"{s}: {doc[s]['count']} of max {t['max']}" + (f"  ({t['why_fewer']})" if t["why_fewer"] else ""))
        for i in doc[s]["items"]:
            print(f"  #{i['rank']} {i['id']}  {i['ranking_inputs']}")
        if t["cutoff"]:
            print(f"  cutoff: {t['cutoff']}")
    print("changes:", "previous available" if doc["changes"]["previous_available"] else doc["changes"]["reason"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
