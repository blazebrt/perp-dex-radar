"""Universe identity (v8 Phase 2, hardened in Phase 3, economic exposure in Phase 5, exposure-local ticker authority in
Phase 6): contract-first classification, price-coherent exposures and four explicit identity states.

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

Two dimensions (v8 Phase 5, v8.identity/3). The identity answers "what economic exposure does a position on this
market take", not "is the instrument implemented as a crypto token or perpetual":
  wrapper evidence     what a venue says about how the instrument is represented (Extended category "Crypto": the
                       market is a crypto-native token/perp wrapper). Recorded per contract (CRYPTO_WRAPPER), shown in
                       the trace, and never evidence of the economic exposure in either direction: Extended files
                       tokenized gold (PAXG, XAUT) under Crypto.
  economic evidence    what price risk the position carries (rules 1-4 below). Only economic evidence decides.
A crypto wrapper on a market whose economic evidence is tradfi is VERIFIED_TRADFI, not a conflict; a crypto wrapper
with no economic evidence is UNVERIFIED (WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE), unless the ticker list verifies it.

Rules (deterministic; no statistics, no per-ticker exceptions, no network):

1. Contract evidence (economic).
   Venue metadata: Extended category "RWA" or a "_24_5" market: tradfi; Extended category "Crypto": no economic
   evidence (v8.identity/2 counted it as crypto; since /3 it is wrapper evidence only); any other Extended category:
   ambiguous. Aster underlyingType other than "COIN": tradfi; "COIN" is no evidence (Aster sends it for the stocks it
   lists too). Lighter (Phase 5): the documented `asset_type` of the market's entry in Lighter's token list
   (/api/v1/tokenlist, enum CRYPTO | RWA) is "RWA": tradfi; "CRYPTO" is no evidence (Lighter files the FX pair USDHKD
   and tokenized gold spot under CRYPTO). Hyperliquid, dYdX, Paradex, edgeX and Variational send no asset-class
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
   contracts inside the exposure only: tradfi and crypto economic evidence together: AMBIGUOUS (a true conflict of
   two economic sources); tradfi evidence: TRADFI, and its unlabeled contracts inherit it; ambiguous evidence:
   AMBIGUOUS; crypto economic evidence: CRYPTO (no source produces it since /3; QUALIFIED_CRYPTO_RULES is empty).
   Wrapper evidence is not consulted. Without contract evidence, on a ticker of the repository's known-crypto list:
   the exposure-local ticker binding of rule 4a; on any other ticker: AMBIGUOUS when another priced exposure of the
   ticker is tradfi or ambiguous; else UNVERIFIED (Phase 2: CRYPTO by default), reason
   WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE when a contract carries a crypto wrapper and NO_POSITIVE_IDENTITY_EVIDENCE
   otherwise. An unpriced contract alone with no evidence: UNVERIFIED.
4a. Ticker binding (v8 Phase 6, v8.identity/4). The known-crypto list is ticker-level knowledge: one crypto asset
   exists under the ticker. It does not say which price-coherent exposure of the ticker that asset is, so it is bound
   to at most one exposure. After every piece of contract evidence above has classified what it can, the exposures of
   a known-crypto ticker left without contract evidence are sorted out:
     blocked     a priced exposure all of whose contracts are on a venue whose exposure check did not run this scan
                 (Phase 5, fail closed: the Lighter token list failed, was malformed or has no entry for the market):
                 UNVERIFIED, EXPOSURE_CHECK_UNAVAILABLE. Never a candidate: a missing check is not evidence, and the
                 blocked exposure does not compete for the binding.
     unpriced    an exposure without a price (a ticker with no priced contract): UNVERIFIED,
                 UNPRICED_NO_CONTRACT_EVIDENCE. A contract without a price cannot be bound.
     candidates  every other priced exposure (one exposure is one candidate, however many venues it spans).
   Exactly one candidate and no exposure of the ticker with direct crypto evidence: CRYPTO, TICKER_KNOWN_CRYPTO_BOUND,
   authority TICKER_LIST. More than one candidate: the list cannot tell which price exposure is its asset, nothing
   chooses (no volume, venue count, open interest, age or majority vote: liquidity and popularity are not identity),
   and every candidate is UNVERIFIED, TICKER_CRYPTO_EXPOSURE_UNBOUND - not AMBIGUOUS, which means conflicting
   economic evidence. A candidate beside an exposure with direct crypto evidence: UNVERIFIED, the same reason (the
   ticker's crypto asset is the directly evidenced exposure). No candidate: nothing is bound. Tradfi and ambiguous
   exposures are never candidates: deterministic negative evidence removes them first (QNT, PURR, BB keep one
   candidate). The binding is recorded per asset (`ticker_authority`).
   v8.identity/3 verified every candidate (and an unpriced-only ticker) from the list alone.
5. Asset state and the coin record. Any CRYPTO exposure: VERIFIED_CRYPTO; the CRYPTO exposures are admitted and the
   coin record is built from them (plus unpriced contracts without tradfi or ambiguous evidence, as before);
   price-separated UNVERIFIED exposures of the ticker stay out. Else any UNVERIFIED exposure: UNVERIFIED; the coin
   record is built from the UNVERIFIED exposures exactly as Phase 2 built it (same venues, prices, volumes), with
   tradfi=False and identity UNVERIFIED. Else (only TRADFI / AMBIGUOUS): VERIFIED_TRADFI or AMBIGUOUS, the legacy
   record of all contracts with tradfi=True, as in Phase 2. Every coin record carries `identity` (the state).

Discovery is not execution: every coin record is in the universe whatever its state (discovery_eligible()); only
VERIFIED_CRYPTO may reach a crypto engine (execution_identity_eligible()), and a coin record without an identity
fails closed. Liquidity, history and strategy gates are separate and unchanged.

Candidate evidence (Phase 4, Stage A): venue fields that are not evidence in either direction (CANDIDATE_FIELDS:
Aster underlyingType COIN and the non-tradfi underlyingSubType tags, Lighter strategy_index, insurance fund and market
flags) are recorded per contract as observed candidate evidence (candidate_evidence()) for the audit, apart from the
authoritative evidence above. Phase 4 qualified no candidate rule (QUALIFIED_CRYPTO_RULES is empty). Phase 5 adds the
Extended subCategory (undocumented in Extended's market schema) and the Lighter token-list values that are not
evidence (asset_type CRYPTO, categories) to the candidates.

Versions. v8.identity/3 (Phase 5) differs from /2 only in Extended category "Crypto" (wrapper, no longer crypto
evidence), the Lighter token-list RWA evidence and its fail-closed rule. v8.identity/4 (Phase 6) differs from /3
only in rule 4a (the known-crypto list is bound to at most one exposure). resolve() also resolves the same contracts
under the previous rules (PREVIOUS_VERSION) and records the result per asset (`previous`), so every audit shows
exactly which assets the version change moved and why. Every version stays reproducible: rules=2, 3 and 4
(VERSION_RULES) resolve as v8.identity/2, /3 and /4 decided.

Volumes: an observed 0 counts (best_vol, tot_vol, trade_vol are 0.0, not None); None means no venue reported one."""
from __future__ import annotations

import json
import os
import statistics

VERSION = "v8.identity/4"
PREVIOUS_VERSION = "v8.identity/3"      # resolved beside it on the same contracts, for the audit's before/after
# the rules each identity version decided by (resolve(rules=...)); older snapshots are reproduced by their own rules
VERSION_RULES = {"v8.identity/2": 2, "v8.identity/3": 3, "v8.identity/4": 4}
RULES, PREVIOUS_RULES = VERSION_RULES[VERSION], VERSION_RULES[PREVIOUS_VERSION]
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
# The category Extended files crypto-native markets under. v8.identity/2 read it as crypto evidence; Phase 5 found it
# describes the instrument wrapper, not the economic exposure (tokenized gold PAXG and XAUT are filed under it), so
# since v8.identity/3 it is wrapper evidence only (wrapper_evidence()).
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
PROMOTION_UNBOUND = ("a unique binding (v8 Phase 6): deterministic negative evidence on all but one of the ticker's "
                     "price exposures, or positive economic evidence on one of them; the known-crypto list alone "
                     "cannot choose among price-separated exposures")
PROMOTION = ("positive identity evidence on a price-coherent contract: the repository's known-crypto or tradfi list, "
             "a venue tradfi label (Extended category RWA, Aster underlyingType or tradfi subtype, Lighter token-list "
             "asset type RWA), a tradfi contract name, or a verified tradfi exposure linked by the venue symbol; a "
             "crypto wrapper label (Extended category Crypto) is not evidence")

# v8 Phase 4 (Stage A): candidate evidence. Venue fields that could look like an asset class but are NOT evidence.
# Phase 4 censused every value of them against the identity states of the retained and live scans and put each one
# through the positive-crypto qualification gate (tools/v8/candidate_census.py, docs/v8/phase4-positive-crypto-
# evidence.md). None qualified: no value states a crypto asset class (Aster underlyingSubType values are sectors,
# themes, tiers, programmes or listing stages; Lighter's strategy_index is absent from its API schema), and the
# values a venue files as crypto include tokenized gold (PAXG) and tickers on the repository's tradfi list. They are
# recorded per contract as OBSERVED candidate evidence (the audit trace), apart from the authoritative evidence of
# contract_evidence(), and they decide nothing. A value used as authority already (an Aster underlyingType other
# than COIN, an Aster tradfi subtype) is authoritative evidence and is not repeated here.
CANDIDATE_FIELDS = {"aster": ("underlyingType", "underlyingSubType"),
                    "lighter": ("strategy_index", "insurance_fund_account_index", "market_flags", "asset_type",
                                "asset_categories"),
                    "extended": ("subCategory",)}
QUALIFIED_CRYPTO_RULES = ()      # Phase 4: no candidate rule qualified as positive crypto evidence (Phase 5: still none)
CANDIDATE_STATUS = "OBSERVED_NOT_AUTHORITY"

# --------------------------------------------------------------------------- v8 Phase 5: wrapper vs economic exposure
CRYPTO_WRAPPER = "CRYPTO_WRAPPER"        # wrapper evidence: how the instrument is represented, never its exposure
WRAPPER_ONLY = "WRAPPER_ONLY"            # the effect of wrapper evidence on the identity: none
# Lighter's token list (GET /api/v1/tokenlist, one bulk request): Token.asset_type is documented in Lighter's OpenAPI
# schema with the enum CRYPTO | RWA, and Lighter's documentation defines its RWAs as commodities, equities and fixed
# income markets. A market's entry: market == "PERPS" and backend_symbol (when set) or symbol == the market symbol of
# /api/v1/orderBookDetails. Only RWA is evidence (tradfi); CRYPTO is not (Phase 5 census: the FX pair USDHKD and
# tokenized gold spot XAUT are filed under CRYPTO).
LIGHTER_ASSET_TYPES = ("CRYPTO", "RWA")
LIGHTER_TRADFI_ASSET_TYPES = frozenset({"RWA"})
LIGHTER_TOKENLIST = "LIGHTER_TOKENLIST"
# Exposure-check states of a contract on a venue that has one (EXPOSURE_CHECKS). Anything but OK means the check did
# not run for that market this scan: the whole list failed (network, 429/5xx after retries), was unavailable (another
# HTTP error), was malformed, had no entry for the market, or a malformed entry; NOT_REQUESTED when the adapter row
# carries no check at all. The check failing never makes a market crypto (rule 4).
XCHECK_OK, XCHECK_FAILED, XCHECK_UNAVAILABLE, XCHECK_MALFORMED = "OK", "FAILED", "UNAVAILABLE", "MALFORMED"
XCHECK_NO_ENTRY, XCHECK_MALFORMED_ENTRY, XCHECK_NOT_REQUESTED = "NO_ENTRY", "MALFORMED_ENTRY", "NOT_REQUESTED"
XCHECK_STATES = (XCHECK_OK, XCHECK_FAILED, XCHECK_UNAVAILABLE, XCHECK_MALFORMED, XCHECK_NO_ENTRY,
                 XCHECK_MALFORMED_ENTRY, XCHECK_NOT_REQUESTED)
EXPOSURE_CHECKS = {"lighter": LIGHTER_TOKENLIST}      # venue -> its economic-exposure check
R_CHECK_UNAVAILABLE = "EXPOSURE_CHECK_UNAVAILABLE"
R_WRAPPER_ONLY = "WRAPPER_ONLY_NO_ECONOMIC_EVIDENCE"
R_NO_EVIDENCE = "NO_POSITIVE_IDENTITY_EVIDENCE"

# --------------------------------------------------------------------------- v8 Phase 6: exposure-local ticker binding
R_TICKER = "TICKER_KNOWN_CRYPTO"                  # the ticker is on the known-crypto list (ticker-level knowledge)
R_BOUND = "TICKER_KNOWN_CRYPTO_BOUND"             # the list was bound to this one exposure (v8.identity/4)
R_UNBOUND = "TICKER_CRYPTO_EXPOSURE_UNBOUND"      # the list could not be bound to this exposure (v8.identity/4)
R_UNPRICED = "UNPRICED_NO_CONTRACT_EVIDENCE"
# an exposure's role in its ticker's binding (Exposure.bind); None: not a known-crypto exposure without evidence
B_SELECTED, B_UNBOUND, B_BLOCKED, B_UNPRICED = "SELECTED", "UNBOUND", "CHECK_BLOCKED", "UNPRICED"
# the ticker's binding result (ticker_authority.result)
T_BOUND, T_UNBOUND_MULTI, T_UNBOUND_DIRECT, T_NO_CANDIDATE = (
    "BOUND", "UNBOUND_MULTIPLE_CANDIDATES", "UNBOUND_DIRECT_CRYPTO_EVIDENCE", "NO_BINDABLE_EXPOSURE")
TICKER_RESULTS = (T_BOUND, T_UNBOUND_MULTI, T_UNBOUND_DIRECT, T_NO_CANDIDATE)
TRACE_STATEMENT = {T_BOUND: "UNIQUE EXPOSURE BINDING", T_UNBOUND_MULTI: "NO UNIQUE EXPOSURE BINDING",
                   T_UNBOUND_DIRECT: "NO TICKER BINDING: DIRECT CRYPTO EVIDENCE DECIDES",
                   T_NO_CANDIDATE: "NO BINDABLE EXPOSURE"}


def candidate_evidence(venue, vmeta):
    """[[field, value], ...]: the candidate values one contract's raw venue fields carry (strings; one entry per element
    of a list field), never authority. Authoritative values (Aster underlyingType other than COIN, the Aster tradfi
    subtypes) are left out: they are contract evidence already. A missing field gives nothing."""
    out = []
    for field in CANDIDATE_FIELDS.get(venue, ()):
        v = (vmeta or {}).get(field)
        if v is None or v == "":
            continue
        for x in (v if isinstance(v, list) else [v]):
            x = str(x)
            if venue == "aster" and field == "underlyingType" and x not in ASTER_NEUTRAL_UNDERLYING:
                continue
            if venue == "aster" and field == "underlyingSubType" and x in ASTER_TRADFI_SUBTYPES:
                continue
            if venue == "lighter" and field == "asset_type" and x in LIGHTER_TRADFI_ASSET_TYPES:
                continue
            out.append([field, x])
    return out


def lighter_tokenlist_index(payload):
    """(state, index, detail) from a Lighter /api/v1/tokenlist payload (pure; no network).

    index: {market symbol: {"asset_type": ..., "categories": [...]}} for every PERPS entry, keyed by backend_symbol
    when set (kPEPE -> 1000PEPE) else symbol; an entry whose asset_type is outside the documented enum, or two entries
    for one market that disagree, map to None (MALFORMED_ENTRY). state: OK, or MALFORMED when the payload is not the
    documented TokenList (code 200 and a tokens array) or holds no usable PERPS entry."""
    detail = {"tokens": 0, "perps_entries": 0, "malformed_entries": [], "duplicate_entries": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("tokens"), list):
        return XCHECK_MALFORMED, {}, dict(detail, why="no tokens array")
    if payload.get("code") not in (None, 200):
        return XCHECK_MALFORMED, {}, dict(detail, why=f"code {payload.get('code')}")
    index = {}
    for e in payload["tokens"]:
        detail["tokens"] += 1
        if not isinstance(e, dict) or e.get("market") != "PERPS":
            continue
        detail["perps_entries"] += 1
        key = str(e.get("backend_symbol") or e.get("symbol") or "")
        if not key:
            detail["malformed_entries"].append(str(e.get("symbol")))
            continue
        at = e.get("asset_type")
        cats = e.get("categories")
        rec = {"asset_type": at, "categories": [str(c) for c in cats] if isinstance(cats, list) else []}
        if at not in LIGHTER_ASSET_TYPES:
            detail["malformed_entries"].append(key)
            rec = None
        if key in index:
            detail["duplicate_entries"].append(key)
            if index[key] is None or rec is None or index[key]["asset_type"] != rec["asset_type"]:
                index[key] = None
            continue
        index[key] = rec
    if not any(v is not None for v in index.values()):
        return XCHECK_MALFORMED, {}, dict(detail, why="no usable PERPS entry")
    return XCHECK_OK, index, detail


def lighter_exposure_fields(sym, state, index):
    """The exposure-check fields of one Lighter market: {"xcheck": state, "asset_type": ..., "asset_categories": [...]}.
    state is the token list's state this scan (OK, FAILED, UNAVAILABLE, MALFORMED, NOT_REQUESTED)."""
    if state != XCHECK_OK:
        return {"xcheck": state or XCHECK_NOT_REQUESTED}
    if sym not in index:
        return {"xcheck": XCHECK_NO_ENTRY}
    rec = index[sym]
    if rec is None:
        return {"xcheck": XCHECK_MALFORMED_ENTRY}
    return {"xcheck": XCHECK_OK, "asset_type": rec["asset_type"], "asset_categories": list(rec["categories"])}


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


def contract_evidence(row, lists, dex=None, rules=3):
    """[(class, reason, authority), ...]: the economic evidence of what the contract itself says (Phase 2 evidence,
    the Phase 3 venue field and parsed-symbol evidence, since Phase 5 the documented exposure fields). rules=2: as
    v8.identity/2 decided (Extended Crypto as crypto evidence, no exposure fields)."""
    if rules >= 3:
        return (base_evidence(row, lists, 3) + venue_field_evidence(row, lists) + exposure_field_evidence(row)
                + parsed_evidence(row, lists, dex))
    return base_evidence(row, lists, 2) + venue_field_evidence(row, lists) + parsed_evidence(row, lists, dex)


def wrapper_evidence(row):
    """[(CRYPTO_WRAPPER, reason, authority)]: what the venue says about the instrument wrapper (Phase 5). Never
    evidence of the economic exposure: recorded and traced, consulted by no rule."""
    if row.get("dex") == "extended" and row.get("category") in EXTENDED_CRYPTO_CATEGORIES:
        return [(CRYPTO_WRAPPER, f"VENUE_CATEGORY:{row.get('category')}", VENUE_METADATA)]
    return []


def exposure_field_evidence(row):
    """Phase 5: tradfi evidence from documented venue exposure metadata - a Lighter market whose token-list entry
    (checked this scan) has asset_type RWA. Same contract only; nothing for a market whose check did not run."""
    if row.get("dex") == "lighter" and row.get("xcheck") == XCHECK_OK \
            and row.get("asset_type") in LIGHTER_TRADFI_ASSET_TYPES:
        return [(TRADFI, f"VENUE_ASSET_TYPE:{row.get('asset_type')}", VENUE_METADATA)]
    return []


def exposure_check(row, dex=None):
    """The exposure-check state of a contract on a venue that has one (EXPOSURE_CHECKS), else None."""
    dex = dex or row.get("dex")
    if dex not in EXPOSURE_CHECKS:
        return None
    x = row.get("xcheck")
    return x if x in XCHECK_STATES else XCHECK_NOT_REQUESTED


def base_evidence(row, lists, rules=3):
    """The Phase 2 evidence of one contract: venue metadata and the contract name. rules=2 (what Phase 2 and
    v8.identity/2 knew) reads Extended category Crypto as crypto evidence; rules=3 does not (wrapper_evidence)."""
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
                if rules < 3:
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


def classify_contract(row, lists, rules=3):
    """(class, reason, authority) of one contract from its own economic evidence; UNLABELED when it carries none."""
    return classify_evidence(contract_evidence(row, lists, rules=rules))


def ticker_class(t, lists):
    """(class, reason) from the repository's ticker lists, or (None, None)."""
    if t in lists.tradfi:
        return TRADFI, "TICKER_TRADFI_LIST"
    if lists.is_fx(t):
        return TRADFI, "TICKER_FX_PAIR"
    if t in lists.known_crypto:
        return CRYPTO, R_TICKER
    return None, None


# --------------------------------------------------------------------------- 2. exposures of one ticker
class Member:
    __slots__ = ("dex", "i", "row", "ev2", "ev", "cls", "why", "auth", "cls2", "npx", "vol", "cand", "cand_rule",
                 "link", "wrap", "xcheck", "xmissing")

    def __init__(self, dex, i, row, lists, rules=None):
        rules = RULES if rules is None else rules
        self.dex, self.i, self.row = dex, i, row
        self.ev2 = base_evidence(row, lists, 2)                  # what Phase 2 knew
        self.ev = contract_evidence(row, lists, dex, rules)      # economic evidence (Phase 3; Phase 5 since /3)
        self.cls, self.why, self.auth = classify_evidence(self.ev)
        self.cls2 = classify_evidence(self.ev2)[0]
        # Phase 5: wrapper evidence (never decides) and the venue's exposure check (fail closed when it did not run)
        self.wrap = wrapper_evidence(row) if rules >= 3 else []
        self.xcheck = exposure_check(row, dex) if rules >= 3 else None
        self.xmissing = self.xcheck is not None and self.xcheck != XCHECK_OK
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
                 "recorded", "bind")

    def __init__(self, xid, members, anchor, priced, single=False):
        self.id, self.members, self.anchor, self.priced, self.single = xid, members, anchor, priced, single
        self.cls = self.why = self.auth = None
        self.admitted = self.attached = self.recorded = False
        self.bind = None             # v8 Phase 6: the exposure's role in its ticker's binding (B_*), else None

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


def classify_exposures(t, exps, lists, phase2=False, rules=None):
    """Sets cls/why/auth of every exposure of ticker t (rules 4 and 4a of the module docstring). phase2=True classifies
    as Phase 2 did (no parsed-symbol evidence; no evidence = CRYPTO by default), for the before/after only. rules: the
    identity rules version (default RULES); the members carry their own (Member(rules=...)): wrapper evidence and
    exposure checks exist since /3. Since /4 a known-crypto ticker is bound to at most one exposure (bind_ticker)."""
    rules = RULES if rules is None else rules
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
    if tcls == CRYPTO and not phase2 and rules >= 4:
        bind_ticker(exps, pending)
        return exps
    for g in pending:
        if tcls == CRYPTO:
            if not phase2 and g.members and all(m.xmissing for m in g.members):
                # Phase 5, fail closed: every contract of this exposure is on a venue whose exposure check did not
                # run this scan; the ticker list alone does not verify what the missing check might have shown
                g.cls, g.why, g.auth = UNVERIFIED, R_CHECK_UNAVAILABLE, NONE
            else:
                g.cls, g.why, g.auth = CRYPTO, twhy, TICKER_LIST
        elif collision:
            g.cls, g.why, g.auth = AMBIGUOUS, "UNLABELED_UNDER_TRADFI_COLLISION", NONE
        elif phase2:
            g.cls, g.why, g.auth = CRYPTO, "DEFAULT_CRYPTO", DEFAULT
        else:
            wrapped = any(m.wrap for m in g.members)
            g.cls, g.why, g.auth = UNVERIFIED, (R_WRAPPER_ONLY if wrapped else R_NO_EVIDENCE), NONE
    return exps


def bind_ticker(exps, pending):
    """Rule 4a (v8.identity/4): bind a known-crypto ticker's list authority to at most one of its exposures without
    contract evidence (`pending`). Sets cls/why/auth and the binding role (Exposure.bind) of each pending exposure.
    Nothing here reads a volume, a venue count, an open interest, an age or the order of the exposures: the outcome
    depends only on how many candidates are left, so it chooses nothing."""
    direct = [g for g in exps if not g.single and g.cls == CRYPTO]     # direct crypto evidence (none since /3)
    cands = []
    for g in pending:
        if not g.priced:
            g.cls, g.why, g.auth, g.bind = UNVERIFIED, R_UNPRICED, NONE, B_UNPRICED
        elif g.members and all(m.xmissing for m in g.members):
            # Phase 5, fail closed: every contract of this exposure is on a venue whose exposure check did not run
            # this scan; the ticker list alone does not verify what the missing check might have shown, and the
            # blocked exposure is not a candidate (it neither takes the binding nor competes for it)
            g.cls, g.why, g.auth, g.bind = UNVERIFIED, R_CHECK_UNAVAILABLE, NONE, B_BLOCKED
        else:
            cands.append(g)
    if len(cands) == 1 and not direct:
        g = cands[0]
        g.cls, g.why, g.auth, g.bind = CRYPTO, R_BOUND, TICKER_LIST, B_SELECTED
        return
    for g in cands:
        g.cls, g.why, g.auth, g.bind = UNVERIFIED, R_UNBOUND, NONE, B_UNBOUND


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
        self.rules = RULES       # the identity rules version this resolution decided by
        self.known_crypto = []   # the known-crypto list it read (v8 Phase 6: the list audit)

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
    dict in the legacy order (first appearance of each ticker in market-list order), each with `identity`.

    Since Phase 5 every asset also carries `previous`: the state, decision, reason and authority the previous identity
    version (PREVIOUS_VERSION, its rules PREVIOUS_RULES) gives the same contracts - the audit's before/after. Only
    VERSION decides."""
    res = _resolve(results, dexes, lists, in_my_dexes, on_conflict, rules=RULES)
    prev = _resolve(results, dexes, lists, in_my_dexes, None, rules=PREVIOUS_RULES, before_after=False)
    for t, info in res.assets.items():
        p = prev.assets.get(t)
        info["previous"] = ({"version": PREVIOUS_VERSION, "state": p["state"], "decision": p["decision"],
                             "reason": p["reason"], "authority": p["authority"]} if p is not None else None)
    return res


def resolve_version(version, results, dexes, lists, in_my_dexes):
    """The resolution a named identity version gives the same contracts (VERSION_RULES: v8.identity/2, /3 or /4), for
    reproducing older snapshots and the before/after; no `previous`, no Phase 1/2 before/after. Never decides."""
    return _resolve(results, dexes, lists, in_my_dexes, None, rules=VERSION_RULES[version], before_after=False)


def _resolve(results, dexes, lists, in_my_dexes, on_conflict=None, rules=None, before_after=True):
    """The resolution under one rules version (VERSION_RULES; default RULES). resolve() is the production entry."""
    rules = RULES if rules is None else rules
    res = Resolution()
    res.rules = rules
    res.known_crypto = sorted(lists.known_crypto)
    by_t = {}
    for dex in dexes:
        rows = results.get(dex)
        if rows is None:
            continue
        res.crypto_rows[dex] = 0
        for i, r in enumerate(rows):
            by_t.setdefault(r["t"], []).append(Member(dex, i, r, lists, rules))
    exps_of = {t: classify_exposures(t, group(t, ms), lists, rules=rules) for t, ms in by_t.items()}
    for t in link_symbols(by_t, exps_of, lists):
        exps_of[t] = classify_exposures(t, group(t, by_t[t]), lists, rules=rules)
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
        info = _asset_info(t, members, exps, state, lists, rules)
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
        if before_after:
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
            "parsed": [m.cand, m.cand_rule] if m.cand else None, "link": m.link,
            # v8 Phase 5: wrapper evidence (never decides) and the venue's exposure check
            "wrapper": [[c, w, a] for c, w, a in m.wrap] or None, "xcheck": m.xcheck}


def _meta(row):
    """The adapter-row fields the identity rules read (the audit keeps them, so a snapshot re-resolves offline)."""
    out = {}
    for k in ("underlying", "category", "subtypes", "asset_type", "xcheck"):
        if row.get(k) is not None:
            out[k] = row.get(k)
    return out or None


def _asset_info(t, members, exps, state, lists, rules=None):
    rules = RULES if rules is None else rules
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
        x = {"id": g.id, "class": g.cls, "state": STATE_OF.get(g.cls), "reason": g.why, "authority": g.auth,
             "priced": g.priced,
             "anchor": f"{g.anchor.dex}:{g.anchor.row.get('sym')}" if g.anchor is not None else None,
             "anchor_price": _r(g.anchor.npx) if g.anchor is not None else None,
             "price_range": [_r(min(px)), _r(max(px))] if px else None,
             "members": [f"{m.dex}:{m.row.get('sym')}" for m in g.members],
             "admitted": bool(g.admitted), "attached": bool(g.attached), "recorded": bool(g.recorded)}
        if g.bind is not None:       # v8 Phase 6: the exposure's role in its ticker's binding
            x["binding"] = g.bind
        wr = sorted({w for m in g.members for _, w, _ in m.wrap})
        if wr:                       # v8 Phase 5: the exposure's wrapper labels, beside (not part of) its class
            x["wrapper"] = wr
        out.append(x)
    # a ticker collision: the ticker's own contracts disagree (some carry tradfi or ambiguous evidence, others do
    # not) and no ticker list settles it for the whole ticker
    labels = {m.cls for g in exps for m in g.members}
    collision = tcls != TRADFI and bool(labels & {TRADFI, AMBIGUOUS}) and bool(labels & {UNLABELED, CRYPTO})
    evidence = [[m.cid, c, w, a] for m in members for c, w, a in m.ev]
    if twhy:
        evidence.append(["ticker:" + t, tcls, twhy, TICKER_LIST])
    wrapper = [[m.cid, c, w, a] for m in members for c, w, a in m.wrap]
    checks = [[m.cid, EXPOSURE_CHECKS[m.dex], m.xcheck] for m in members if m.xcheck is not None]
    first = deciding[0] if deciding else None
    wrapper_only = state == UNVERIFIED and any(g.why == R_WRAPPER_ONLY for g in deciding)
    tauth = ticker_authority(t, exps, state) if tcls == CRYPTO and rules >= 4 else None
    unbound = tauth is not None and tauth["result"] in (T_UNBOUND_MULTI, T_UNBOUND_DIRECT)
    return {"decision": decision, "state": state, "admitted": state == VERIFIED_CRYPTO,
            "authority": first.auth if first is not None else NONE,
            "reason": first.why if first is not None else None,
            "evidence": evidence, "exposures": out, "collision": collision, "ticker_list": twhy,
            "discovery_eligible": True, "execution_identity_eligible": state == VERIFIED_CRYPTO,
            "promotion": (PROMOTION_UNBOUND if unbound else PROMOTION) if state == UNVERIFIED else None,
            # v8 Phase 6: how the known-crypto list was bound to this ticker's exposures (None: not on the list)
            "ticker_authority": tauth,
            "excluded_unverified": [g.id for g in excluded if g.cls == UNVERIFIED and not g.single] or None,
            "links": [dict(m.link, contract=m.cid) for m in members if m.link] or None,
            # v8 Phase 5: the two evidence paths, kept apart (Decision Trace)
            "wrapper_evidence": wrapper, "exposure_checks": checks, "wrapper_only": wrapper_only,
            "exposure_trace": exposure_trace(wrapper, evidence, checks, state, decision,
                                             first.why if first is not None else None, tauth)}


def ticker_authority(t, exps, state):
    """The exposure-local binding of a known-crypto ticker (rule 4a), as the audit records it: the ticker-level input,
    every exposure that was a binding candidate, the one selected (or none), the result, and why each other exposure
    was not a candidate."""
    lead = [g for g in exps if not g.single]
    cands = [g for g in exps if g.bind in (B_SELECTED, B_UNBOUND)]
    sel = next((g for g in exps if g.bind == B_SELECTED), None)
    direct = [g for g in lead if g.cls == CRYPTO and g.bind is None]
    if sel is not None:
        result = T_BOUND
    elif cands and direct:
        result = T_UNBOUND_DIRECT
    elif len(cands) > 1:
        result = T_UNBOUND_MULTI
    else:
        result = T_NO_CANDIDATE
    excluded = []
    for g in exps:
        if g.bind in (B_SELECTED, B_UNBOUND):
            continue
        if g.bind == B_BLOCKED:
            why = R_CHECK_UNAVAILABLE
        elif g.bind == B_UNPRICED or g.single:
            why = "UNPRICED"
        elif g.cls == CRYPTO:
            why = "DIRECT_CRYPTO_EVIDENCE"
        else:
            why = f"{g.cls}_EVIDENCE"          # TRADFI_EVIDENCE / AMBIGUOUS_EVIDENCE: deterministic contract evidence
        excluded.append([g.id, why])
    return {"ticker": t, "known_crypto": True, "rules_version": VERSION,
            "bindable_exposures": [g.id for g in cands],
            "candidate_prices": {g.id: _r(g.anchor.npx) for g in cands if g.anchor is not None},
            "selected_exposure": sel.id if sel is not None else None, "result": result,
            "excluded": excluded,
            "direct_crypto_exposures": [g.id for g in direct],
            "check_blocked_exposures": [g.id for g in exps if g.bind == B_BLOCKED],
            "tradfi_exposures": [g.id for g in lead if g.cls == TRADFI],
            "ambiguous_exposures": [g.id for g in lead if g.cls == AMBIGUOUS],
            "unpriced_exposures": [g.id for g in exps if g.bind == B_UNPRICED or g.single],
            "statement": TRACE_STATEMENT[result], "effect": state}


def exposure_trace(wrapper, evidence, checks, state, decision, reason, tauth=None):
    """The Decision Trace of one asset's identity (v8 Phase 5): the wrapper path and its effect (none), the economic
    path and its result, the exposure checks, the final state and whether crypto execution is allowed. Since v8 Phase 6
    also the ticker binding (binding_trace): which exposures the known-crypto list could be bound to and the result."""
    econ_classes = sorted({c for _, c, _, _ in evidence})
    return {"binding": binding_trace(tauth),
            "wrapper": [{"source": s, "evidence": w, "effect": WRAPPER_ONLY} for s, _, w, _ in wrapper],
            "economic": [{"source": s, "class": c, "evidence": w, "authority": a} for s, c, w, a in evidence],
            "economic_classes": econ_classes,
            "checks": [{"source": s, "check": k, "state": v} for s, k, v in checks],
            "final": state, "decision": decision, "reason": reason,
            "crypto_execution": "ALLOWED" if state == VERIFIED_CRYPTO else "BLOCKED"}


def binding_trace(tauth):
    """Input -> candidates -> rules -> result -> effect of one ticker binding, in words (None: not a known-crypto
    ticker, or rules before /4). No silent rejection: every exposure is either a candidate or excluded with a why."""
    if tauth is None:
        return None
    cands, result = tauth["bindable_exposures"], tauth["result"]
    rules = [f"{x}: excluded ({why})" for x, why in tauth["excluded"]]
    rules += [f"{x}: no economic evidence either way (candidate)" for x in cands]
    if result == T_UNBOUND_MULTI:
        rules.append(f"{len(cands)} candidates are price-separated; ticker-level identity cannot distinguish them")
    elif result == T_UNBOUND_DIRECT:
        rules.append("the ticker's crypto asset is the directly evidenced exposure; the list cannot verify another")
    elif result == T_BOUND:
        rules.append("one candidate left: the ticker list is bound to it")
    else:
        rules.append("no candidate left: nothing to bind")
    return {"input": "KNOWN_CRYPTO ticker = true", "candidates": cands, "rules": rules,
            "result": tauth["statement"], "selected": tauth["selected_exposure"], "effect": tauth["effect"]}


def _r(x, nd=8):
    if x is None:
        return None
    return float(f"{float(x):.{nd}g}")


# --------------------------------------------------------------------------- 5. same-scan identity authority
# The scanner resolves the universe and writes every coin's identity once per scan; engines that do not build the
# universe themselves (smart money, which reads Hyperliquid positions) read it from the same output folder instead of
# rebuilding it. It is the same authority the other engines use, never a second classifier.
AUTHORITY_FILE = os.path.join("data", "v8", "identity_authority.json")
AUTHORITY_SCHEMA = "v8.identity-authority/1"
AUTHORITY_MAX_AGE_S = 6 * 3600      # offline only: in GitHub Actions the scan ids must be equal


def authority_record(coins, ts, scan_id, assets=None):
    """{coin: [state, decision]} for every coin of a universe (decision from the Resolution when given, else the
    state's own name), with the scan it belongs to."""
    states = {}
    for t, c in (coins or {}).items():
        st = c.get("identity")
        dec = ((assets or {}).get(t) or {}).get("decision") if assets else None
        states[t] = [st, dec or st]
    return {"schema": AUTHORITY_SCHEMA, "identity_version": VERSION, "scan_id": scan_id, "ts": int(ts),
            "n": len(states), "states": dict(sorted(states.items()))}


def write_authority(out_dir, coins, ts, scan_id, assets=None):
    path = os.path.join(out_dir, AUTHORITY_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(authority_record(coins, ts, scan_id, assets), fh, sort_keys=True, separators=(",", ":"))
    return path


class Authority:
    """Identity states of one scan as an engine reads them. state(t) is None whenever the authority is not usable
    or does not name the coin: the caller treats None as no execution identity (fail closed)."""

    def __init__(self, ok, why, record=None):
        self.ok, self.why = ok, why
        rec = record or {}
        self.scan_id, self.ts = rec.get("scan_id"), rec.get("ts")
        self.version = rec.get("identity_version")
        self.states = (rec.get("states") or {}) if ok else {}

    def state(self, t):
        v = self.states.get(t)
        return v[0] if isinstance(v, list) and v else None

    def decision(self, t):
        v = self.states.get(t)
        return v[1] if isinstance(v, list) and len(v) > 1 else None

    def summary(self):
        return {"ok": self.ok, "why": self.why, "scan_id": self.scan_id, "ts": self.ts, "coins": len(self.states),
                "source": AUTHORITY_FILE.replace(os.sep, "/")}

    @classmethod
    def from_states(cls, states, scan_id="given", ts=0):
        """An authority built in memory (tests): {coin: state} or {coin: [state, decision]}."""
        rec = {"scan_id": scan_id, "ts": ts, "identity_version": VERSION,
               "states": {t: (v if isinstance(v, list) else [v, v]) for t, v in (states or {}).items()}}
        return cls(True, "given", rec)


def load_authority(out_dir, now, scan_id):
    """The scanner's identity authority of this scan, from out_dir. Fails closed: a missing, unreadable, other-version
    or other-scan file gives an authority with no states (every coin None). Same scan: equal GitHub Actions scan ids
    (gh-<run>-<attempt>); offline (local scan ids) the file must be at most AUTHORITY_MAX_AGE_S away in time."""
    path = os.path.join(out_dir, AUTHORITY_FILE)
    try:
        with open(path) as fh:
            rec = json.load(fh)
    except FileNotFoundError:
        return Authority(False, "NO_AUTHORITY_FILE")
    except (OSError, ValueError) as e:
        return Authority(False, f"UNREADABLE:{type(e).__name__}", None)
    if not isinstance(rec, dict) or rec.get("schema") != AUTHORITY_SCHEMA:
        return Authority(False, "WRONG_SCHEMA", rec if isinstance(rec, dict) else None)
    if rec.get("identity_version") != VERSION:
        return Authority(False, f"OTHER_IDENTITY_VERSION:{rec.get('identity_version')}", rec)
    a, b = str(rec.get("scan_id") or ""), str(scan_id or "")
    if a.startswith("gh-") or b.startswith("gh-"):
        if a != b:
            return Authority(False, "OTHER_SCAN", rec)
    elif not isinstance(rec.get("ts"), (int, float)) or abs(int(now) - int(rec["ts"])) > AUTHORITY_MAX_AGE_S:
        return Authority(False, "STALE", rec)
    return Authority(True, "SAME_SCAN", rec)

