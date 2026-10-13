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

VERSION = "v8.quant-strategy-policy/1"
PATH = Path(__file__).with_name("quant_strategy_policy.json")
DEPLOYMENT = {"LEGACY_HOLDOVER", "ACTIVE_REQUALIFIED", "PAPER_ONLY", "DISABLED"}
RESEARCH = {"REQUALIFIED", "PROBATION", "REJECTED", "INSUFFICIENT_EVIDENCE", "INVALIDATED"}
ENABLED = {"LEGACY_HOLDOVER", "ACTIVE_REQUALIFIED"}
REPO_ROOT = PATH.parent.parent
RUNTIME_IMPLEMENTATION_FILES = ("quant.py",)


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
    require(all(isinstance(s, str) for s in order) and len(set(order)) == len(order), "duplicate or invalid order")
    require(set(order) == set(enabled), "order must contain every deployment-enabled strategy exactly once")
    return policy


def load(strats, path=PATH):
    policy = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate(policy, strats, REPO_ROOT)
