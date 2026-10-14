"""Reviewed deployment authority; research never writes this policy. Standard library only.

An ACTIVE_REQUALIFIED promotion is bound three ways - reviewed evidence == adjudication row == the code running now - on
three independent identities:

    runtime_definition_hash         digest of the runtime metadata STRATS[sid] (name, tf, kind, desc, params)
    adjudicated_definition_hash     digest of the exact research definition (implementation, params, code)
    runtime_implementation_hash     digest of the bytes of the runtime implementation manifest below

The runtime implementation manifest is RUNTIME_IMPLEMENTATION_FILES. quant.py holds everything that turns bars into a
deployed strategy's trades: the STRATS metadata, the indicators (_ewm, ema, wilder, atr, adx, ret, rstd, to_daily),
the signal functions (sig_tsmom, sig_trend_ema, xs_scores), the stop and trailing logic (_stop), slippage (slip_of),
eligibility, and trade management (sim_trade and the run loop's entry/exit rules). Hashing its exact bytes means any
edit to it - a strategy's or not - invalidates every promotion until a review is regenerated (fail closed).

v9 probation tier (ACTIVE_PROBATION / PROBATION). A strategy side that the survivorship-free archive confirms
(tools/v9/confirm.py, research/v9/probation_evidence.json, v9.probation-evidence/1) may be deployed at a reduced size
before the full Phase 9 requalification is possible. Its row carries a `probation` record, validated fail closed:

    sides             the confirmed sides only ("long" / "short"); the other side of the strategy stays WATCH
    risk_multiplier   in (0, MAX_PROBATION_RISK_MULTIPLIER]: probation never trades at full size
    evidence          {path, sha256}: the bound evidence file; every listed side must be CONFIRMED in it, for the
                      runtime definition (digest of STRATS[sid]) and runtime implementation hash running now
    forward_tests     {side: {experiment_id, path, sha256, effective_from}}: the shadow-ledger REGISTRATION of each
                      side's forward test, registered before its evaluation starts; effective_from is its
                      evaluation_start (the first signal that counts, and the start of the governed book)

Changing quant.py therefore invalidates a probation until the evidence is re-bound (python tools/v9/confirm.py
--from-branch evidence-results), exactly as it invalidates an ACTIVE_REQUALIFIED promotion.

Excluded, with the reason each is not part of a strategy's runtime definition:
    scanner.py              market-data acquisition, bar cleaning and the shared crypto universe/identity/liquidity
                            gates used by every engine; it decides which coins and bars exist, not how a strategy
                            trades them, and is versioned and hashed by the audit (identity_config_hash, config_hash)
    v8/evidence.py          the shared identity execution gate (v8.identity) and entry-time proof stamps on journal
                            records; it decides whether a coin is verified crypto for every engine, not a strategy's
                            signal, stop, size or exit
    v8/strategy_policy.py   this file and quant_strategy_policy.json: the deployment authority itself, whose content
                            is validated here and hashed separately (runtime_policy_hash)
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

VERSION = "v8.quant-strategy-policy/2"       # /2: the v9 ACTIVE_PROBATION deployment state and its probation record
PATH = Path(__file__).with_name("quant_strategy_policy.json")
DEPLOYMENT = {"LEGACY_HOLDOVER", "ACTIVE_REQUALIFIED", "ACTIVE_PROBATION", "PAPER_ONLY", "DISABLED"}
RESEARCH = {"REQUALIFIED", "PROBATION", "REJECTED", "INSUFFICIENT_EVIDENCE", "INVALIDATED"}
ENABLED = {"LEGACY_HOLDOVER", "ACTIVE_REQUALIFIED", "ACTIVE_PROBATION"}
REPO_ROOT = PATH.parent.parent
RUNTIME_IMPLEMENTATION_FILES = ("quant.py",)
PROBATION_EVIDENCE_SCHEMA = "v9.probation-evidence/1"
MAX_PROBATION_RISK_MULTIPLIER = 0.5
PROBATION_KEYS = {"sides", "risk_multiplier", "evidence", "forward_tests"}
FORWARD_TEST_KEYS = {"experiment_id", "path", "sha256", "effective_from"}
LEDGER_DIR = "research/shadow-ledger"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def adjudicated_definition_hash(row):
    """Bind the exact research representation, independently of runtime metadata."""
    fields = ("strategy_id", "implementation", "params", "parameter_hash", "code_hash", "code_files")
    if not isinstance(row, dict) or any(k not in row or row[k] is None for k in fields):
        raise ValueError("STRATEGY_POLICY_INVALID: adjudicated definition fields missing")
    return digest({k: row[k] for k in fields})


def runtime_implementation_hash(root=REPO_ROOT, files=RUNTIME_IMPLEMENTATION_FILES):
    """Digest of the exact bytes of every runtime implementation file, keyed by repository-relative path."""
    base = Path(root)
    return digest({name: hashlib.sha256((base / name).read_bytes()).hexdigest() for name in files})


def validate(policy, strats, root=None, runtime_root=None):
    """No fallback. Promotion references an in-repository, hash-bound reviewed evidence record.

    `root` holds the reviewed evidence and adjudication files; `runtime_root` holds the runtime implementation that is
    hashed (default: this repository, i.e. the code quant.py runs)."""
    def require(ok, message):
        if not ok:
            raise ValueError("STRATEGY_POLICY_INVALID: " + message)
    require(isinstance(policy, dict) and policy.get("schema") == VERSION, "schema")
    rows, order = policy.get("strategies"), policy.get("runtime_order")
    require(isinstance(rows, list) and isinstance(order, list), "strategy list / order")
    ids = []
    enabled = []
    for row in rows:
        require(isinstance(row, dict), "strategy record")
        sid = row.get("strategy_id")
        require(isinstance(sid, str) and bool(sid) and sid not in ids, "unique strategy ID")
        ids.append(sid)
        ds, rs = row.get("deployment_state"), row.get("research_state")
        require(isinstance(ds, str) and ds in DEPLOYMENT and isinstance(rs, str) and rs in RESEARCH, "states")
        if ds in ENABLED or ds == "PAPER_ONLY":
            require(sid in strats, "deployed ID absent from STRATS")
        if ds in ENABLED:
            enabled.append(sid)
        if ds == "ACTIVE_REQUALIFIED":
            require(rs == "REQUALIFIED", "active without requalification")
            ref = row.get("reviewed_evidence")
            require(isinstance(ref, dict) and root is not None, "reviewed evidence required")
            base = Path(root).resolve()
            name = ref.get("path")
            require(isinstance(name, str), "evidence path")
            path = (base / name).resolve()
            require(path.is_relative_to(base) and path.is_file(), "evidence path outside repository or missing")
            raw = path.read_bytes()
            require(hashlib.sha256(raw).hexdigest() == ref.get("sha256"), "evidence hash")
            ev = json.loads(raw)
            require(ev.get("schema") == "v8.reviewed-strategy-evidence/1" and
                    ev.get("strategy_id") == sid and ev.get("research_state") == "REQUALIFIED" and
                    ev.get("blocking_reasons") == [] and ev.get("review_decision") == "APPROVED" and
                    isinstance(ev.get("review_url"), str) and
                    ev["review_url"].startswith("https://github.com/blazebrt/perp-dex-radar/pull/") and
                    isinstance(ev.get("adjudication_sha256"), str) and len(ev["adjudication_sha256"]) == 64,
                    "reviewed evidence content")
            artifact_name = ev.get("adjudication_path")
            require(isinstance(artifact_name, str), "adjudication path")
            artifact_path = (base / artifact_name).resolve()
            require(artifact_path.is_relative_to(base) and artifact_path.is_file(), "adjudication file missing")
            artifact_raw = artifact_path.read_bytes()
            require(hashlib.sha256(artifact_raw).hexdigest() == ev["adjudication_sha256"], "adjudication hash")
            artifact = json.loads(artifact_raw)
            from .strategy_authority import VERSION as authority_version, adjudicate
            require(artifact.get("schema") == authority_version, "adjudication schema")
            matches = [r for r in artifact.get("strategies", []) if r.get("strategy_id") == sid]
            require(len(matches) == 1 and isinstance(matches[0], dict), "adjudication row")
            adjudicated = matches[0]
            # Re-run the current gate against the exact bound adjudicated definition (its sides come from it).
            require(adjudicated.get("research_state") == "REQUALIFIED" and
                    adjudicate(adjudicated.get("evidence", {}), adjudicated)["research_state"] == "REQUALIFIED",
                    "adjudication does not satisfy current gate")
            require(ev.get("runtime_definition_hash") == adjudicated.get("runtime_definition_hash") == digest(strats[sid]),
                    "runtime definition differs between runtime, review and adjudication")
            definition_hash = adjudicated_definition_hash(adjudicated)
            require(ev.get("adjudicated_definition_hash") == adjudicated.get("adjudicated_definition_hash") == definition_hash,
                    "adjudicated definition differs from review or row content")
            try:
                current_implementation = runtime_implementation_hash(REPO_ROOT if runtime_root is None else runtime_root)
            except OSError:
                current_implementation = None
            require(current_implementation is not None and
                    ev.get("runtime_implementation_hash") == adjudicated.get("runtime_implementation_hash")
                    == current_implementation,
                    "runtime implementation differs between runtime, review and adjudication")
        if ds == "ACTIVE_PROBATION":
            require(rs == "PROBATION", "active probation without the PROBATION research state")
            require(root is not None, "probation evidence required")
            _validate_probation(sid, row.get("probation"), strats, Path(root).resolve(), runtime_root, require)
        else:
            require("probation" not in row, "a probation record on a row that is not ACTIVE_PROBATION")
    require(all(isinstance(s, str) for s in order) and len(set(order)) == len(order), "duplicate or invalid order")
    require(set(order) == set(enabled), "order must contain every deployment-enabled strategy exactly once")
    return policy


def _bound_file(base, ref, require, what, inside=None):
    """The bytes of a hash-bound file inside the repository (or inside `inside` below it)."""
    require(isinstance(ref, dict) and isinstance(ref.get("path"), str) and isinstance(ref.get("sha256"), str),
            what + " reference")
    path = (base / ref["path"]).resolve()
    limit = (base / inside).resolve() if inside else base
    require(path.is_relative_to(limit) and path.is_file(), what + " outside its folder or missing")
    raw = path.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == ref["sha256"], what + " hash")
    return raw


def _validate_probation(sid, prob, strats, base, runtime_root, require):
    """ACTIVE_PROBATION: the confirmed sides, a reduced size, the bound evidence and a registered forward test."""
    def number(x):
        return not isinstance(x, bool) and isinstance(x, (int, float))
    require(isinstance(prob, dict) and set(prob) == PROBATION_KEYS, "probation record keys")
    sides = prob["sides"]
    require(isinstance(sides, list) and bool(sides) and len(set(sides)) == len(sides)
            and set(sides) <= {"long", "short"}, "probation sides")
    m = prob["risk_multiplier"]
    require(number(m) and 0 < m <= MAX_PROBATION_RISK_MULTIPLIER, "probation risk multiplier must be in (0, %s]"
            % MAX_PROBATION_RISK_MULTIPLIER)
    ev = json.loads(_bound_file(base, prob["evidence"], require, "probation evidence"))
    require(ev.get("schema") == PROBATION_EVIDENCE_SCHEMA, "probation evidence schema")
    try:
        current = runtime_implementation_hash(REPO_ROOT if runtime_root is None else runtime_root)
    except OSError:
        current = None
    require(current is not None and (ev.get("code") or {}).get("runtime_implementation_hash") == current,
            "probation evidence was produced for another runtime implementation (re-bind it with tools/v9/confirm.py)")
    tests = prob["forward_tests"]
    require(isinstance(tests, dict) and set(tests) == set(sides), "one forward test per probation side")
    for side in sides:
        rows = [h for h in ev.get("hypotheses") or [] if isinstance(h, dict) and h.get("strategy_id") == sid
                and h.get("side") == side]
        require(len(rows) == 1, f"probation evidence row for {sid} {side}")
        h = rows[0]
        require(h.get("verdict") == "CONFIRMED" and h.get("failing") == [] and isinstance(h.get("checks"), dict)
                and bool(h["checks"]) and all(v is True for v in h["checks"].values()),
                f"{sid} {side} is not CONFIRMED by the probation evidence")
        require(h.get("runtime_definition_hash") == digest(strats[sid]),
                f"{sid} runtime definition differs from the confirmed one")
        window = (h.get("late_entry") or {}).get("trade_window_hours")
        require(number(window) and window > 0, f"{sid} {side} has no confirmed entry window")
        band = (h.get("demotion_band") or {}).get("table")
        require(isinstance(band, list) and bool(band) and all(isinstance(b, dict) and number(b.get("trades"))
                                                              and number(b.get("p05_mean_R")) for b in band),
                f"{sid} {side} demotion band")
        require(isinstance(h.get("expectation"), dict), f"{sid} {side} expectation")
        ft = tests[side]
        require(isinstance(ft, dict) and set(ft) == FORWARD_TEST_KEYS, f"{sid} {side} forward test keys")
        reg = json.loads(_bound_file(base, ft, require, f"{sid} {side} forward-test registration", LEDGER_DIR))
        params = reg.get("params") or {}
        require(reg.get("kind") == "REGISTRATION" and reg.get("status") == "REGISTERED" and reg.get("authority") == "NONE"
                and reg.get("experiment_id") == ft["experiment_id"], f"{sid} {side} forward-test registration record")
        require(params.get("strategy_id") == sid and params.get("side") == side and params.get("risk_multiplier") == m,
                f"{sid} {side} forward test registered for other parameters")
        require(isinstance(ft["effective_from"], int) and not isinstance(ft["effective_from"], bool)
                and ft["effective_from"] == reg.get("evaluation_start")
                and isinstance(reg.get("registered_at"), int) and reg["registered_at"] <= ft["effective_from"],
                f"{sid} {side} probation must start at its registered forward-only evaluation start")


def probation_terms(row, root=REPO_ROOT):
    """The bound evidence terms of a validated ACTIVE_PROBATION row, per side: the confirmed entry window, the
    out-of-sample expectation, the demotion band and the forward test. None for any other row. Call only on a policy
    that validate() accepted (it re-reads the bound file; its hash was checked at load)."""
    prob = row.get("probation") if isinstance(row, dict) else None
    if row.get("deployment_state") != "ACTIVE_PROBATION" or not isinstance(prob, dict):
        return None
    raw = (Path(root) / prob["evidence"]["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != prob["evidence"]["sha256"]:
        raise ValueError("STRATEGY_POLICY_INVALID: probation evidence hash")
    ev = json.loads(raw)
    sides = {}
    for side in prob["sides"]:
        h = next(x for x in ev["hypotheses"] if x["strategy_id"] == row["strategy_id"] and x["side"] == side)
        sides[side] = {"entry_window_s": int(h["late_entry"]["trade_window_hours"] * 3600),
                       "expectation": h["expectation"], "trades": h["trades"],
                       "holdout": {k: h["windows"]["holdout"].get(k) for k in ("n", "mean_R", "lower_95", "upper_95")},
                       "holdout_holm_p": h.get("holdout_holm_p"),
                       "design_window": {k: h["windows"]["design_window"].get(k)
                                         for k in ("n", "mean_R", "lower_95", "upper_95")},
                       "demotion_band": h["demotion_band"], "forward_test": prob["forward_tests"][side]}
    return {"risk_multiplier": prob["risk_multiplier"], "sides": sides, "evidence": dict(prob["evidence"]),
            "evidence_as_of": ev.get("as_of"), "dataset_sha256": (ev.get("inputs") or {}).get("dataset_sha256")}


def load(strats, path=PATH):
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate(policy, strats, REPO_ROOT)
