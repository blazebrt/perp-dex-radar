"""The Phase 3 evidence accounting of a smart-money journal, read-only (v8 Phase 3, final closure).

    python tools/v8/smart_journal_evidence.py smart_journal.json [--json out.json]

Applies smart.mark_legacy() and smart.accuracy() to an in-memory copy of a journal (the published one: the Scan
workflow saves it to the journal-data branch) and reports every paper trade by evidence class - qualified (entry-time
VERIFIED_CRYPTO proof, in the live record) or without entry-time identity proof (kept, never counted) - with the coins,
the live record and verdict under the Phase 3 rules, and the pre-Phase-3 live record (every closed signal trade) for
comparison. The input file is never written."""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

import smart as SM  # noqa: E402


def report(J, research):
    J2 = copy.deepcopy(J)
    marked = SM.mark_legacy(J2)
    acc = SM.accuracy(research, J2)
    by = {}
    for part in ("open", "closed"):
        for tr in J2.get(part) or []:
            cls = "qualified" if SM.trade_qualified(tr) else "unqualified"
            by.setdefault(f"{cls}_{part}_{tr.get('kind', 'signal')}", []).append(tr.get("coin"))
    closed = J.get("closed") or []
    return {"journal": {"engine": J.get("engine"), "scans": J.get("scans"), "created": J.get("created"),
                        "updated": J.get("updated"), "open": len(J.get("open") or []), "closed": len(closed)},
            "already_with_provenance": sum(1 for t in (J.get("open") or []) + closed if "identity_qualified" in t),
            "marked_legacy": marked, "evidence": acc["evidence"], "coins": {k: v for k, v in sorted(by.items())},
            "phase3": {"live": acc["live"], "live_info": acc["live_info"], "verdict": acc["verdict"],
                       "legacy_unqualified": acc["legacy_unqualified"]},
            "pre_phase3": {"live": SM.live_stats([x for x in closed if x.get("kind", "signal") == "signal"]),
                           "live_info": SM.live_stats([x for x in closed if x.get("kind") == "info"])}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("journal")
    ap.add_argument("--json", default=None)
    ap.add_argument("--research", default=os.path.join(ROOT, "smart_research.json"))
    a = ap.parse_args(argv)
    with open(a.journal) as fh:
        J = json.load(fh)
    try:
        with open(a.research) as fh:
            research = json.load(fh)
    except (OSError, ValueError):
        research = None
    rep = report(J, research)
    if a.json:
        with open(a.json, "w") as fh:
            json.dump(rep, fh, indent=1, sort_keys=True)
    print(json.dumps(rep, indent=1, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
