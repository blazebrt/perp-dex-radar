"""Universe identity (v8 Phase 2, hardened in Phase 3): contract-first classification, price-coherent exposures and
four explicit identity states.

The single authority that turns the eight DEX market lists into the coin universe every engine reads
(scanner.build_universe() calls resolve(); quant and picks call build_universe()), and the single place that says
which coins may reach a crypto engine (execution_identity_eligible()).

    raw venue contract (one adapter row, venue:raw_symbol)
      -> contract evidence from the contract's own metadata, name and venue symbol
      -> price-coherent exposures per ticker (prices per 1 coin: 1000PEPE and kPEPE compare as PEPE)
      -> exposure class CRYPTO / TRADFI / AMBIGUOUS / UNVERIFIED
      -> asset identity state VERIFIED_CRYPTO / VERIFIED_TRADFI / AMBIGUOUS / UNVERIFIED
      -> the legacy coin record (identity field set), built from the deciding exposure only

Phase 3 retires the implicit rule "no tradfi evidence and no crypto evidence = crypto" (Phase 2's DEFAULT_CRYPTO).
An exposure without positive evidence is UNVERIFIED: it stays in the universe (discovery: the coin record, the
registry, the audit, every engine's ledger), it is not called tradfi, and it has no crypto execution authority.

Rules (deterministic; no statistics, no per-ticker exceptions, no network):

1. Contract evidence.
   Venue metadata: Extended category "RWA" or a "_24_5" market: tradfi; Extended category "Crypto": crypto; any other
   Extended category: ambiguous. Aster underlyingType other than "COIN": tradfi; "COIN" is no evidence (Aster sends
   it for the stocks it lists too). Hyperliquid, Lighter, dYdX, Paradex, edgeX and Variational send no asset-class
   field.
   Contract name: a name matching the tradfi name pattern (Inc, Holdings, ETF, ...) is tradfi unless the ticker is
   on the known-crypto list (the precedence of scanner.is_tradfi()).
   Venue fields (Phase 3, tradfi direction only, chosen from the live venue field census): an Aster underlyingSubType
   in ASTER_TRADFI_SUBTYPES (STOCK, ETF, Commodities, Semiconductor, USD1-RWA); a Variational market name starting
   "Swap on " (ticker not known crypto).
   Venue symbol (Phase 3): on venues whose market symbols name the base asset only (BASE_ONLY_SYMBOL_VENUES; the
   quote is the venue's settlement currency and is never written), a symbol ending in a quote code
   (QUOTE_SUFFIXES) yields a parsed underlying candidate: SAMSUNGUSD -> SAMSUNG. The candidate never changes the
   contract's ticker. It is evidence in one direction only, tradfi: when the candidate is on the repository's tradfi
   list or an FX code pair, or (rule 3) when the candidate ticker has a TRADFI exposure at a coherent price. It is
   never crypto evidence: a parsed name is not enough to grant execution authority.
   Tradfi and crypto evidence on one contract: ambiguous. No evidence: the contract is UNLABELED.
2. Exposures. The priced contracts of a ticker are grouped around anchors: the contract with the most 24h volume
   anchors the first exposure and takes every contract within 20% of its price (the legacy price-conflict
   tolerance); the most traded of the rest anchors the next, and so on. Contracts without a price never join a
   priced exposure and never change one: each stays on its own. A ticker with no priced contract is one exposure.
3. Parsed-symbol links (one hop, after every ticker is classified on its own contracts): a contract whose parsed
   candidate is another ticker of this scan, and whose price per coin is within 20% of a TRADFI exposure of that
   ticker, gains tradfi evidence (PARSED_SYMBOL_EXPOSURE). Every link found is recorded, also when it decides
   nothing (HYUNDAIUSD -> HYUNDAI, both unverified). Tickers that gained evidence are classified again; the links
   are not followed further.
4. Exposure class. A ticker on the tradfi list or an FX pair: TRADFI (unchanged legacy lists). Otherwise from the
   contracts inside the exposure only: tradfi and crypto evidence together: AMBIGUOUS; tradfi evidence: TRADFI, and
   its unlabeled contracts inherit it; ambiguous evidence: AMBIGUOUS; crypto evidence: CRYPTO. Without contract
   evidence: CRYPTO when the ticker is on the repository's known-crypto list; AMBIGUOUS when another priced exposure
   of the ticker is tradfi or ambiguous; else UNVERIFIED (Phase 2: CRYPTO by default). An unpriced contract alone
   with no evidence: UNVERIFIED.
5. Asset state and the coin record. Any CRYPTO exposure: VERIFIED_CRYPTO; the CRYPTO exposures are admitted and the
   coin record is built from them (plus unpriced contracts without tradfi or ambiguous evidence, as before);
   price-separated UNVERIFIED exposures of the ticker stay out. Else any UNVERIFIED exposure: UNVERIFIED; the coin
   record is built from the UNVERIFIED exposures exactly as Phase 2 built it (same venues, prices, volumes), with
   tradfi=False and identity UNVERIFIED. Else (only TRADFI / AMBIGUOUS): VERIFIED_TRADFI or AMBIGUOUS, the legacy
   record of all contracts with tradfi=True, as in Phase 2. Every coin record carries `identity` (the state).

Discovery is not execution: every coin record is in the universe whatever its state (discovery_eligible()); only
VERIFIED_CRYPTO may reach a crypto engine (execution_identity_eligible()), and a coin record without an identity
fails closed. Liquidity, history and strategy gates are separate and unchanged.

Volumes: an observed 0 counts (best_vol, tot_vol, trade_vol are 0.0, not None); None means no venue reported one."""
from __future__ import annotations

import statistics

VERSION = "v8.identity/2"
TOL = 0.2          # price tolerance of one exposure (the legacy price-conflict tolerance)

# contract classes (a contract's own evidence) and exposure classes
CRYPTO, TRADFI, AMBIGUOUS, UNLABELED, UNVERIFIED = "CRYPTO", "TRADFI", "AMBIGUOUS", "UNLABELED", "UNVERIFIED"
CLASSES = (CRYPTO, TRADFI, AMBIGUOUS, UNLABELED, UNVERIFIED)
# asset identity states (v8 Phase 3)
VERIFIED_CRYPTO, VERIFIED_TRADFI = "VERIFIED_CRYPTO", "VERIFIED_TRADFI"
STATES = (VERIFIED_CRYPTO, VERIFIED_TRADFI, AMBIGUOUS, UNVERIFIED)
STATE_OF = {CRYPTO: VERIFIED_CRYPTO, TRADFI: VERIFIED_TRADFI, AMBIGUOUS: AMBIGUOUS, UNVERIFIED: UNVERIFIED}
# authority of a classification. DEFAULT is Phase 2's "crypto because nothing said otherwise": retired in Phase 3,
# kept so older snapshots stay readable; never emitted.
VENUE_METADATA, CONTRACT_NAME, TICKER_LIST, PARSED_SYMBOL, INHERITED, DEFAULT, NONE = (
    "VENUE_METADATA", "CONTRACT_NAME", "TICKER_LIST", "PARSED_SYMBOL", "INHERITED", "DEFAULT", "NONE")

# contract states in the universe (registry `legacy` field)
SELECTED, DUPLICATE, CONFLICT, NOT_ADMITTED = ("SELECTED", "DUPLICATE_NOT_SELECTED", "PRICE_CONFLICT_DROPPED",
                                              "EXPOSURE_NOT_ADMITTED")
NOT_ADMITTED_UNVERIFIED = "UNVERIFIED_EXPOSURE_NOT_ADMITTED"      # v8 Phase 3
KEPT_STATES = (SELECTED, DUPLICATE, CONFLICT, NOT_ADMITTED, NOT_ADMITTED_UNVERIFIED)
# asset decisions
D_CRYPTO, D_SELECTED = "CRYPTO", "CRYPTO_EXPOSURE_SELECTED"
D_TRADFI, D_TRADFI_EXPOSURE, D_AMBIGUOUS = "TRADFI_CLASSIFIED", "TRADFI_EXPOSURE_EXCLUDED", "AMBIGUOUS_EXPOSURE"
D_UNVERIFIED = "IDENTITY_UNVERIFIED"
STATE_OF_DECISION = {D_CRYPTO: VERIFIED_CRYPTO, D_SELECTED: VERIFIED_CRYPTO, D_TRADFI: VERIFIED_TRADFI,
                     D_TRADFI_EXPOSURE: VERIFIED_TRADFI, D_AMBIGUOUS: AMBIGUOUS, D_UNVERIFIED: UNVERIFIED}

EXTENDED_TRADFI_CATEGORIES = frozenset({"RWA"})
EXTENDED_CRYPTO_CATEGORIES = frozenset({"Crypto"})
ASTER_NEUTRAL_UNDERLYING = frozenset({"COIN"})
# Phase 3, from the venue field census of the exact-head live scan gh-37782095629-1 (2,016 active perps): Aster
# underlyingSubType values that were never on a market of a verified crypto exposure (STOCK: 98 tradfi, 19 unverified
# or ambiguous, 0 crypto; ETF, Commodities, Semiconductor, USD1-RWA: 54 tradfi, 8 unverified, 0 crypto). Tradfi
# evidence only. The crypto-looking values (Top, Meme, AI) are recorded, never evidence: Meme was on a tradfi market.
ASTER_TRADFI_SUBTYPES = frozenset({"STOCK", "ETF", "Commodities", "Semiconductor", "USD1-RWA"})
# Variational names its tradfi swaps "Swap on <underlying>" (9 tradfi, 4 unverified, 0 crypto in the same census)
VARIATIONAL_TRADFI_NAME_PREFIX = "swap on "
NAMED_VENUES = ("variational", "extended")     # the venues whose market name the legacy coin record keeps
# venues whose market symbol names the base asset only; the quote (the venue's settlement currency) is never part
# of the symbol (Hyperliquid "BTC", Lighter "ETH", Variational "SOL"), so a trailing quote code is a lead to parse
BASE_ONLY_SYMBOL_VENUES = ("hyperliquid", "lighter", "variational")
QUOTE_SUFFIXES = ("USD",)
MIN_CANDIDATE_LEN = 2
PROMOTION = ("positive identity evidence on a price-coherent contract: a venue asset-class label (Extended "
             "category, Aster underlyingType), the repository's known-crypto or tradfi list, a tradfi contract name, "
             "or a verified tradfi exposure linked by the venue symbol")


class Lists:
    """The repository's ticker lists (scanner.TRADFI, KNOWN_CRYPTO, is_fx, TRADFI_NAME), passed in, never copied."""

    def __init__(self, tradfi, known_crypto, is_fx, name_re):
        self.tradfi, self.known_crypto, self.is_fx, self.name_re = tradfi, known_crypto, is_fx, name_re


# --------------------------------------------------------------------------- engines: discovery vs execution
def execution_identity_eligible(coin):
    """True only for a coin record whose identity is VERIFIED_CRYPTO (and that is not excluded as tradfi). The gate
    every crypto engine applies before it evaluates a coin. A coin record without an identity fails closed."""
    return bool(coin) and not coin.get("tradfi") and coin.get("identity") == VERIFIED_CRYPTO


def discovery_eligible(coin):
    """True for every coin record with at least one venue market, whatever its identity state: the system sees it."""
    return bool(coin) and bool(coin.get("venues"))


# --------------------------------------------------------------------------- 1. one contract
def parse_symbol(dex, t):
    """(candidate, rule) for the ticker of a contract on a base-only-symbol venue whose ticker ends in a quote code,
    else (None, None). SAMSUNGUSD on Lighter -> ("SAMSUNG", "QUOTE_SUFFIX:USD"). A lead only (see rules 1 and 3)."""
    if dex not in BASE_ONLY_SYMBOL_VENUES or not t:
        return None, None
    u = str(t)
    for q in QUOTE_SUFFIXES:
        if u.endswith(q) and len(u) - len(q) >= MIN_CANDIDATE_LEN:
            return u[:-len(q)], f"QUOTE_SUFFIX:{q}"
    return None, None


def contract_evidence(row, lists, dex=None):
    """[(class, reason, authority), ...]: what the contract itself says (Phase 2 evidence, then the Phase 3 venue
    field and parsed-symbol evidence)."""
    return base_evidence(row, lists) + venue_field_evidence(row, lists) + parsed_evidence(row, lists, dex)


def base_evidence(row, lists):
    """The Phase 2 evidence of one contract: venue metadata and the contract name."""
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


def venue_field_evidence(row, lists):
    """Phase 3: tradfi evidence from same-venue fields the census showed to be reliable in that direction: an Aster
    underlyingSubType in ASTER_TRADFI_SUBTYPES, a Variational name "Swap on ..." (ticker not known crypto, the
    precedence of the name rule)."""
    dex, t = row.get("dex"), row.get("t")
    ev = []
    if dex == "aster":
        hit = sorted(set(row.get("subtypes") or ()) & ASTER_TRADFI_SUBTYPES)
        if hit:
            ev.append((TRADFI, "VENUE_SUBTYPE:" + "+".join(hit), VENUE_METADATA))
    elif dex == "variational":
        name = str(row.get("name") or "")
        if name.lower().startswith(VARIATIONAL_TRADFI_NAME_PREFIX) and t not in lists.known_crypto:
            ev.append((TRADFI, "VENUE_NAME:swap on", CONTRACT_NAME))
    return ev


def parsed_evidence(row, lists, dex=None):
    """Phase 3: tradfi evidence from a parsed venue symbol whose candidate is on the tradfi list or an FX pair."""
    t = row.get("t")
    cand, _ = parse_symbol(dex or row.get("dex"), t)
    if not cand or t in lists.known_crypto:
        return []
    if cand in lists.tradfi:
        return [(TRADFI, f"PARSED_SYMBOL_TRADFI_LIST:{cand}", PARSED_SYMBOL)]
    if lists.is_fx(cand):
        return [(TRADFI, f"PARSED_SYMBOL_FX_PAIR:{cand}", PARSED_SYMBOL)]
    return []


def classify_evidence(ev):
    """(class, reason, authority) of one contract from its evidence list; UNLABELED when there is none."""
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


def classify_contract(row, lists):
    """(class, reason, authority) of one contract from its own evidence; UNLABELED when it carries none."""
    return classify_evidence(contract_evidence(row, lists))


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
    __slots__ = ("dex", "i", "row", "ev2", "ev", "cls", "why", "auth", "cls2", "npx", "vol", "cand", "cand_rule",
                 "link")

    def __init__(self, dex, i, row, lists):
        self.dex, self.i, self.row = dex, i, row
        self.ev2 = base_evidence(row, lists)                     # what Phase 2 knew
        self.ev = self.ev2 + venue_field_evidence(row, lists) + parsed_evidence(row, lists, dex)   # Phase 3
        self.cls, self.why, self.auth = classify_evidence(self.ev)
        self.cls2 = classify_evidence(self.ev2)[0]
        p, m = row.get("price"), row.get("mult") or 1.0
        self.npx = p / m if p else None          # price per 1 coin; legacy `if v.get("price")`
        self.vol = row.get("vol") or 0
        self.cand, self.cand_rule = parse_symbol(dex, row.get("t"))
        self.link = None

    def add(self, cls, why, auth):
        self.ev.append((cls, why, auth))
        self.cls, self.why, self.auth = classify_evidence(self.ev)

    @property
    def cid(self):
        return f"{self.dex}:{self.row.get('sym')}"


class Exposure:
    __slots__ = ("id", "members", "anchor", "priced", "single", "cls", "why", "auth", "admitted", "attached",
                 "recorded")

    def __init__(self, xid, members, anchor, priced, single=False):
        self.id, self.members, self.anchor, self.priced, self.single = xid, members, anchor, priced, single
        self.cls = self.why = self.auth = None
        self.admitted = self.attached = self.recorded = False

    def evidence(self, phase2=False):
        return {(m.cls2 if phase2 else m.cls) for m in self.members}


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


def classify_exposures(t, exps, lists, phase2=False):
    """Sets cls/why/auth of every exposure of ticker t (rule 4 of the module docstring). phase2=True classifies as
    Phase 2 did (no parsed-symbol evidence; no evidence = CRYPTO by default), for the before/after only."""
    tcls, twhy = ticker_class(t, lists)
    pending = []
    for g in exps:
        ev = g.evidence(phase2)
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
            g.cls, g.why, g.auth = (UNLABELED if phase2 else UNVERIFIED), "UNPRICED_NO_CONTRACT_EVIDENCE", NONE
        else:
            pending.append(g)
    # unpriced single contracts never count: a contract without a price cannot redefine another exposure
    collision = any(g.cls in (TRADFI, AMBIGUOUS) for g in exps if not g.single)
    for g in pending:
        if tcls == CRYPTO:
            g.cls, g.why, g.auth = CRYPTO, twhy, TICKER_LIST
        elif collision:
            g.cls, g.why, g.auth = AMBIGUOUS, "UNLABELED_UNDER_TRADFI_COLLISION", NONE
        elif phase2:
            g.cls, g.why, g.auth = CRYPTO, "DEFAULT_CRYPTO", DEFAULT
        else:
            g.cls, g.why, g.auth = UNVERIFIED, "NO_POSITIVE_IDENTITY_EVIDENCE", NONE
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
        self.coins = {}          # ticker -> legacy coin record with its identity state
        self.rows = {}           # (dex, row index) -> per-contract identity (see _row_info)
        self.assets = {}         # ticker -> decision, state, evidence and exposures
        self.crypto_rows = {}    # dex -> adapter rows whose exposure was admitted to the crypto universe

    def asset(self, t):
        return self.assets.get(t)


def link_symbols(by_t, exps_of, lists):
    """Rule 3: parsed-symbol links, one hop. Records every link on its contract; returns the tickers that gained
    tradfi evidence (they are classified again by the caller)."""
    changed = set()
    for t, members in by_t.items():
        for m in members:
            c = m.cand
            if not c or c == t or c not in exps_of:
                continue
            cands = [g2 for g2 in exps_of[c] if not g2.single and g2.anchor is not None]
            hit = next((g2 for g2 in cands if m.npx and abs(m.npx / g2.anchor.npx - 1) <= TOL), None)
            m.link = {"candidate": c, "rule": m.cand_rule,
                      "exposures": [[g2.id, g2.cls, _r(g2.anchor.npx)] for g2 in cands],
                      "coherent_exposure": hit.id if hit is not None else None,
                      "coherent_class": hit.cls if hit is not None else None, "evidence": None}
            if hit is not None and hit.cls == TRADFI and t not in lists.known_crypto:
                why = f"PARSED_SYMBOL_EXPOSURE:{hit.id}"
                m.add(TRADFI, why, PARSED_SYMBOL)
                m.link["evidence"] = why
                changed.add(t)
    return changed


def resolve(results, dexes, lists, in_my_dexes, on_conflict=None):
    """results: {dex: adapter rows or None (the adapter failed)}. Returns a Resolution; .coins is the legacy coin
    dict in the legacy order (first appearance of each ticker in market-list order), each with `identity`."""
    res = Resolution()
    by_t = {}
    for dex in dexes:
        rows = results.get(dex)
        if rows is None:
            continue
        res.crypto_rows[dex] = 0
        for i, r in enumerate(rows):
            by_t.setdefault(r["t"], []).append(Member(dex, i, r, lists))
    exps_of = {t: classify_exposures(t, group(t, ms), lists) for t, ms in by_t.items()}
    for t in link_symbols(by_t, exps_of, lists):
        exps_of[t] = classify_exposures(t, group(t, by_t[t]), lists)
    for t, members in by_t.items():
        exps = exps_of[t]
        lead = [g for g in exps if not g.single]
        admit = [g for g in lead if g.cls == CRYPTO]
        unver = [g for g in lead if g.cls == UNVERIFIED]
        if admit:
            state = VERIFIED_CRYPTO
            for g in admit:
                g.admitted = True
            core = admit
        elif unver:
            state = UNVERIFIED
            for g in unver:
                g.recorded = True
            core = unver
        else:
            state, core = None, []
        if core:
            for g in exps:
                if g.single and g.cls in (CRYPTO, UNVERIFIED):
                    g.attached = True
        chosen = {id(m) for g in exps if g.admitted or g.recorded or g.attached for m in g.members}
        if chosen:
            use = [m for m in members if id(m) in chosen]
            coin, picked, popped = merge(t, use, in_my_dexes, on_conflict)
        else:
            use = members
            coin, picked, popped = merge(t, use, in_my_dexes, on_conflict)
            coin["tradfi"] = True
        info = _asset_info(t, members, exps, state, lists)
        coin["identity"] = info["state"]
        in_merge = {id(m) for m in use}
        if coin["venues"]:
            res.coins[t] = coin
        for g in exps:
            for m in g.members:
                if id(m) not in in_merge:
                    st = NOT_ADMITTED_UNVERIFIED if g.cls == UNVERIFIED else NOT_ADMITTED
                elif picked.get(m.dex) is not m.row:
                    st = DUPLICATE
                elif m.dex in popped:
                    st = CONFLICT
                else:
                    st = SELECTED
                res.rows[(m.dex, m.i)] = _row_info(m, g, st, info["state"])
                if res.rows[(m.dex, m.i)]["admitted"]:
                    res.crypto_rows[m.dex] = res.crypto_rows.get(m.dex, 0) + 1
        info["phase1_tradfi"] = _phase1_tradfi(t, members, lists)
        info["phase2"] = _phase2(t, members, lists)
        res.assets[t] = info
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


def _phase2(t, members, lists):
    """What the Phase 2 identity decided for this ticker on the same contracts, for the audit's before/after only:
    {"state": CRYPTO / TRADFI / AMBIGUOUS, "reasons": the admitted exposures' reasons}. Phase 2 had no parsed-symbol
    evidence and admitted an exposure without evidence as CRYPTO by default."""
    exps = classify_exposures(t, group(t, members), lists, phase2=True)
    lead = [g for g in exps if not g.single]
    admit = [g for g in lead if g.cls == CRYPTO]
    if admit:
        return {"state": "CRYPTO", "reasons": sorted({g.why for g in admit})}
    if any(g.cls == AMBIGUOUS for g in lead):
        return {"state": "AMBIGUOUS", "reasons": sorted({g.why for g in lead if g.cls == AMBIGUOUS})}
    return {"state": "TRADFI", "reasons": sorted({g.why for g in lead if g.cls == TRADFI})}


def _row_info(m, g, state, asset_state):
    inherited = None
    if g.cls == TRADFI and m.cls in (UNLABELED,) and g.auth != TICKER_LIST:
        src = next((x for x in g.members if x.cls == TRADFI), None)
        inherited = f"{src.dex}:{src.row.get('sym')}" if src is not None else None
    in_record = bool(g.admitted or g.recorded or g.attached)
    return {"cls": m.cls, "why": m.why, "auth": m.auth, "npx": m.npx, "exp": g.id, "exp_cls": g.cls,
            "exp_why": g.why, "exp_state": STATE_OF.get(g.cls),
            "admitted": in_record and asset_state == VERIFIED_CRYPTO, "in_record": in_record,
            "inherited_from": inherited, "state": state, "meta": _meta(m.row),
            "evidence": [[c, w, a] for c, w, a in m.ev] or None,
            "parsed": [m.cand, m.cand_rule] if m.cand else None, "link": m.link}


def _meta(row):
    out = {}
    for k in ("underlying", "category", "subtypes"):
        if row.get(k) is not None:
            out[k] = row.get(k)
    return out or None


def _asset_info(t, members, exps, state, lists):
    lead = [g for g in exps if not g.single]
    tcls, twhy = ticker_class(t, lists)
    excluded = [g for g in exps if not (g.admitted or g.recorded or g.attached)]
    if state == VERIFIED_CRYPTO:
        decision = D_SELECTED if any(g.cls in (TRADFI, AMBIGUOUS) for g in excluded) else D_CRYPTO
        deciding = [g for g in exps if g.admitted]
    elif state == UNVERIFIED:
        decision, deciding = D_UNVERIFIED, [g for g in exps if g.recorded]
    elif any(g.cls == AMBIGUOUS for g in lead):
        decision, deciding = D_AMBIGUOUS, [g for g in lead if g.cls == AMBIGUOUS]
    elif any(g.auth != TICKER_LIST and any(m.cls != TRADFI for m in g.members) for g in lead):
        decision = D_TRADFI_EXPOSURE      # a contract without tradfi evidence of its own inherited it
        deciding = [g for g in lead if g.cls == TRADFI]
    else:
        decision, deciding = D_TRADFI, [g for g in lead if g.cls == TRADFI]
    state = STATE_OF_DECISION[decision]
    out = []
    for g in exps:
        px = [m.npx for m in g.members if m.npx]
        out.append({"id": g.id, "class": g.cls, "state": STATE_OF.get(g.cls), "reason": g.why, "authority": g.auth,
                    "priced": g.priced,
                    "anchor": f"{g.anchor.dex}:{g.anchor.row.get('sym')}" if g.anchor is not None else None,
                    "anchor_price": _r(g.anchor.npx) if g.anchor is not None else None,
                    "price_range": [_r(min(px)), _r(max(px))] if px else None,
                    "members": [f"{m.dex}:{m.row.get('sym')}" for m in g.members],
                    "admitted": bool(g.admitted), "attached": bool(g.attached), "recorded": bool(g.recorded)})
    # a ticker collision: the ticker's own contracts disagree (some carry tradfi or ambiguous evidence, others do
    # not) and no ticker list settles it for the whole ticker
    labels = {m.cls for g in exps for m in g.members}
    collision = tcls != TRADFI and bool(labels & {TRADFI, AMBIGUOUS}) and bool(labels & {UNLABELED, CRYPTO})
    evidence = [[m.cid, c, w, a] for m in members for c, w, a in m.ev]
    if twhy:
        evidence.append(["ticker:" + t, tcls, twhy, TICKER_LIST])
    first = deciding[0] if deciding else None
    return {"decision": decision, "state": state, "admitted": state == VERIFIED_CRYPTO,
            "authority": first.auth if first is not None else NONE,
            "reason": first.why if first is not None else None,
            "evidence": evidence, "exposures": out, "collision": collision, "ticker_list": twhy,
            "discovery_eligible": True, "execution_identity_eligible": state == VERIFIED_CRYPTO,
            "promotion": PROMOTION if state == UNVERIFIED else None,
            "excluded_unverified": [g.id for g in excluded if g.cls == UNVERIFIED and not g.single] or None,
            "links": [dict(m.link, contract=m.cid) for m in members if m.link] or None}


def _r(x, nd=8):
    if x is None:
        return None
    return float(f"{float(x):.{nd}g}")
