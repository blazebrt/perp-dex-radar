"""Disposition ledger: one final disposition per asset per engine, and the engine's coverage accounting.

Records are compact (no candles, no arrays of prices): the shared event fields - scan id, timestamp, engine, git
commit, config hash and engine version - live once in the engine part's header and are joined back by expand().

Record keys
    a   canonical asset            d   disposition (taxonomy.DISPOSITIONS)     c   stable reason code
    st  stage that decided it      r   human reason                            o   observed input(s)
    th  threshold or rule          h   data health of the inputs               src data source
    k   venue contract ids         x   step codes (taxonomy.STEPS) noted on the way, optional
"""
from __future__ import annotations

from . import taxonomy as T


def _fmt(v):
    if isinstance(v, float):
        if v != v:
            return "nan"
        a = abs(v)
        if a >= 1e6:
            return f"{v / 1e6:.2f}M"
        if a >= 1e3:
            return f"{v / 1e3:.1f}k"
        return f"{v:.4g}"
    if isinstance(v, dict):
        return ", ".join(f"{k} {_fmt(x)}" for k, x in v.items())
    if isinstance(v, (list, tuple)):
        return "/".join(_fmt(x) for x in v)
    return str(v)


def render(code, o=None, th=None):
    s = T.describe(code)
    bits = []
    if o is not None:
        bits.append(f"observed {_fmt(o)}")
    if th is not None:
        bits.append(f"rule {_fmt(th)}")
    return s + (f" ({'; '.join(bits)})" if bits else "")


def _clean(v):
    """JSON-safe, compact observed values (floats rounded to 6 significant digits)."""
    if isinstance(v, float):
        return float(f"{v:.6g}") if v == v else None
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


class Ledger:
    def __init__(self, engine):
        self.engine = engine
        self.input = []           # assets the engine received, in order
        self._in = set()
        self.records = {}         # asset -> record
        self.duplicates = []      # assets given two final dispositions (an audit defect)
        self.problems = []        # audit consistency problems (an audit defect, legacy output unaffected)

    def expect(self, assets):
        for a in assets:
            if a not in self._in:
                self._in.add(a)
                self.input.append(a)

    def final(self, asset, code, stage, o=None, th=None, h=T.HEALTHY, src=None, k=None, x=None, r=None):
        d = T.disposition_of(code)
        if d is None:
            raise ValueError(f"{code} is a contract state, not a final disposition")
        if asset in self.records:
            self.duplicates.append([asset, code])
            return self.records[asset]
        rec = {"a": asset, "d": d, "c": code, "st": stage, "r": r or render(code, o, th)}
        if o is not None:
            rec["o"] = _clean(o)
        if th is not None:
            rec["th"] = _clean(th)
        rec["h"] = h
        if src:
            rec["src"] = src
        if k:
            rec["k"] = list(k)
        if x:
            rec["x"] = list(dict.fromkeys(x))
        self.records[asset] = rec
        return rec

    def note(self, asset, step):
        r = self.records.get(asset)
        if r is not None:
            xs = r.setdefault("x", [])
            if step not in xs:
                xs.append(step)

    def problem(self, msg):
        if len(self.problems) < 50:
            self.problems.append(str(msg)[:300])

    def coverage(self):
        by_d = {d: 0 for d in T.DISPOSITIONS}
        by_c = {}
        for r in self.records.values():
            by_d[r["d"]] += 1
            by_c[r["c"]] = by_c.get(r["c"], 0) + 1
        missing = [a for a in self.input if a not in self.records]
        extra = sorted(a for a in self.records if a not in self._in)
        return {"input": len(self.input), "disposed": len(self.records), "unaccounted": len(missing),
                "unaccounted_assets": missing[:50], "outside_input": extra[:50], "by_disposition": by_d,
                "by_reason": dict(sorted(by_c.items())), "duplicates": self.duplicates[:20],
                "unclassified": by_c.get("AUDIT_UNCLASSIFIED", 0)}

    def to_part(self):
        return {"engine": self.engine, "coverage": self.coverage(), "problems": self.problems,
                "records": [self.records[a] for a in sorted(self.records)]}


def expand(part, header):
    """Full events (every field of the provenance contract) from a compact engine part."""
    for r in part.get("records") or []:
        yield {"scan_id": header.get("scan_id"), "ts": header.get("ts"), "engine": part.get("engine"),
               "stage": r.get("st"), "asset": r.get("a"), "contracts": r.get("k") or [], "disposition": r.get("d"),
               "reason_code": r.get("c"), "reason": r.get("r"), "observed": r.get("o"), "rule": r.get("th"),
               "health": r.get("h"), "source": r.get("src"), "steps": r.get("x") or [],
               "git_sha": header.get("git_sha"), "config_hash": (header.get("config_hashes") or {}).get(
                   part.get("engine")), "engine_version": (header.get("engine_versions") or {}).get(part.get("engine"))}
