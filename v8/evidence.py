"""Entry-time identity provenance of paper trades, and the current identity of open positions (v8 Phase 3 closure).

Two separate questions, never mixed:

  current identity      May this open position be an actionable trade signal NOW?
                        Answered from this scan's identity (the same universe / authority every engine gates on):
                        only VERIFIED_CRYPTO; a missing identity fails closed. It changes from scan to scan and is
                        never written into the journal.

  entry-time proof      May this trade count in the forward (live) evidence record when it closes?
                        Answered once, when the trade is opened, from the identity of the scan that opens it:
                        identity_state_at_entry, identity_qualified, identity_version, identity_scan_id,
                        identity_decision. Never recomputed from a later scan - in either direction (no hindsight).

A trade written before entry-time proof existed carries none of it: it is kept unchanged (prices, stop, trail,
hours, funding, returns, R, open/closed state), followed to its normal close, marked LEGACY_NO_IDENTITY_PROOF and
reported apart; it never enters a live record. Nothing here classifies identity: the states come from v8.identity
through the scan's universe (smart money uses the same rule through its same-scan authority file, smart.py)."""
from __future__ import annotations

from . import identity as ID

LEGACY_NO_IDENTITY_PROOF = "LEGACY_NO_IDENTITY_PROOF"
NOT_VERIFIED_AT_ENTRY = "NOT_VERIFIED_AT_ENTRY"
IDENTITY_PROOF_INCOMPLETE = "IDENTITY_PROOF_INCOMPLETE"
TRADE_IDENTITY_FIELDS = ("identity_state_at_entry", "identity_qualified", "identity_version", "identity_scan_id",
                         "identity_decision")


# --------------------------------------------------------------------------- this scan's identity
def universe_authority(coins, ts, scan_id, assets=None):
    """The identity authority of a universe built in this process: the very record the scanner writes as
    data/v8/identity_authority.json (v8.identity.authority_record), held in memory. A coin record without an
    identity has state None (fail closed)."""
    return ID.Authority(True, "SCAN_UNIVERSE", ID.authority_record(coins, ts, scan_id, assets))


def block_reason(state, decision=None):
    """The reason a coin in `state` has no crypto execution identity, or None for VERIFIED_CRYPTO."""
    if state == ID.VERIFIED_CRYPTO:
        return None
    if state == ID.UNVERIFIED:
        return "IDENTITY_UNVERIFIED"
    if state == ID.AMBIGUOUS:
        return "AMBIGUOUS_EXPOSURE"
    if state == ID.VERIFIED_TRADFI:
        return decision if decision in ("TRADFI_CLASSIFIED", "TRADFI_EXPOSURE_EXCLUDED") else "TRADFI_CLASSIFIED"
    return "IDENTITY_AUTHORITY_MISSING"


def current_identity(coin_record, decision=None):
    """(state, block reason or None) of an open position's coin in this scan. The gate is the engines' own
    execution gate (v8.identity.execution_identity_eligible); a coin missing from this scan's universe, or without
    an identity, is blocked (IDENTITY_AUTHORITY_MISSING)."""
    if coin_record is None:
        return None, "IDENTITY_AUTHORITY_MISSING"
    st = coin_record.get("identity")
    if ID.execution_identity_eligible(coin_record):
        return st, None
    if coin_record.get("tradfi") and st == ID.VERIFIED_CRYPTO:      # not produced by v8.identity; fail closed anyway
        return st, "TRADFI_CLASSIFIED"
    return st, block_reason(st, decision)


# --------------------------------------------------------------------------- entry-time proof
def stamp(tr, coin, auth):
    """Entry-time identity provenance of a new paper trade on `coin`, from the authority of the scan that opens it.
    Written once; never rewritten."""
    st = auth.state(coin)
    ok = bool(auth.ok) and st == ID.VERIFIED_CRYPTO
    tr.update(identity_state_at_entry=st, identity_qualified=ok, identity_version=auth.version,
              identity_scan_id=auth.scan_id, identity_decision=auth.decision(coin))
    if not ok:              # not reachable through the engines: their source gates open trades on VERIFIED_CRYPTO only
        tr["identity_unqualified_reason"] = NOT_VERIFIED_AT_ENTRY
    return tr


def stamp_pair(twin, parent, coin, auth):
    """A benchmark twin carries its pair's proof: it is evidence only together with the trade it benchmarks, so its
    qualification is the parent's (a pair is in or out of the live record as a whole). The twin's own coin state is
    recorded beside it."""
    for k in TRADE_IDENTITY_FIELDS:
        twin[k] = parent.get(k)
    if parent.get("identity_unqualified_reason"):
        twin["identity_unqualified_reason"] = parent["identity_unqualified_reason"]
    twin["pair"] = parent.get("id")
    twin["identity_coin_state_at_entry"] = auth.state(coin)
    return twin


def qualified(tr):
    """Whether a paper trade belongs to the forward evidence record: complete entry-time proof of VERIFIED_CRYPTO."""
    return (tr.get("identity_qualified") is True and tr.get("identity_state_at_entry") == ID.VERIFIED_CRYPTO
            and bool(tr.get("identity_scan_id")) and bool(tr.get("identity_version")))


def unqualified_reason(tr):
    return None if qualified(tr) else (tr.get("identity_unqualified_reason") or IDENTITY_PROOF_INCOMPLETE)


def mark_legacy(trades):
    """Trades without entry-time identity provenance are kept unchanged and marked identity_qualified=False,
    LEGACY_NO_IDENTITY_PROOF. Nothing is inferred from the coin's current identity. Returns the number newly
    marked (0 once a journal has been migrated)."""
    n = 0
    for tr in trades:
        if "identity_qualified" not in tr:
            tr["identity_state_at_entry"] = None
            tr["identity_qualified"] = False
            tr["identity_unqualified_reason"] = LEGACY_NO_IDENTITY_PROOF
            n += 1
    return n


def proof_complete(tr):
    """Whether a trade carries every entry-time identity field (qualified or not)."""
    return all(k in tr for k in TRADE_IDENTITY_FIELDS) and bool(tr.get("identity_scan_id")) \
        and bool(tr.get("identity_version"))
