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
    """Where quant strategy authority comes from today (exposed, not changed): quant.py runs its ORDER tuple
    regardless of any research verdict, and tools/research/qexport.py assigns the verdict "live" to its FINAL tuple
    before any evidence test runs. Read with ast (qexport imports numpy/pandas), never executed."""
    import ast
    out = {"quant_runtime_order": None, "research_final": None, "research_verdict_preassigned_live": None,
           "research_file_verdicts": None, "files": {}}
    try:
        import quant as q
        out["quant_runtime_order"] = list(q.ORDER)
    except Exception:  # noqa: BLE001
        pass
    path = os.path.join(ROOT, "tools", "research", "qexport.py")
    out["files"]["tools/research/qexport.py"] = file_sha(path)
    out["files"]["quant.py"] = file_sha(os.path.join(ROOT, "quant.py"))
    out["files"]["quant_research.json"] = file_sha(os.path.join(ROOT, "quant_research.json"))
    try:
        with open(path) as fh:
            tree = ast.parse(fh.read())
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "FINAL" for t in node.targets):
                out["research_final"] = list(ast.literal_eval(node.value))
            if isinstance(node, ast.FunctionDef) and node.name == "verdict" and node.body:
                first = node.body[0]
                if isinstance(first, ast.If) and "FINAL" in ast.dump(first.test):
                    ret = next((b for b in first.body if isinstance(b, ast.Return)), None)
                    val = getattr(ret, "value", None)
                    lead = val.elts[0] if isinstance(val, ast.Tuple) and val.elts else None
                    out["research_verdict_preassigned_live"] = isinstance(lead, ast.Constant) and lead.value == "live"
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {e}"[:200]
    try:
        with open(os.path.join(ROOT, "quant_research.json")) as fh:
            st = json.load(fh).get("strategies") or {}
        out["research_file_verdicts"] = {k: (v or {}).get("verdict") for k, v in sorted(st.items())}
    except (OSError, ValueError, AttributeError):
        pass
    return out


def header(engine, ts):
    from . import ENGINE_VERSION, SCHEMA
    return {"schema": SCHEMA, "engine": engine, "scan_id": scan_id(ts), "ts": int(ts), "git_sha": git_sha(),
            "git_ref": git_ref(), "repo": os.environ.get("GITHUB_REPOSITORY"), "config_hash": config_hash(engine),
            "engine_version": engine_version(engine), "audit_version": ENGINE_VERSION,
            "identity_config_hash": identity_config_hash()}
