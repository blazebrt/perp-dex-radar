"""Universe identity (v8 Phase 2): contract-first classification and price-coherent exposures.

The single authority that turns the eight DEX market lists into the coin universe every engine reads
(scanner.build_universe() calls resolve(); quant and picks call build_universe()). It replaces the legacy step that
keyed everything by ticker and OR-ed the tradfi flag over every market of the ticker: one equity market listed
under a crypto ticker (QNT, PURR and BB on Extended) hid the crypto coin from every engine, even after the price check
had dropped that very market.

    raw venue contract (one adapter row, venue:raw_symbol)
      -> contract classification from the contract's own evidence (venue metadata, the contract's name)
      -> price-coherent exposures per ticker (prices per 1 coin: 1000PEPE and kPEPE compare as PEPE)
      -> exposure class CRYPTO / TRADFI / AMBIGUOUS
      -> the legacy coin record, built only from the admitted crypto exposure

Rules (deterministic; no statistics, no per-ticker exceptions):

1. Contract evidence. Extended category "RWA" (stocks, FX, commodities, indices) or a "_24_5" market: tradfi.
   Extended category "Crypto": crypto. Any other Extended category: ambiguous (the legacy rule called it tradfi).
   Aster underlyingType other than "COIN": tradfi; "COIN" is no evidence, because Aster sends "COIN" for the stocks
   it lists too (Phase 1 live audit). A contract name that matches the tradfi name pattern (Inc, Holdings, ETF, ...)
   is tradfi unless the ticker is on the known-crypto list, exactly as scanner.is_tradfi() ranks them. Tradfi and
   crypto evidence on one contract: ambiguous. Hyperliquid, Lighter, dYdX, Paradex and edgeX send no such metadata:
   their contracts are UNLABELED.
2. Exposures. The priced contracts of a ticker are grouped around anchors: the contract with the most 24h volume
   anchors the first exposure and takes every contract within 20% of its price (the legacy price-conflict
   tolerance); the most traded of the rest anchors the next, and so on. Contracts without a price never join a
   priced exposure and never change one: each stays on its own. A ticker with no priced contract at all is one
   exposure.
3. Exposure class. A ticker on the tradfi list or an FX pair: TRADFI (the legacy lists, unchanged). Otherwise from
   the contracts inside the exposure only: tradfi evidence and crypto evidence together: AMBIGUOUS; tradfi evidence:
   TRADFI, and its unlabeled contracts inherit it (a stock one venue forgot to label stays a stock); ambiguous
   evidence: AMBIGUOUS; crypto evidence: CRYPTO. Without any contract evidence: CRYPTO when the ticker is on the
   repository's known-crypto list (unchanged in this phase); AMBIGUOUS when another priced exposure of the same
   ticker is tradfi or ambiguous (a ticker that names a stock somewhere needs positive crypto evidence: this keeps a
   stock quoted in another currency on one venue, like XIAOMI, out); else CRYPTO by default, as before.
4. Admission. The CRYPTO exposures (priced, or the ticker's only exposure) are admitted. Unpriced contracts without
   tradfi or ambiguous evidence ride along with an admitted exposure, as they always did. The coin record is then
   built from the admitted contracts with the legacy steps unchanged: one market per venue (most volume), the price
   check against the most traded market, the reference price, the volumes. A ticker with nothing admitted keeps
   its legacy record of all contracts with tradfi=True, so every engine excludes it as before.

A ticker without tradfi evidence anywhere has every contract admitted, so its coin record is exactly the legacy
one. Volumes: an observed 0 now counts (best_vol, tot_vol, trade_vol are 0.0, not None); None means no venue
reported a volume (see v8.liquidity)."""
from __future__ import annotations

import statistics

VERSION = "v8.identity/1"
TOL = 0.2          # price tolerance of one exposure (the legacy price-conflict tolerance)

CRYPTO, TRADFI, AMBIGUOUS, UNLABELED = "CRYPTO", "TRADFI", "AMBIGUOUS", "UNLABELED"
CLASSES = (CRYPTO, TRADFI, AMBIGUOUS, UNLABELED)
# authority of a classification
VENUE_METADATA, CONTRACT_NAME, TICKER_LIST, INHERITED, DEFAULT, NONE = (
    "VENUE_METADATA", "CONTRACT_NAME", "TICKER_LIST", "INHERITED", "DEFAULT", "NONE")

# contract states in the universe (registry `legacy` field)
SELECTED, DUPLICATE, CONFLICT, NOT_ADMITTED = ("SELECTED", "DUPLICATE_NOT_SELECTED", "PRICE_CONFLICT_DROPPED",
                                              "EXPOSURE_NOT_ADMITTED")
# asset decisions
D_CRYPTO, D_SELECTED = "CRYPTO", "CRYPTO_EXPOSURE_SELECTED"
D_TRADFI, D_TRADFI_EXPOSURE, D_AMBIGUOUS = "TRADFI_CLASSIFIED", "TRADFI_EXPOSURE_EXCLUDED", "AMBIGUOUS_EXPOSURE"

EXTENDED_TRADFI_CATEGORIES = frozenset({"RWA"})
EXTENDED_CRYPTO_CATEGORIES = frozenset({"Crypto"})
ASTER_NEUTRAL_UNDERLYING = frozenset({"COIN"})
NAMED_VENUES = ("variational", "extended")     # the venues whose market name the legacy coin record keeps


class Lists:
    """The repository's ticker lists (scanner.TRADFI, KNOWN_CRYPTO, is_fx, TRADFI_NAME), passed in, never copied."""

    def __init__(self, tradfi, known_crypto, is_fx, name_re):
        self.tradfi, self.known_crypto, self.is_fx, self.name_re = tradfi, known_crypto, is_fx, name_re


# --------------------------------------------------------------------------- 1. one contract
def contract_evidence(row, lists):
    """[(class, reason, authority), ...]: what the contract itself says, strongest first."""
    t, dex = row.get("t"), row.get("dex")
    ev = []
    if dex == "extended":
        cat = row.get("category")
        if "_24_5" in str(row.get("sym") or ""):
            ev.append((TRADFI, "VENUE_24_5_MARKET", VENUE_METADATA))
        if cat:
            if cat in EXTENDED_TRADFI_CATEGORIES:
                ev.append((TRADFI, f"VENUE_CATEGORY:{cat}", VENUE_METADATA))
            elif cat in EXTENDED_CRYPTO_CATEGORIES:
                ev.append((CRYPTO, f"VENUE_CATEGORY:{cat}", VENUE_METADATA))
            else:
                ev.append((AMBIGUOUS, f"VENUE_CATEGORY_UNRECOGNIZED:{cat}", VENUE_METADATA))
    elif dex == "aster":
        ut = row.get("underlying")
        if ut and ut not in ASTER_NEUTRAL_UNDERLYING:
            ev.append((TRADFI, f"VENUE_UNDERLYING:{ut}", VENUE_METADATA))
    name = row.get("name")
    if name and t not in lists.known_crypto:
        m = lists.name_re.search(str(name))
        if m:
            ev.append((TRADFI, "NAME_PATTERN:" + m.group(0).lower(), CONTRACT_NAME))
    return ev


def classify_contract(row, lists):
    """(class, reason, authority) of one contract from its own evidence; UNLABELED when it carries none."""
    ev = contract_evidence(row, lists)
    if not ev:
        return UNLABELED, "NO_CONTRACT_EVIDENCE", NONE
    kinds = {c for c, _, _ in ev}
    if TRADFI in kinds and CRYPTO in kinds:
        return AMBIGUOUS, "CONFLICTING_CONTRACT_EVIDENCE:" + "+".join(w for _, w, _ in ev), VENUE_METADATA
    for want in (TRADFI, AMBIGUOUS, CRYPTO):
        for c, w, a in ev:
            if c == want:
                return c, w, a
    return UNLABELED, "NO_CONTRACT_EVIDENCE", NONE   # not reached


def ticker_class(t, lists):
    """(class, reason) from the repository's ticker lists, or (None, None)."""
    if t in lists.tradfi:
        return TRADFI, "TICKER_TRADFI_LIST"
    if lists.is_fx(t):
        return TRADFI, "TICKER_FX_PAIR"
    if t in lists.known_crypto:
        return CRYPTO, "TICKER_KNOWN_CRYPTO"
    return None, None


# --------------------------------------------------------------------------- 2. exposures of one ticker
class Member:
    __slots__ = ("dex", "i", "row", "cls", "why", "auth", "npx", "vol")

    def __init__(self, dex, i, row, lists):
        self.dex, self.i, self.row = dex, i, row
        self.cls, self.why, self.auth = classify_contract(row, lists)
        p, m = row.get("price"), row.get("mult") or 1.0
        self.npx = p / m if p else None          # price per 1 coin; legacy `if v.get("price")`
        self.vol = row.get("vol") or 0


class Exposure:
    __slots__ = ("id", "members", "anchor", "priced", "single", "cls", "why", "auth", "admitted", "attached")

    def __init__(self, xid, members, anchor, priced, single=False):
        self.id, self.members, self.anchor, self.priced, self.single = xid, members, anchor, priced, single
        self.cls = self.why = self.auth = None
        self.admitted = self.attached = False

    def evidence(self):
        return {m.cls for m in self.members}


def group(t, members):
    """Price-coherent exposures of one ticker, deterministic: anchors by volume (first in market-list order on a
    tie), every priced contract within TOL of its anchor's price, unpriced contracts each on their own."""
    priced = [m for m in members if m.npx]
    out = []
    if not priced:
        return [Exposure(f"{t}#1", list(members), None, priced=False)]
    rest, k = list(priced), 0
    while rest:
        k += 1
        anchor = max(rest, key=lambda m: m.vol)
        mem = [m for m in rest if abs(m.npx / anchor.npx - 1) <= TOL]
        out.append(Exposure(f"{t}#{k}", mem, anchor, priced=True))
        taken = {id(m) for m in mem}
        rest = [m for m in rest if id(m) not in taken]
    for j, m in enumerate((m for m in members if not m.npx), 1):
        out.append(Exposure(f"{t}#u{j}", [m], None, priced=False, single=True))
    return out


def classify_exposures(t, exps, lists):
    """Sets cls/why/auth of every exposure of ticker t (rules 3 and 4 of the module docstring)."""
    tcls, twhy = ticker_class(t, lists)
    pending = []
    for g in exps:
        ev = g.evidence()
        if tcls == TRADFI:     # the repository's tradfi list or an FX pair settles the whole ticker
            g.cls, g.why, g.auth = TRADFI, twhy, TICKER_LIST
        elif TRADFI in ev and CRYPTO in ev:
            g.cls, g.why, g.auth = AMBIGUOUS, "CONFLICTING_CONTRACT_EVIDENCE", VENUE_METADATA
        elif TRADFI in ev:
            g.cls, g.why, g.auth = TRADFI, "TRADFI_CONTRACT_EVIDENCE", _auth(g, TRADFI)
        elif AMBIGUOUS in ev:
            g.cls, g.why, g.auth = AMBIGUOUS, "AMBIGUOUS_CONTRACT_EVIDENCE", VENUE_METADATA
        elif CRYPTO in ev:
            g.cls, g.why, g.auth = CRYPTO, "CRYPTO_VENUE_METADATA", VENUE_METADATA
        elif g.single:
            g.cls, g.why, g.auth = UNLABELED, "UNPRICED_NO_CONTRACT_EVIDENCE", NONE
        else:
            pending.append(g)
    # unpriced single contracts never count: a contract without a price cannot redefine another exposure
    collision = any(g.cls in (TRADFI, AMBIGUOUS) for g in exps if not g.single)
    for g in pending:
        if tcls == CRYPTO:
            g.cls, g.why, g.auth = CRYPTO, twhy, TICKER_LIST
        elif collision:
            g.cls, g.why, g.auth = AMBIGUOUS, "UNLABELED_UNDER_TRADFI_COLLISION", NONE
        else:
            g.cls, g.why, g.auth = CRYPTO, "DEFAULT_CRYPTO", DEFAULT
    return exps


def _auth(g, cls):
    auths = [m.auth for m in g.members if m.cls == cls]
    return VENUE_METADATA if VENUE_METADATA in auths else (auths[0] if auths else NONE)


# --------------------------------------------------------------------------- 3. the legacy coin record
def _median(xs, default=0.0):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else default


def merge(t, members, in_my_dexes, on_conflict=None):
    """The legacy coin record from the given contracts (market-list order): one market per venue (most volume, the
    first on a tie), the price check against the most traded market, the reference price and the volumes.

    Returns (coin, picked {dex: row}, popped {dex}). Identical to the legacy build_universe() steps except that an
    observed 0 volume counts in best_vol / tot_vol / trade_vol (None only when no venue reported a volume)."""
    c = {"t": t, "venues": {}, "name": None, "tradfi": False}
    for m in members:
        r, dex = m.row, m.dex
        old = c["venues"].get(dex)
        if old is None or (r.get("vol") or 0) > (old.get("vol") or 0):
            c["venues"][dex] = r
        if r.get("name") and not c["name"] and dex in NAMED_VENUES:
            c["name"] = r["name"]
    picked, popped = dict(c["venues"]), set()
    priced = [(dex, v["price"] / v["mult"], v.get("vol") or 0) for dex, v in c["venues"].items() if v.get("price")]
    ref = None
    if priced:
        # anchor on the most traded venue; a venue far from it lists a different asset under this ticker
        anchor = max(priced, key=lambda x: x[2])
        ref = anchor[1] if anchor[2] > 0 else _median([p for _, p, _ in priced], None)
        if len(priced) >= 2:
            for dex, p, _ in priced:
                if abs(p / ref - 1) > TOL:
                    if on_conflict is not None:
                        on_conflict(t, dex, p, ref)
                    c["venues"].pop(dex, None)
                    popped.add(dex)
            ref = _median([v["price"] / v["mult"] for v in c["venues"].values() if v.get("price")], ref)
    c["ref_price"] = ref
    vols = [v["vol"] for v in c["venues"].values() if v.get("vol") is not None]
    c["best_vol"] = max(vols) if vols else None
    c["tot_vol"] = sum(vols) if vols else None
    mine = [v["vol"] for d, v in c["venues"].items() if v.get("vol") is not None and in_my_dexes(d)]
    c["trade_vol"] = max(mine) if mine else None
    return c, picked, popped


# --------------------------------------------------------------------------- 4. the universe
class Resolution:
    """What resolve() decided, for the engines (coins) and for the audit (everything else)."""

    def __init__(self):
        self.coins = {}          # ticker -> legacy coin record (tradfi=True when nothing was admitted)
        self.rows = {}           # (dex, row index) -> per-contract identity (see _row_info)
        self.assets = {}         # ticker -> decision and exposures
        self.crypto_rows = {}    # dex -> adapter rows whose exposure was admitted to the crypto universe

    def asset(self, t):
        return self.assets.get(t)


def resolve(results, dexes, lists, in_my_dexes, on_conflict=None):
    """results: {dex: adapter rows or None (the adapter failed)}. Returns a Resolution; .coins is the legacy coin
    dict in the legacy order (first appearance of each ticker in market-list order)."""
    res = Resolution()
    by_t = {}
    for dex in dexes:
        rows = results.get(dex)
        if rows is None:
            continue
        res.crypto_rows[dex] = 0
        for i, r in enumerate(rows):
            by_t.setdefault(r["t"], []).append(Member(dex, i, r, lists))
    for t, members in by_t.items():
        exps = classify_exposures(t, group(t, members), lists)
        lead = [g for g in exps if not g.single]
        admit = [g for g in lead if g.cls == CRYPTO]
        for g in admit:
            g.admitted = True
        if admit:
            for g in exps:
                if g.single and g.cls in (CRYPTO, UNLABELED):
                    g.attached = True
        chosen = {id(m) for g in exps if g.admitted or g.attached for m in g.members}
        if chosen:
            use = [m for m in members if id(m) in chosen]
            coin, picked, popped = merge(t, use, in_my_dexes, on_conflict)
        else:
            use = members
            coin, picked, popped = merge(t, use, in_my_dexes, on_conflict)
            coin["tradfi"] = True
        in_merge = {id(m) for m in use}
        if coin["venues"]:
            res.coins[t] = coin
        for g in exps:
            for m in g.members:
                if id(m) not in in_merge:
                    state = NOT_ADMITTED
                elif picked.get(m.dex) is not m.row:
                    state = DUPLICATE
                elif m.dex in popped:
                    state = CONFLICT
                else:
                    state = SELECTED
                res.rows[(m.dex, m.i)] = _row_info(m, g, state, exps)
                if g.admitted or g.attached:
                    res.crypto_rows[m.dex] = res.crypto_rows.get(m.dex, 0) + 1
        res.assets[t] = _asset_info(t, exps, bool(chosen), lists)
        res.assets[t]["phase1_tradfi"] = _phase1_tradfi(t, members, lists)
    return res


def _phase1_tradfi(t, members, lists):
    """What the Phase 1 (legacy) universe decided for this ticker, for the audit's before/after only: the adapter
    label OR-ed over every market, then the ticker lists and the name of the first Variational/Extended market."""
    if any(m.row.get("tradfi") for m in members):
        return True
    name = next((m.row.get("name") for m in members if m.row.get("name") and m.dex in NAMED_VENUES), None)
    if t in lists.tradfi or lists.is_fx(t):
        return True
    if t in lists.known_crypto:
        return False
    return bool(name and lists.name_re.search(str(name)))


def _row_info(m, g, state, exps):
    inherited = None
    if g.cls == TRADFI and m.cls in (UNLABELED,) and g.auth != TICKER_LIST:
        src = next((x for x in g.members if x.cls == TRADFI), None)
        inherited = f"{src.dex}:{src.row.get('sym')}" if src is not None else None
    return {"cls": m.cls, "why": m.why, "auth": m.auth, "npx": m.npx, "exp": g.id, "exp_cls": g.cls,
            "exp_why": g.why, "admitted": bool(g.admitted or g.attached), "inherited_from": inherited, "state": state,
            "meta": _meta(m.row)}


def _meta(row):
    out = {}
    for k in ("underlying", "category"):
        if row.get(k) is not None:
            out[k] = row.get(k)
    return out or None


def _asset_info(t, exps, admitted, lists):
    lead = [g for g in exps if not g.single]
    tcls, twhy = ticker_class(t, lists)
    if admitted:
        excluded = [g for g in exps if not (g.admitted or g.attached)]
        decision = D_SELECTED if excluded else D_CRYPTO
    elif any(g.cls == AMBIGUOUS for g in lead):
        decision = D_AMBIGUOUS
    elif any(g.auth != TICKER_LIST and any(m.cls != TRADFI for m in g.members) for g in lead):
        decision = D_TRADFI_EXPOSURE      # a contract without tradfi evidence of its own inherited it
    else:
        decision = D_TRADFI
    out = []
    for g in exps:
        px = [m.npx for m in g.members if m.npx]
        out.append({"id": g.id, "class": g.cls, "reason": g.why, "authority": g.auth, "priced": g.priced,
                    "anchor": f"{g.anchor.dex}:{g.anchor.row.get('sym')}" if g.anchor is not None else None,
                    "anchor_price": _r(g.anchor.npx) if g.anchor is not None else None,
                    "price_range": [_r(min(px)), _r(max(px))] if px else None,
                    "members": [f"{m.dex}:{m.row.get('sym')}" for m in g.members],
                    "admitted": bool(g.admitted), "attached": bool(g.attached)})
    # a ticker collision: the ticker's own contracts disagree (some carry tradfi or ambiguous evidence, others do
    # not) and no ticker list settles it for the whole ticker
    labels = {m.cls for g in exps for m in g.members}
    collision = tcls != TRADFI and bool(labels & {TRADFI, AMBIGUOUS}) and bool(labels & {UNLABELED, CRYPTO})
    return {"decision": decision, "admitted": admitted, "exposures": out, "collision": collision,
            "ticker_list": twhy}


def _r(x, nd=8):
    if x is None:
        return None
    return float(f"{float(x):.{nd}g}")
