"""Static, deterministic historical trial census. Never executes a historical research/grid script."""
from __future__ import annotations

import ast
import hashlib
import itertools
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE = "c2d48549a8012fa77862cb57d7e706620fa85a18"
VERSION = "v8.strategy-trial-census/1"
SOURCES = ("tools/research/qexport.py", "tools/research/qstrat.py", "tools/research/qgrid.py",
           "tools/research/qrun.py", "tools/research/qrun3y.py")
CODE_FILES = ("tools/research/qstrat.py", "tools/research/qind.py", "tools/research/qdata.py",
              "tools/research/qsim.py")


def digest(x):
    return hashlib.sha256(json.dumps(x, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", "-c", "safe.directory=*", *args], cwd=ROOT).decode()


def static(node):
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
        return static(node.left) * static(node.right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "dict":
        return {k.arg: static(k.value) for k in node.keywords}
    return ast.literal_eval(node)


def assignment(source, name):
    for n in ast.parse(source).body:
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets):
            return n.value
    raise ValueError("missing assignment " + name)


def defaults(source):
    out = {}
    for n in ast.parse(source).body:
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"):
            out[n.name] = {a.arg: static(v) for a, v in zip(n.args.args[-len(n.args.defaults):], n.args.defaults)}
    return out


def catalog():
    """Canonical exported candidates, with defaults made explicit for deduplication."""
    source = (ROOT / SOURCES[0]).read_text(encoding="utf-8")
    defs = defaults((ROOT / SOURCES[1]).read_text(encoding="utf-8"))
    code_hash = digest({p: hashlib.sha256((ROOT / p).read_text(encoding="utf-8").encode()).hexdigest() for p in CODE_FILES})
    result = []
    node = assignment(source, "TESTED")
    for key, value in zip(node.keys, node.values):
        sid, fn, kw = static(key), value.elts[0].attr, static(value.elts[1])
        params = dict(defs[fn], **kw)
        result.append({"strategy_id": sid, "implementation": fn, "params": params, "explicit_params": kw,
                       "parameter_hash": digest(params), "code_hash": code_hash, "code_files": list(CODE_FILES),
                       "family": static(value.elts[3]), "timeframe": static(value.elts[4])})
    return result


def build():
    commits = git("log", BASE, "--format=%H", "--", *SOURCES).splitlines()
    trials = {}
    revisions = []
    grid_counts = {}
    for commit in commits:
        sources = {}
        for path in SOURCES:
            sources[path] = git("show", f"{commit}:{path}")
        defs = defaults(sources[SOURCES[1]])
        code = {}
        for path in CODE_FILES:
            # Git blob content, not platform newline conversion.
            code[path] = hashlib.sha256(git("show", f"{commit}:{path}").encode()).hexdigest()
        code_hash = digest(code)
        revisions.append({"commit": commit, "files": {p: hashlib.sha256(s.encode()).hexdigest() for p, s in sources.items()}})

        def add(sid, fn, kw, classification, source):
            params = dict(defs[fn], **kw)
            key = digest({"implementation": fn, "parameter_hash": digest(params), "code_hash": code_hash})
            row = trials.setdefault(key, {"trial_id": key, "implementation": fn, "params": params,
                                        "parameter_hash": digest(params), "code_hash": code_hash, "aliases": [],
                                        "classification": classification, "evidence": []})
            row["aliases"] = sorted(set(row["aliases"] + [sid]))
            if classification == "PROVEN_CONSIDERED":
                row["classification"] = classification
            row["evidence"].append({"commit": commit, "path": source, "classification": classification})

        for path, name in ((SOURCES[0], "TESTED"), (SOURCES[1], "LIBRARY")):
            node = assignment(sources[path], name)
            for key, value in zip(node.keys, node.values):
                fn = value.elts[0]
                add(static(key), fn.attr if isinstance(fn, ast.Attribute) else fn.id, static(value.elts[1]),
                    "PROVEN_CONSIDERED", path)
        node = assignment(sources[SOURCES[2]], "grids")
        for key, value in zip(node.keys, node.values):
            sid, fn, grid = static(key), value.elts[0].attr, static(value.elts[1])
            keys = list(grid)
            count = 0
            for vals in itertools.product(*(grid[k] for k in keys)):
                kw = dict(zip(keys, vals))
                if sid == "TREND_EMA" and kw["fast"] >= kw["slow"]:
                    continue
                add(sid, fn, kw, "ENCODED_SEARCH_SPACE", SOURCES[2])
                count += 1
            grid_counts.setdefault(sid, count)
    # Saved results prove reported runs, but predate the imported implementation. Do not
    # invent a code binding or count them a second time as distinct trials.
    result_commits = git("log", BASE, "--format=%H", "--", "quant_research.json").splitlines()
    unbound = []
    for commit in result_commits:
        result = json.loads(git("show", f"{commit}:quant_research.json"))
        for sid, row in sorted(result.get("strategies", {}).items()):
            unbound.append({"strategy_id": sid, "commit": commit, "path": "quant_research.json",
                            "classification": "PROVEN_RUN", "code_binding": "UNKNOWN_HISTORICAL_STATUS",
                            "parameter_hash": digest(row.get("params")), "included_as_extra_distinct_trial": False})
    inventory = sorted(set(git("log", BASE, "--name-only", "--format=", "--", "*research*", "*grid*",
                               "*result*", "*trades*").splitlines()) - {""})
    rows = sorted(trials.values(), key=lambda x: x["trial_id"])
    return {"schema": VERSION, "base": BASE, "complete": False, "status": "TRIAL_CENSUS_INCOMPLETE",
            "known_lower_bound": len(rows), "upper_bound": None, "trials": rows, "revisions": revisions,
            "reported_runs_without_code_binding": unbound, "history_file_inventory": inventory,
            "uncertainty": ["Research source imported as one commit; earlier local edits and trials unavailable.",
                            "Saved results predate source import; exact historical implementation cannot be proven.",
                            "Encoded grid proves consideration, not execution. CLI windows/overrides are not logged.",
                            "No complete historical trial-return matrix; lower bound cannot support requalification."],
            "deduplication": "implementation + expanded parameter hash + relevant code hash",
            "grid_settings": grid_counts}
