"""Canonical contract registry: every market the eight DEX market-list endpoints returned.

A contract's identity is venue + raw symbol (`hyperliquid:kPEPE`, `aster:BBUSDT`). Records are never collapsed by
ticker: two venues listing the same ticker are two contracts, and so are two markets of one venue that map to the
same canonical asset. The registry re-reads the payloads the legacy adapters already fetched (no extra request),
including the markets the adapters skip, and then reconciles each record with what the universe did with it
(skipped, selected, duplicate not selected, dropped as a price conflict, or - since Phase 2 - kept out as part of a
separate exposure of its ticker), with the identity decision of v8.identity: the contract's own classification and
reason, its price per 1 coin, its exposure, the exposure's class, and whether it was admitted to the crypto universe.

Observational only: nothing here is read by the engines. The registry's own reading of a raw market is checked
against the adapter's output on every scan, and the identity's per-contract state against the coin records; a
disagreement is recorded as AUDIT_ADAPTER_MISMATCH."""
from __future__ import annotations

import re

from . import health as H
from . import identity as ID

MARKET_LIST = {   # venue -> funding settlement interval in hours where the venue documents it in the payload's terms
    "hyperliquid": 1, "dydx": 1, "variational": None, "aster": None, "edgex": None, "lighter": None,
    "paradex": None, "extended": None}


def _sc():
    import scanner as sc
    return sc


# --------------------------------------------------------------------------- classification helpers
def tradfi_reason(t, name=None):
    """(is_tradfi, reason) mirroring scanner.is_tradfi(t, name) exactly, with the rule that decided it."""
    sc = _sc()
    if t in sc.TRADFI:
        return True, "TRADFI_LIST"
    if sc.is_fx(t):
        return True, "FX_PAIR"
    if t in sc.KNOWN_CRYPTO:
        return False, "KNOWN_CRYPTO"
    if name:
        m = sc.TRADFI_NAME.search(name)
        if m:
            return True, "NAME_PATTERN:" + m.group(0).lower()
    return False, "DEFAULT_CRYPTO"


def canon_reason(norm):
    """(asset, multiplier, reason): scanner.canon(norm) and which rule produced it."""
    sc = _sc()
    t, mult = sc.canon(norm)
    u = str(norm).strip()
    if u.upper() in sc.ALIAS:
        return t, mult, "ALIAS:" + u.upper()
    base, m = sc.mult_split(u)
    if base in sc.ALIAS:
        return t, mult, f"MULTIPLIER_ALIAS:{base}x{m:g}"
    if m != 1.0:
        return t, mult, f"MULTIPLIER:x{m:g}"
    if t != u:
        return t, mult, "UPPERCASE"
    return t, mult, "IDENTITY"


# --------------------------------------------------------------------------- per-venue readers of raw payloads
def _f(x):
    return _sc().fnum(x)


def _rec(venue, raw, norm, mtype, active, skip, price=None, vol=None, oi=None, fund8h=None, tradfi=None,
         tradfi_why=None, name=None, rcv=None, status=None, vmeta=None):
    return {"venue": venue, "raw": raw, "norm": norm, "type": mtype, "active": active, "status": status,
            "skip": skip, "price": price, "vol": vol, "oi": oi, "fund8h": fund8h, "tradfi_override": tradfi,
            "tradfi_why": tradfi_why, "name": name, "rcv": rcv, "vmeta": vmeta}


# identity-relevant raw fields each venue's market list sends (v8 Phase 3). Recorded as observed, per contract, so
# a scan shows what each venue says about its instruments. Only the fields named in v8.identity's rules decide
# anything (Extended category, Aster underlyingType, the venue symbol, the contract name); the rest is evidence for
# review, never authority.
def _vm(src, keys):
    out = {}
    for k in keys:
        v = (src or {}).get(k)
        if v not in (None, "", [], {}):
            out[k] = v
    return out or None


def read_hyperliquid(p):
    rcv, d = p.get("meta", (None, None))
    out = []
    if not isinstance(d, list) or len(d) < 2:
        return out
    meta, ctxs = d[0] or {}, d[1] or []
    for asset, ctx in zip(meta.get("universe") or [], ctxs):
        name = str(asset.get("name", ""))
        skip = "EMPTY_SYMBOL" if not name else "HL_BUILDER_MARKET" if ":" in name else \
            "DELISTED" if asset.get("isDelisted") else None
        px = _f(ctx.get("markPx")) or _f(ctx.get("oraclePx"))
        oi_b, fr = _f(ctx.get("openInterest")), _f(ctx.get("funding"))
        out.append(_rec("hyperliquid", name, name, "perp", not asset.get("isDelisted"), skip, price=px,
                        vol=_f(ctx.get("dayNtlVlm")), oi=oi_b * px if oi_b is not None and px else None,
                        fund8h=fr * 8 if fr is not None else None, rcv=rcv,
                        status="delisted" if asset.get("isDelisted") else "listed"))
    return out


def read_variational(p):
    rcv, d = p.get("stats", (None, None))
    out = []
    for L in (d or {}).get("listings") or []:
        sym = str(L.get("ticker", "")).strip()
        oi = L.get("open_interest") or {}
        lo, so = _f(oi.get("long_open_interest")), _f(oi.get("short_open_interest"))
        apr = _f(L.get("funding_rate"))
        out.append(_rec("variational", sym, sym, "perp", True, None if sym else "EMPTY_SYMBOL",
                        price=_f(L.get("mark_price")), vol=_f(L.get("volume_24h")),
                        oi=(lo or 0) + (so or 0) if lo is not None else None,
                        fund8h=apr * 8 / 8760 if apr is not None else None, name=L.get("name") or sym, rcv=rcv,
                        status="listed", vmeta=_vm(L, ("name",))))
    return out


def read_aster(p):
    rcv, info = p.get("info", (None, None))
    tick = {x["symbol"]: x for x in (p.get("ticker", (None, None))[1] or []) if isinstance(x, dict) and "symbol" in x}
    prem = {x["symbol"]: x for x in (p.get("premium", (None, None))[1] or []) if isinstance(x, dict) and "symbol" in x}
    out = []
    for s in (info or {}).get("symbols") or []:
        ct, st = s.get("contractType", "PERPETUAL"), s.get("status", "TRADING")
        skip = "NOT_PERPETUAL" if ct != "PERPETUAL" else "NOT_TRADING" if st != "TRADING" else None
        sym = s.get("symbol", "")
        base = s.get("baseAsset") or re.sub(r"(USDT|USDC|USD)$", "", sym)
        tk, pr = tick.get(sym, {}), prem.get(sym, {})
        ut = s.get("underlyingType")
        out.append(_rec("aster", sym, base, "perp" if ct == "PERPETUAL" else str(ct).lower(), st == "TRADING", skip,
                        price=_f(tk.get("lastPrice")) or _f(pr.get("markPrice")), vol=_f(tk.get("quoteVolume")),
                        fund8h=_f(pr.get("lastFundingRate")), tradfi=True if ut and ut != "COIN" else None,
                        tradfi_why=f"VENUE_UNDERLYING:{ut}" if ut and ut != "COIN" else None, rcv=rcv, status=st,
                        vmeta=_vm(s, ("baseAsset", "quoteAsset", "marginAsset", "underlyingType",
                                      "underlyingSubType"))))
    return out


def read_edgex(p):
    rcv, d = p.get("meta", (None, None))
    out = []
    for c in (((d or {}).get("data") or {}).get("contractList")) or []:
        name = str(c.get("contractName") or "")
        base = re.sub(r"(USDT|USDC|USD)$", "", name.upper().replace("-PERP", "").replace("-", "").replace("_", ""))
        off = c.get("enableTrade") is False or c.get("enableDisplay") is False
        skip = "NOT_TRADING" if off else "EMPTY_SYMBOL" if not base else None
        out.append(_rec("edgex", name, base, "perp", not off, skip, rcv=rcv,
                        status="enabled" if not off else "disabled"))
    return out


def read_lighter(p):
    rcv, d = p.get("books", (None, None))
    lst = (d or {}).get("order_book_details") or (d or {}).get("order_books") or []
    out = []
    for b in lst:
        mt, st = b.get("market_type", "perp"), b.get("status", "active")
        sym = str(b.get("symbol", ""))
        skip = "NOT_PERPETUAL" if mt != "perp" else "NOT_TRADING" if st != "active" else \
            "EMPTY_SYMBOL" if not sym else None
        cfgm = b.get("market_config") if isinstance(b.get("market_config"), dict) else {}
        vm = _vm(b, ("market_flags", "strategy_index")) or {}
        vm.update(_vm(cfgm, ("trading_hours", "insurance_fund_account_index")) or {})
        out.append(_rec("lighter", sym, sym, str(mt), st == "active", skip,
                        price=_f(b.get("mark_price")) or _f(b.get("last_trade_price")),
                        vol=_f(b.get("daily_quote_token_volume")), rcv=rcv, status=st, vmeta=vm or None))
    return out


def read_dydx(p):
    rcv, d = p.get("markets", (None, None))
    out = []
    for tk, m in ((d or {}).get("markets") or {}).items():
        st = m.get("status")
        px, oi_b, fr = _f(m.get("oraclePrice")), _f(m.get("openInterest")), _f(m.get("nextFundingRate"))
        out.append(_rec("dydx", tk, tk.split("-")[0], "perp", st == "ACTIVE", None if st == "ACTIVE" else "NOT_TRADING",
                        price=px, vol=_f(m.get("volume24H")), oi=oi_b * px if oi_b is not None and px else None,
                        fund8h=fr * 8 if fr is not None else None, rcv=rcv, status=st))
    return out


def read_paradex(p):
    rcv, d = p.get("summary", (None, None))
    out = []
    for r in (d or {}).get("results") or []:
        sym = str(r.get("symbol", ""))
        perp = sym.endswith("-PERP")
        px = _f(r.get("mark_price")) or _f(r.get("last_traded_price"))
        oi_b = _f(r.get("open_interest"))
        out.append(_rec("paradex", sym, sym.split("-")[0], "perp" if perp else "other", True,
                        None if perp else "NOT_PERPETUAL", price=px, vol=_f(r.get("volume_24h")),
                        oi=oi_b * px if oi_b is not None and px else None, fund8h=_f(r.get("funding_rate")), rcv=rcv,
                        status="listed"))
    return out


def read_extended(p):
    rcv, d = p.get("markets", (None, None))
    out = []
    for m in (d or {}).get("data") or []:
        off = m.get("active") is False or m.get("status", "ACTIVE") != "ACTIVE"
        notperp = bool(m.get("type")) and m["type"] != "PERPETUAL"
        name = str(m.get("name", ""))
        st = m.get("marketStats") or {}
        fr = _f(st.get("fundingRate"))
        cat = m.get("category")
        tf = (cat and cat != "Crypto") or "_24_5" in name
        why = (f"VENUE_CATEGORY:{cat}" if cat and cat != "Crypto" else "VENUE_24_5_MARKET") if tf else None
        out.append(_rec("extended", name, m.get("assetName") or name.split("-")[0],
                        "perp" if not m.get("type") or m["type"] == "PERPETUAL" else str(m["type"]).lower(),
                        not off, "NOT_TRADING" if off else "NOT_PERPETUAL" if notperp else None,
                        price=_f(st.get("markPrice")) or _f(st.get("lastPrice")), vol=_f(st.get("dailyVolume")),
                        oi=_f(st.get("openInterest")), fund8h=fr * 8 if fr is not None else None,
                        tradfi=True if tf else None, tradfi_why=why, name=m.get("description"), rcv=rcv,
                        status=m.get("status", "ACTIVE") if m.get("active") is not False else "inactive",
                        vmeta=_vm(m, ("category", "assetName", "description"))))
    return out


READERS = {"hyperliquid": read_hyperliquid, "variational": read_variational, "aster": read_aster,
           "edgex": read_edgex, "lighter": read_lighter, "dydx": read_dydx, "paradex": read_paradex,
           "extended": read_extended}


# --------------------------------------------------------------------------- the registry
def build(trace, coins, dex_status, dex_ok, scan_ts):
    """Contracts and assets from one scanner run.

    trace: the Recorder after build_universe(); coins/dex_status/dex_ok: what build_universe() returned (the same
    call, so venue rows can be matched by identity). Returns {"contracts": [...], "assets": {...}, "venues": {...},
    "events": [...]}."""
    sc = _sc()
    contracts, venues, seen_ids = [], {}, {}
    ident = getattr(trace, "ident", None)
    for dex in sc.DEXES:
        payload = trace.payloads.get(dex)
        rows = trace.rows.get(dex)
        vinfo = {"ok": bool((dex_status.get(dex) or {}).get("ok")), "raw": 0, "kept": 0, "skipped": 0,
                 "mismatch": 0, "payload": bool(payload)}
        venues[dex] = vinfo
        if not payload:
            continue
        try:
            recs = READERS[dex](payload)
        except Exception as e:  # noqa: BLE001 - an unreadable payload is a registry gap, never a scan failure
            vinfo["error"] = f"{type(e).__name__}: {e}"[:200]
            continue
        # legacy adapter rows of this venue, matched to raw records by symbol in order
        pool = {}
        for i, r in enumerate(rows or []):
            pool.setdefault(r.get("sym"), []).append(i)
        for rec in recs:
            vinfo["raw"] += 1
            asset, mult, why = canon_reason(rec["norm"])
            cid = f"{dex}:{rec['raw']}"
            if cid in seen_ids:                       # never collapse: same raw symbol twice in one payload
                seen_ids[cid] += 1
                cid = f"{cid}#{seen_ids[cid]}"
            else:
                seen_ids[cid] = 1
            row_i, info = None, None
            if rec["skip"] is None:
                lst = pool.get(rec["raw"])
                row_i = lst.pop(0) if lst else None
            if rec["skip"] is not None:
                legacy = rec["skip"]
                vinfo["skipped"] += 1
            elif rows is None:
                legacy = "ADAPTER_FAILED"
            elif row_i is None:
                legacy = "AUDIT_ADAPTER_MISMATCH"
                vinfo["mismatch"] += 1
            else:
                vinfo["kept"] += 1
                row = rows[row_i]
                c = coins.get(row["t"]) if isinstance(coins, dict) else None
                info = ident.rows.get((dex, row_i)) if ident is not None else None
                in_coin = c is not None and (c.get("venues") or {}).get(dex) is row
                if info is None or (info["state"] == ID.SELECTED) != in_coin:
                    legacy = "AUDIT_ADAPTER_MISMATCH"       # the identity's state disagrees with the coin record
                    vinfo["mismatch"] += 1
                else:
                    legacy = info["state"]
                if row["t"] != asset or abs((row.get("mult") or 1.0) - mult) > 1e-12:
                    legacy, vinfo["mismatch"] = "AUDIT_ADAPTER_MISMATCH", vinfo["mismatch"] + 1
                elif rec["tradfi_override"] is None and bool(row.get("tradfi")) != tradfi_reason(asset, rec.get("name"))[0]:
                    legacy, vinfo["mismatch"] = "AUDIT_ADAPTER_MISMATCH", vinfo["mismatch"] + 1
            if rec["tradfi_override"] is not None:
                tf, tf_why = rec["tradfi_override"], rec["tradfi_why"]
            else:
                tf, tf_why = tradfi_reason(asset, rec.get("name"))
            pb, vb = H.basis(rec["price"]), H.basis(rec["vol"])
            fb, ob = H.basis(rec["fund8h"]), H.basis(rec["oi"])
            basis = {k: b for k, b in (("price", pb), ("vol", vb), ("oi", ob), ("fund8h", fb))
                     if b != H.OBSERVED}
            contracts.append({
                "id": cid, "venue": dex, "raw": rec["raw"], "norm": rec["norm"], "asset": asset, "mult": mult,
                "canon": why, "type": rec["type"], "active": rec["active"], "status": rec["status"],
                "tradfi": bool(tf), "tradfi_reason": tf_why, "price": _r(rec["price"]), "vol": _r(rec["vol"]),
                "oi": _r(rec["oi"]), "fund8h": _r(rec["fund8h"], 9), "fund_iv_h": MARKET_LIST.get(dex),
                "src_ts": None, "rcv_ts": int(rec["rcv"]) if rec["rcv"] else None,
                "health": H.contract_state(pb, vb, conflicted=legacy == "PRICE_CONFLICT_DROPPED"),
                "basis": basis, "legacy": legacy, "first_seen": None,
                # v8 Phase 2 identity (None for contracts the adapters skip)
                "cls": (info or {}).get("cls"), "cls_reason": (info or {}).get("why"),
                "cls_auth": (info or {}).get("auth"), "npx": _r((info or {}).get("npx")),
                "exposure": (info or {}).get("exp"), "exp_class": (info or {}).get("exp_cls"),
                "exp_reason": (info or {}).get("exp_why"), "admitted": (info or {}).get("admitted"),
                "inherited_from": (info or {}).get("inherited_from"), "meta": (info or {}).get("meta"),
                # v8 Phase 3 identity: the exposure's state, whether the contract is in the coin record, every piece of
                # contract evidence, the parsed venue symbol and its link, and the raw venue identity fields
                "exp_state": (info or {}).get("exp_state"), "in_record": (info or {}).get("in_record"),
                "evidence": (info or {}).get("evidence"), "parsed": (info or {}).get("parsed"),
                "link": (info or {}).get("link"), "vmeta": rec.get("vmeta"),
                # v8 Phase 4: observed candidate evidence (never authority; see v8.identity.CANDIDATE_FIELDS)
                "candidate": ID.candidate_evidence(dex, rec.get("vmeta")) or None})
        # adapter rows the registry could not match to any raw record
        left = sum(len(v) for v in pool.values())
        if left:
            vinfo["mismatch"] += left
            vinfo["unmatched_rows"] = left
    assets = asset_summary(contracts, coins, dex_ok, ident)
    events = [[code, kw] for code, kw in trace.events]
    return {"contracts": contracts, "assets": assets, "venues": venues, "events": events,
            "fallback": not dex_ok, "scan_ts": scan_ts}


def _r(x, nd=8):
    if x is None:
        return None
    try:
        return float(f"{float(x):.{nd}g}")
    except (TypeError, ValueError):
        return None


def asset_summary(contracts, coins, dex_ok, ident=None):
    """Per canonical asset: its contracts, how the universe classified it (CRYPTO, TRADFI, AMBIGUOUS or why it has
    no coin), the identity decision with every exposure, and whether its contracts collide (disagree)."""
    by = {}
    for c in contracts:
        a = by.setdefault(c["asset"], {"contracts": [], "venues": set(), "norms": set(), "kept_crypto": False,
                                       "kept_tradfi": False, "any_kept": False, "failed": False, "candidate": []})
        if c["legacy"] == "ADAPTER_FAILED":
            a["failed"] = True
        a["contracts"].append(c["id"])
        if c.get("candidate") and c["legacy"] in ID.KEPT_STATES:
            a["candidate"].extend([c["id"], f, v] for f, v in c["candidate"])
        a["venues"].add(c["venue"])
        a["norms"].add(c["norm"])
        if c["legacy"] in ID.KEPT_STATES:
            a["any_kept"] = True
        if c["legacy"] == "SELECTED":
            a["kept_tradfi" if c["tradfi"] else "kept_crypto"] = True
    out = {}
    coins = coins if isinstance(coins, dict) else {}
    for t, a in by.items():
        c = coins.get(t)
        info = ident.asset(t) if ident is not None else None
        if c is not None:
            if c.get("tradfi"):
                state = "AMBIGUOUS" if info is not None and info["decision"] == ID.D_AMBIGUOUS else "TRADFI"
            elif ID.execution_identity_eligible(c):
                state = "CRYPTO"
            else:
                state = "UNVERIFIED"          # in the universe, not tradfi, no crypto execution identity (Phase 3)
        elif a["failed"] and not a["any_kept"]:
            state = "VENUE_ADAPTER_FAILED"
        elif not a["any_kept"]:
            state = "NO_ACTIVE_PERP_CONTRACT"
        else:
            state = "PRICE_CONFLICT_ALL_VENUES"
        out[t] = {"contracts": a["contracts"], "venues": sorted(a["venues"]), "legacy": state,
                  "collision": bool(info and info["collision"]),
                  "aliases": sorted(a["norms"]) if len(a["norms"]) > 1 else None,
                  "identity": (_identity_block(info, c) if info is not None else None),
                  # v8 Phase 4: observed candidate evidence, apart from the authoritative identity evidence above
                  "candidate_evidence": ({"observed": a["candidate"], "authority": False,
                                          "status": ID.CANDIDATE_STATUS,
                                          "qualified_rules": list(ID.QUALIFIED_CRYPTO_RULES)}
                                         if a["candidate"] else None)}
    for t, c in coins.items():   # the fallback universe has coins without any contract
        if t not in out:
            out[t] = {"contracts": [], "venues": [], "legacy": "TRADFI" if c.get("tradfi") else "CRYPTO",
                      "collision": False, "aliases": None, "fallback": not dex_ok, "identity": None}
    return out


def _identity_block(info, coin):
    """The asset's identity as the audit shows it: Input -> Rule -> Result -> Effect (v8 Phase 3)."""
    return {"state": info.get("state"), "decision": info["decision"], "authority": info.get("authority"),
            "reason": info.get("reason"), "ticker_list": info["ticker_list"], "evidence": info.get("evidence") or [],
            "discovery_eligible": bool(info.get("discovery_eligible")) and bool((coin or {}).get("venues")),
            "execution_identity_eligible": ID.execution_identity_eligible(coin),
            "promotion": info.get("promotion"), "links": info.get("links"),
            "excluded_unverified": info.get("excluded_unverified"),
            "phase1": "TRADFI" if info.get("phase1_tradfi") else "CRYPTO",
            "phase2": (info.get("phase2") or {}).get("state"),
            "phase2_reasons": (info.get("phase2") or {}).get("reasons"), "exposures": info["exposures"]}


def counts(reg):
    """Headline counts of a registry."""
    cs = reg.get("contracts") or []
    assets = reg.get("assets") or {}
    by_legacy, by_venue, by_health = {}, {}, {}
    for c in cs:
        by_legacy[c["legacy"]] = by_legacy.get(c["legacy"], 0) + 1
        by_venue[c["venue"]] = by_venue.get(c["venue"], 0) + 1
        by_health[c["health"]] = by_health.get(c["health"], 0) + 1
    st, dec = {}, {}
    for a in assets.values():
        st[a["legacy"]] = st.get(a["legacy"], 0) + 1
        d = (a.get("identity") or {}).get("decision")
        if d:
            dec[d] = dec.get(d, 0) + 1
    return {"raw_contracts": len(cs), "active_perps": sum(1 for c in cs if c["type"] == "perp" and c["active"]),
            "selected": by_legacy.get("SELECTED", 0), "by_legacy_state": dict(sorted(by_legacy.items())),
            "by_venue": dict(sorted(by_venue.items())), "by_health": dict(sorted(by_health.items())),
            "canonical_assets": len(assets), "assets_by_legacy": dict(sorted(st.items())),
            "tradfi_collisions": sorted(t for t, a in assets.items() if a.get("collision")),
            "assets_by_identity": dict(sorted(dec.items())), "identity_version": ID.VERSION,
            "crypto_exposure_selected": sorted(t for t, a in assets.items()
                                               if (a.get("identity") or {}).get("decision") == ID.D_SELECTED),
            "ambiguous": sorted(t for t, a in assets.items() if a.get("legacy") == "AMBIGUOUS"),
            # before/after on the same market lists: the Phase 1 ticker-level OR vs the Phase 2 identity
            "phase1_crypto": sum(1 for a in assets.values() if (a.get("identity") or {}).get("phase1") == "CRYPTO"),
            "phase1_excluded": sum(1 for a in assets.values() if (a.get("identity") or {}).get("phase1") == "TRADFI"),
            "now_crypto": sum(1 for a in assets.values() if a.get("identity") and a.get("legacy") == "CRYPTO"),
            "now_excluded": sum(1 for a in assets.values() if a.get("identity") and a.get("legacy") in ("TRADFI", "AMBIGUOUS")),
            # Phase 2 counts kept for continuity: legacy "CRYPTO" now means VERIFIED_CRYPTO only
            "changed_vs_phase1": sorted(t for t, a in assets.items() if a.get("identity") and
                                        (a["identity"]["phase1"] == "CRYPTO") != (a.get("legacy") == "CRYPTO")),
            "by_contract_class": _count(cs, "cls"), "by_exposure_class": _count(cs, "exp_class"),
            "multi_symbol_assets": sorted(t for t, a in assets.items() if a.get("aliases")),
            **identity_counts(assets, cs),
            "alias_mapped": sorted({c["id"] for c in cs if str(c.get("canon", "")).startswith(("ALIAS", "MULTIPLIER_ALIAS"))}),
            "adapter_mismatches": by_legacy.get("AUDIT_ADAPTER_MISMATCH", 0)}


def identity_counts(assets, cs):
    """v8 Phase 3: the four identity states, discovery vs execution identity, and the before/after against the
    Phase 2 identity on the same market lists (default-crypto inventory)."""
    idents = {t: a["identity"] for t, a in assets.items() if a.get("identity")}
    by_state = {st: 0 for st in ID.STATES}
    for i in idents.values():
        if i.get("state") in by_state:
            by_state[i["state"]] += 1
    p2_default_only = sorted(t for t, i in idents.items() if i.get("phase2") == "CRYPTO"
                             and (i.get("phase2_reasons") or []) == ["DEFAULT_CRYPTO"])
    p2_default_any = sorted(t for t, i in idents.items() if i.get("phase2") == "CRYPTO"
                            and "DEFAULT_CRYPTO" in (i.get("phase2_reasons") or []))
    p2_to_state = {}
    for t in p2_default_any:
        st = idents[t].get("state")
        p2_to_state.setdefault(st, []).append(t)
    p2map = {"CRYPTO": ID.VERIFIED_CRYPTO, "TRADFI": ID.VERIFIED_TRADFI, "AMBIGUOUS": ID.AMBIGUOUS}
    changed = sorted(t for t, i in idents.items() if i.get("phase2") and p2map.get(i["phase2"]) != i.get("state"))
    active = [c for c in cs if c.get("type") == "perp" and c.get("active")]
    return {"identity_states": by_state,
            "unverified_assets": sorted(t for t, i in idents.items() if i.get("state") == ID.UNVERIFIED),
            "discovery_visible_assets": sum(1 for i in idents.values() if i.get("discovery_eligible")),
            "discovery_visible_contracts": sum(1 for c in active if c.get("legacy") in ID.KEPT_STATES),
            "execution_identity_eligible": sum(1 for i in idents.values() if i.get("execution_identity_eligible")),
            "phase2_states": {k: sum(1 for i in idents.values() if i.get("phase2") == k)
                              for k in ("CRYPTO", "TRADFI", "AMBIGUOUS")},
            "phase2_default_crypto_only": p2_default_only, "phase2_default_crypto_any": p2_default_any,
            "phase2_default_crypto_now": {k: sorted(v) for k, v in sorted(p2_to_state.items())},
            "changed_vs_phase2": changed,
            "changed_vs_phase2_detail": {t: [idents[t].get("phase2"), idents[t].get("state")] for t in changed},
            "parsed_symbol_links": sorted(c["id"] for c in cs if c.get("link")),
            "now_unverified": by_state[ID.UNVERIFIED],
            "candidate_evidence": candidate_counts(assets, cs)}


def candidate_counts(assets, cs):
    """v8 Phase 4: the candidate-evidence census of this scan: every venue.field=value observed on a kept contract, by
    the identity state of its exposure, so each audit snapshot adds one observation of how the candidate values line
    up with verified identity (none is authority: qualified_rules is empty)."""
    cross = {}
    for c in cs:
        if c.get("legacy") not in ID.KEPT_STATES:
            continue
        for f, v in c.get("candidate") or []:
            k = f"{c['venue']}.{f}={v}"
            st = c.get("exp_state") or "NONE"
            cross.setdefault(k, {}).setdefault(st, 0)
            cross[k][st] += 1
    unv = [t for t, a in assets.items() if (a.get("identity") or {}).get("state") == ID.UNVERIFIED]
    return {"qualified_rules": list(ID.QUALIFIED_CRYPTO_RULES), "status": ID.CANDIDATE_STATUS,
            "by_value_and_exposure_state": {k: dict(sorted(v.items())) for k, v in sorted(cross.items())},
            "unverified_with_candidate": sorted(t for t in unv if assets[t].get("candidate_evidence")),
            "unverified_without_candidate": sorted(t for t in unv if not assets[t].get("candidate_evidence"))}


def _count(cs, k):
    out = {}
    for c in cs:
        v = c.get(k)
        if v is not None:
            out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items()))
