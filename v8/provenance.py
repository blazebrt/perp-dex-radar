"""Run provenance: scan id, git commit, deterministic config hashes and file hashes.

Config hashes cover what decides an engine's output - its CFG (minus the schedule values the workflow sets
through the environment), its strategy definitions, the ticker lists, and the research files that decide what is
"tested" - serialised canonically (sorted keys, functions by name, no memory addresses). No secret is ever read:
API keys and webhook URLs live in the environment and are not part of any CFG."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_KEYS = {"schedule_minute", "schedule_every_min"}      # set by the workflow, not part of the strategy config
RESEARCH_FILES = {"radar": [], "quant": ["quant_research.json"], "swing": ["picks_research.json"],
                  "day": ["picks_research.json"], "smart": ["smart_research.json"]}


def canonical(x):
    """A JSON-ready structure with a stable form: sorted dict keys, sets sorted, functions by qualified name."""
    if isinstance(x, dict):
        return {str(k): canonical(v) for k, v in sorted(x.items(), key=lambda kv: str(kv[0]))}
    if isinstance(x, (list, tuple)):
        return [canonical(v) for v in x]
    if isinstance(x, (set, frozenset)):
        return sorted(canonical(v) for v in x)
    if isinstance(x, float):
        return repr(x)
    if isinstance(x, (str, int, bool)) or x is None:
        return x
    if callable(x):
        return "fn:" + getattr(x, "__module__", "?") + "." + getattr(x, "__qualname__", getattr(x, "__name__", "?"))
    if isinstance(x, re.Pattern):
        return "re:" + x.pattern
    return "obj:" + type(x).__name__


def sha(obj):
    return hashlib.sha256(json.dumps(canonical(obj), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_sha(path):
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def _cfg(c):
    return {k: v for k, v in c.items() if k not in ENV_KEYS}


def identity_config():
    """Everything that decides an asset's identity state (v8.identity), for the resolver config hash."""
    import scanner as sc
    ID = sc.IDENTITY
    return {"version": ID.VERSION, "tol": ID.TOL, "extended_tradfi": sorted(ID.EXTENDED_TRADFI_CATEGORIES),
            # v8.identity/3 (Phase 5): Extended Crypto is wrapper evidence only; Lighter token-list RWA is tradfi
            # evidence; an exposure seen only through a failed exposure check is not verified by the ticker list
            "extended_crypto_wrapper": sorted(ID.EXTENDED_CRYPTO_CATEGORIES),
            "lighter_tradfi_asset_types": sorted(ID.LIGHTER_TRADFI_ASSET_TYPES),
            "lighter_asset_types": list(ID.LIGHTER_ASSET_TYPES),
            "exposure_checks": dict(sorted(ID.EXPOSURE_CHECKS.items())), "exposure_check_ok": ID.XCHECK_OK,
            # v8.identity/4 (Phase 6): the known-crypto list is bound to at most one price-coherent exposure
            "rules": ID.RULES, "previous_version": ID.PREVIOUS_VERSION,
            "ticker_binding": {"bound": ID.R_BOUND, "unbound": ID.R_UNBOUND, "results": list(ID.TICKER_RESULTS),
                               "max_bound_exposures": 1},
            "aster_neutral": sorted(ID.ASTER_NEUTRAL_UNDERLYING), "base_only_symbol_venues": list(ID.BASE_ONLY_SYMBOL_VENUES),
            "aster_tradfi_subtypes": sorted(ID.ASTER_TRADFI_SUBTYPES),
            "variational_tradfi_name_prefix": ID.VARIATIONAL_TRADFI_NAME_PREFIX,
            "quote_suffixes": list(ID.QUOTE_SUFFIXES), "min_candidate_len": ID.MIN_CANDIDATE_LEN,
            "tradfi": sorted(sc.TRADFI), "known_crypto": sorted(sc.KNOWN_CRYPTO), "fx": sorted(sc.FX_CODES),
            "tradfi_name": sc.TRADFI_NAME.pattern}


def identity_config_hash():
    return sha(identity_config())


def engine_config(engine):
    """The decision-relevant configuration of one engine (a dict, hashed by config_hash)."""
    import scanner as sc
    base = {"universe": {"dexes": sc.DEXES, "sources": sc.SOURCES, "tradfi": sc.TRADFI, "known_crypto": sc.KNOWN_CRYPTO,
                         "alias": sc.ALIAS, "symbol_override": {f"{a}:{b}": v for (a, b), v in sc.SYMBOL_OVERRIDE.items()},
                         "fx": sc.FX_CODES, "tradfi_name": sc.TRADFI_NAME.pattern,
                         "trade_dexes": sc.CFG.get("trade_dexes"), "min_dex_vol": sc.CFG.get("min_dex_vol"),
                         # v8 Phase 2: the universe identity and liquidity semantics that decide the universe
                         "identity": identity_config(),
                         "liquidity": sc.LIQUIDITY.VERSION}}
    if engine == "radar":
        base["cfg"] = _cfg(sc.CFG)
        base["strategies"] = sc.STRATEGIES
        base["user_strategies"] = file_sha(os.path.join(ROOT, sc.CFG.get("user_file") or "strategies.json"))
        base["version"] = sc.VERSION
    elif engine == "quant":
        import quant as q
        base.update(cfg=q.CFG, strats=q.STRATS, version=q.VERSION)
    elif engine in ("swing", "day"):
        import picks as p
        base.update(cfg=p.CFG, long_w=p.LONG_W, short_w=p.SHORT_W, day_w=p.DAY_W, version=p.VERSION)
    elif engine == "smart":
        import smart as s
        base.update(cfg=s.CFG, version=s.VERSION)
    elif engine == "discovery":      # v8 Phase 7: observational; its thresholds order research attention only
        from . import discovery as ds
        base.update(version=ds.VERSION, thresholds=ds.THRESHOLDS, flags={k: v[0] for k, v in ds.FLAGS.items()},
                    stage2_n=sc.CFG.get("stage2_n"), stage2_extra=sc.CFG.get("stage2_extra"))
    for f in RESEARCH_FILES.get(engine, []):
        base["research:" + f] = file_sha(os.path.join(ROOT, f))
    return base


def config_hash(engine):
    try:
        return sha(engine_config(engine))
    except Exception as e:  # noqa: BLE001
        return f"error:{type(e).__name__}"


def engine_version(engine):
    try:
        if engine in ("radar", "universe"):
            import scanner as m
        elif engine == "quant":
            import quant as m
        elif engine in ("swing", "day"):
            import picks as m
        elif engine == "smart":
            import smart as m
        elif engine == "discovery":
            from . import discovery as m
        else:
            return None
        return m.VERSION
    except Exception:  # noqa: BLE001
        return None


def _git(*args):
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() or None if r.returncode == 0 else None
    except Exception:  # noqa: BLE001
        return None


def git_sha():
    return os.environ.get("GITHUB_SHA") or _git("rev-parse", "HEAD")


def git_ref():
    return os.environ.get("GITHUB_REF_NAME") or _git("rev-parse", "--abbrev-ref", "HEAD")


def scan_id(ts):
    """The workflow run (shared by every engine of one scan) or, offline, an explicit V8_SCAN_ID or the time."""
    if os.environ.get("V8_SCAN_ID"):
        return os.environ["V8_SCAN_ID"]
    run = os.environ.get("GITHUB_RUN_ID")
    if run:
        return f"gh-{run}-{os.environ.get('GITHUB_RUN_ATTEMPT', '1')}"
    return f"local-{int(ts)}"


def strategy_authority():
    """Deployment comes from reviewed policy; the governed report has no runtime authority."""
    from . import strategy_policy as SP, strategy_authority as SA
    out = {"research_verdict_preassigned_live": False, "research_final": [], "files": {}}
    try:
        import quant as q
        policy = SP.load(q.STRATS)
        out.update(runtime_policy_schema=SP.VERSION, runtime_policy_hash=SP.digest(policy),
                   quant_runtime_order=policy["runtime_order"], deployment_states={r["strategy_id"]: r["deployment_state"] for r in policy["strategies"]},
                   research_states={r["strategy_id"]: r["research_state"] for r in policy["strategies"]},
                   health=["STRATEGY_POLICY_OK"],
                   legacy_holdover_count=sum(r["deployment_state"] == "LEGACY_HOLDOVER" for r in policy["strategies"]))
    except (OSError, ValueError, TypeError, KeyError) as e:
        out.update(health=["STRATEGY_POLICY_INVALID"], error=str(e))
    out.update(adjudication_version=SA.VERSION, trial_census_version="v8.strategy-trial-census/1",
               trial_census_complete=False, matched_control_version="v8.matched-controls/1",
               matched_control_status="FULL_MATCHED_CONTROL_UNAVAILABLE", multiple_testing_version="v8.multiple-testing/1",
               multiple_testing_status="MULTIPLE_TESTING_INSUFFICIENT_DATA", requalified_strategy_count=0)
    out["health"].extend(["TRIAL_CENSUS_INCOMPLETE", "MATCHED_CONTROLS_INCOMPLETE", "STRATEGY_EVIDENCE_INSUFFICIENT"])
    for name in ("research_strategy_trial_census.json", "research_strategy_adjudication.json"):
        path = os.path.join(ROOT, "research", "phase9", name)
        out[name + "_hash"] = file_sha(path)
    try:
        with open(os.path.join(ROOT, "research", "phase9", "research_strategy_adjudication.json")) as fh:
            report = json.load(fh)
        if report.get("schema") != SA.VERSION:
            raise ValueError("unsupported adjudication schema")
        out["adjudicated_research_states"] = {r["strategy_id"]: r["research_state"] for r in report["strategies"]}
        out["requalified_strategy_count"] = sum(v == "REQUALIFIED" for v in out["adjudicated_research_states"].values())
        out["adjudication_provenance"] = report["provenance"]
    except (OSError, ValueError, KeyError) as e:
        out["adjudication_status"] = "UNAVAILABLE"
        out["adjudication_error"] = str(e)
    for name in ("tools/research/qexport.py", "quant.py", "quant_research.json"):
        out["files"][name] = file_sha(os.path.join(ROOT, name))
    with open(os.path.join(ROOT, "quant_research.json")) as fh:
        out["legacy_stored_verdicts"] = {k: v.get("verdict") for k, v in json.load(fh)["strategies"].items()}
    out["research_file_verdicts"] = {k: "LEGACY_SURVIVORSHIP_UNQUALIFIED" for k in out["legacy_stored_verdicts"]}
    out["legacy_portfolio_label"] = "LEGACY_DIAGNOSTIC / NOT STRATEGY AUTHORITY"
    return out


def header(engine, ts):
    from . import ENGINE_VERSION, SCHEMA
    return {"schema": SCHEMA, "engine": engine, "scan_id": scan_id(ts), "ts": int(ts), "git_sha": git_sha(),
            "git_ref": git_ref(), "repo": os.environ.get("GITHUB_REPOSITORY"), "config_hash": config_hash(engine),
            "engine_version": engine_version(engine), "audit_version": ENGINE_VERSION,
            "identity_config_hash": identity_config_hash()}
